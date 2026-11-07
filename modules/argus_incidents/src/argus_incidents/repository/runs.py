"""The queue of incidents waiting to be walked.

The alert endpoint writes a row here and answers; a worker takes it and invokes
the graph. That is the whole of it, and it is what makes an investigation
outlive the request that asked for one - a connection that timed out can no
longer be the only handle on a running incident.

Claiming is `FOR UPDATE SKIP LOCKED`, the standard Postgres queue claim: two
workers cannot take the same run, and a worker that dies mid-claim releases its
lock rather than wedging the row. The lease is a separate thing from the lock
and answers a question the lock cannot - whether the worker that took this run
is still walking it - because a dead worker's lock dies with its connection and
leaves nothing behind to distinguish it from a slow one.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum
from typing import Final

import psycopg
from argus_core import Fence, UuidStr
from argus_core.models import IncidentStatus
from psycopg.rows import class_row
from pydantic import BaseModel


class RunState(StrEnum):
    """Where a run is, which is not where its incident is.

    An incident's status says what Argus knows about the failure; a run's state
    says whether anything is currently thinking about it. A queued run on a
    resolved incident is a bug, and it takes two columns to be able to see it.
    """

    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class Run(BaseModel):
    """One walk of the graph, as the queue holds it.

    `incident_id` rather than the incident: a worker needs the thread to invoke
    the graph on, and reading the incident is the graph's own business. The
    alert is already on the incident row, so carrying a copy here would be a
    second version of it to keep in step.

    `epoch` is which claim of the run this is: every claim moves it on, so a
    holder whose run was taken back holds an epoch the row no longer has.

    `retries` is how many times the run was requeued to be tried again, and
    `not_before` when it may next be taken - see `try_again_later`.
    """

    id: UuidStr
    incident_id: UuidStr
    state: RunState
    claimed_by: str | None
    leased_until: datetime | None
    epoch: int
    failure_reason: str | None
    created_at: datetime
    retries: int
    not_before: datetime | None


# Every column a `Run` is read from, in its order.
_A_RUN: Final = ("id, incident_id, state, claimed_by, leased_until, epoch, failure_reason, "
                 "created_at, retries, not_before")


def enqueue(conn: psycopg.Connection, incident_id: str) -> str:
    """Puts one incident in line to be walked, and returns the run's id.

    Committed here rather than left to the caller: the endpoint's whole promise
    is that the run outlives the request, and a run still sitting in an
    uncommitted transaction is a promise kept only until the process ends.
    """
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO incident_run (incident_id, state) VALUES (%s, %s) RETURNING id",
            (incident_id, RunState.QUEUED)
        )
        row = cursor.fetchone()
        assert row is not None
    conn.commit()

    return str(row[0])


def claim(conn: psycopg.Connection,
          claimed_by: str,
          lease: timedelta) -> Run | None:
    """Takes one run to walk, or answers that there is nothing to take.

    `SKIP LOCKED` is what makes a second worker harmless rather than merely
    unlikely: it passes over a row another worker is claiming instead of
    queueing behind it, so two workers starting together take two different
    runs and never the same one twice.

    A run whose lease has run out is taken back, because the worker holding it
    is no longer walking it - a claim is renewed while a run is alive, so an
    expired lease means the holder stopped. It is resumed rather than restarted:
    the graph is invoked on the incident's own thread, and the checkpointer
    replays what was already done.

    Every claim moves the run's epoch on, a taking-back included, so the claim
    it replaced can tell it no longer holds the run.

    A run requeued to be tried again waits out its `not_before` first - unless
    its incident was withdrawn meanwhile. What a withdrawn incident's walk does
    next is put back what it changed, which needs no model, and Argus's changes
    would otherwise stand until the wait was over. A resolution keeps the wait:
    its walk goes on to the write-up, which needs the model the wait is for.
    """
    with conn.cursor(row_factory=class_row(Run)) as cursor:
        cursor.execute(
            "UPDATE incident_run SET state = %s, claimed_by = %s, "
            "leased_until = now() + %s, epoch = epoch + 1 "
            "WHERE id = ("
            "    SELECT run.id FROM incident_run run JOIN incident ON incident.id = run.incident_id"
            "    WHERE (run.state = %s AND (run.not_before IS NULL OR run.not_before <= now()"
            "                               OR incident.status = %s))"
            "       OR (run.state = %s AND run.leased_until < now())"
            "    ORDER BY run.created_at"
            "    LIMIT 1"
            "    FOR UPDATE OF run SKIP LOCKED"
            ") "
            f"RETURNING {_A_RUN}",
            (RunState.RUNNING, claimed_by, lease, RunState.QUEUED, IncidentStatus.WITHDRAWN,
             RunState.RUNNING)
        )
        claimed = cursor.fetchone()
    conn.commit()

    return claimed


def renew(conn: psycopg.Connection, held: Run, lease: timedelta) -> bool:
    """Says the worker holding this run is still walking it, and answers
    whether it still holds it.

    An investigation legitimately takes minutes, so a lease set once at claim
    time would either be long enough to keep a dead worker's run from being
    taken back for as long, or short enough to let a live worker's run be taken from it.
    Renewing is what lets it be short.

    Only the claim that holds the run renews it: one whose run was taken back,
    or settled, extends nothing and is told so - a lease extended by the holder
    it was taken from would keep the new holder's run from being taken back
    when that holder stops.
    """
    with conn.cursor() as cursor:
        cursor.execute(
            "UPDATE incident_run SET leased_until = now() + %s "
            "WHERE id = %s AND epoch = %s AND state = %s RETURNING id",
            (lease, held.id, held.epoch, RunState.RUNNING)
        )
        still_held = cursor.fetchone() is not None
    conn.commit()

    return still_held


def finish(conn: psycopg.Connection, held: Run) -> bool:
    """Marks a run walked to its end, whatever end the graph reached, and
    answers whether this claim still held it to mark.

    Nothing about whether the incident was resolved: a walk that escalated is
    as finished as one that resolved, and the incident's own status is where
    that difference is recorded.
    """
    return _settle(conn, held, RunState.DONE, failure_reason=None)


def fail(conn: psycopg.Connection, held: Run, reason: str) -> bool:
    """Records that a run stopped badly, and why, and answers whether this
    claim still held it to record.

    The reason is stored rather than logged, because an incident whose run
    failed has to be tellable from one still being worked - and a log line is
    not something the incident can be read alongside.
    """
    return _settle(conn, held, RunState.FAILED, failure_reason=reason)


def try_again_later(conn: psycopg.Connection, held: Run, wait: timedelta) -> bool:
    """Requeues a run to be taken again once `wait` is over, counted as one
    more try, and answers whether this claim still held it to requeue.

    For a walk that could not get an answer from the model for now. The next
    claim resumes it from its checkpoint, where it stopped, so nothing the walk
    did is undone or done again - its claims on actions included, which the
    resumed walk answers as it would a dead worker's.

    Only by the claim that holds the run, as settling is, and for the same
    reason: one since taken back would take the run from the worker walking it.
    Committing is the caller's.
    """
    with conn.cursor() as cursor:
        cursor.execute(
            "UPDATE incident_run SET state = %s, retries = retries + 1, "
            "not_before = now() + %s, claimed_by = NULL, leased_until = NULL "
            "WHERE id = %s AND epoch = %s AND state = %s RETURNING id",
            (RunState.QUEUED, wait, held.id, held.epoch, RunState.RUNNING)
        )

        return cursor.fetchone() is not None


def is_held(conn: psycopg.Connection, held: Fence) -> bool:
    """Whether the run is still at the claim `held` names, and still being
    walked.

    A read and nothing more: no lock is taken, because what asks is a walk
    deciding whether its next turn is worth paying for, and a run taken back a
    moment after the answer is caught by the next write, which the database
    refuses.
    """
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT 1 FROM incident_run WHERE id = %s AND epoch = %s AND state = %s",
            (held.run_id, held.epoch, RunState.RUNNING)
        )

        return cursor.fetchone() is not None


def hold_for_a_change(conn: psycopg.Connection, held: Fence) -> bool:
    """Whether the run is still at the claim `held` names, and still being
    walked - and, where it is, the run kept so until `conn`'s transaction ends.

    Asked by the write tier before it changes the world for a walk. Kept, not
    only read, because a run taken back between the answer and the change would
    have the change made for a claim that no longer holds it. The run's row is
    share-locked, which a claim skips, and a renewal or a settling waits on, and
    which the walk's own fenced writes share. So a long change can outlast the
    lease: the run is still not taken back, and the renewal lands once the
    change is done. Committing or rolling back is the caller's, once the change
    is made.
    """
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT 1 FROM incident_run WHERE id = %s AND epoch = %s AND state = %s "
            "FOR SHARE",
            (held.run_id, held.epoch, RunState.RUNNING)
        )

        return cursor.fetchone() is not None


def get(conn: psycopg.Connection, run_id: str) -> Run | None:
    """One run by its id."""
    with conn.cursor(row_factory=class_row(Run)) as cursor:
        cursor.execute(
            f"SELECT {_A_RUN} FROM incident_run WHERE id = %s",
            (run_id,)
        )

        return cursor.fetchone()


def get_run_for_incident(conn: psycopg.Connection, incident_id: str) -> Run | None:
    """The most recent run recorded for one incident.

    Named for what it looks up by, rather than sharing `get`'s name: the
    argument is not the run's identity, and one incident can have been walked
    more than once.
    """
    with conn.cursor(row_factory=class_row(Run)) as cursor:
        cursor.execute(
            f"SELECT {_A_RUN} FROM incident_run "
            "WHERE incident_id = %s ORDER BY created_at DESC LIMIT 1",
            (incident_id,)
        )

        return cursor.fetchone()


def get_unsettled_runs(conn: psycopg.Connection) -> list[Run]:
    """Every run still waiting to be walked or being walked, oldest first.

    Both, because a run waiting is as live as one being walked: a worker takes
    it the moment one is free, and acts on whatever is there when it does. A
    run that finished or failed acts on nothing again.
    """
    with conn.cursor(row_factory=class_row(Run)) as cursor:
        cursor.execute(
            f"SELECT {_A_RUN} FROM incident_run "
            "WHERE state IN (%s, %s) ORDER BY created_at",
            (RunState.QUEUED, RunState.RUNNING)
        )

        return cursor.fetchall()


def _settle(conn: psycopg.Connection,
            held: Run,
            state: RunState,
            failure_reason: str | None) -> bool:
    """How a run stops, either way - only by the claim that holds it.

    The lease is released with it: a settled run is nobody's, and leaving a
    worker's name on it would make a finished run look like one being walked by
    somebody who never let go.

    A claim since taken back settles nothing: the run is another worker's to
    walk, and settling it here would end that walk where nothing would ever
    take it up again. The lease does not decide that - the epoch does - so a
    holder whose lease ran out with nobody taking the run settles it still.

    Committing is the caller's. A failed run's claims, its escalation and its
    failure are one moment, and the caller is the one holding all three.
    """
    with conn.cursor() as cursor:
        cursor.execute(
            "UPDATE incident_run SET state = %s, failure_reason = %s, "
            "claimed_by = NULL, leased_until = NULL "
            "WHERE id = %s AND epoch = %s AND state = %s RETURNING id",
            (state, failure_reason, held.id, held.epoch, RunState.RUNNING)
        )

        return cursor.fetchone() is not None
