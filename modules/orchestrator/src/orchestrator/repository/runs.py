from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum

import psycopg
from psycopg.rows import class_row
from pydantic import BaseModel

from orchestrator.repository._types import UuidStr

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
    """

    id: UuidStr
    incident_id: UuidStr
    state: RunState
    claimed_by: str | None
    leased_until: datetime | None
    failure_reason: str | None
    created_at: datetime


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
    """
    with conn.cursor(row_factory=class_row(Run)) as cursor:
        cursor.execute(
            "UPDATE incident_run SET state = %s, claimed_by = %s, "
            "leased_until = now() + %s "
            "WHERE id = ("
            "    SELECT id FROM incident_run"
            "    WHERE state = %s OR (state = %s AND leased_until < now())"
            "    ORDER BY created_at"
            "    LIMIT 1"
            "    FOR UPDATE SKIP LOCKED"
            ") "
            "RETURNING id, incident_id, state, claimed_by, leased_until, "
            "failure_reason, created_at",
            (RunState.RUNNING, claimed_by, lease, RunState.QUEUED, RunState.RUNNING)
        )
        claimed = cursor.fetchone()
    conn.commit()

    return claimed


def renew(conn: psycopg.Connection, run_id: str, lease: timedelta) -> None:
    """Says the worker holding this run is still walking it.

    An investigation legitimately takes minutes, so a lease set once at claim
    time would either be long enough to make a dead worker's run unreclaimable
    for as long, or short enough to let a live worker's run be taken from it.
    Renewing is what lets it be short.
    """
    with conn.cursor() as cursor:
        cursor.execute(
            "UPDATE incident_run SET leased_until = now() + %s WHERE id = %s",
            (lease, run_id)
        )
    conn.commit()


def finish(conn: psycopg.Connection, run_id: str) -> None:
    """Marks a run walked to its end, whatever end the graph reached.

    Nothing about whether the incident was resolved: a walk that escalated is
    as finished as one that resolved, and the incident's own status is where
    that difference is recorded.
    """
    _settle(conn, run_id, RunState.DONE, failure_reason=None)


def fail(conn: psycopg.Connection, run_id: str, reason: str) -> None:
    """Records that a run stopped badly, and why.

    The reason is stored rather than logged, because an incident whose run
    failed has to be tellable from one still being worked - and a log line is
    not something the incident can be read alongside.
    """
    _settle(conn, run_id, RunState.FAILED, failure_reason=reason)


def get(conn: psycopg.Connection, run_id: str) -> Run | None:
    """One run by its id."""
    with conn.cursor(row_factory=class_row(Run)) as cursor:
        cursor.execute(
            "SELECT id, incident_id, state, claimed_by, leased_until, "
            "failure_reason, created_at FROM incident_run WHERE id = %s",
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
            "SELECT id, incident_id, state, claimed_by, leased_until, "
            "failure_reason, created_at FROM incident_run "
            "WHERE incident_id = %s ORDER BY created_at DESC LIMIT 1",
            (incident_id,)
        )

        return cursor.fetchone()


def _settle(conn: psycopg.Connection,
            run_id: str,
            state: RunState,
            failure_reason: str | None) -> None:
    """How a run stops, either way.

    The lease is released with it: a settled run is nobody's, and leaving a
    worker's name on it would make a finished run look like one being walked by
    somebody who never let go.
    """
    with conn.cursor() as cursor:
        cursor.execute(
            "UPDATE incident_run SET state = %s, failure_reason = %s, "
            "claimed_by = NULL, leased_until = NULL WHERE id = %s",
            (state, failure_reason, run_id)
        )
    conn.commit()
