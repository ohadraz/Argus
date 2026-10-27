"""The process that walks incidents.

It does one thing in a loop: take a run, walk it, settle it. Everything that
makes an investigation slow - the model, the retrieval, the wait for a service
to recover - happens here, in a process nobody is holding a connection open to.

A worker takes work rather than being given it, which is what makes a second
one harmless and a restart uneventful: the queue is the only coordination, and
a run whose worker stopped is simply the oldest thing nobody holds a lease on.
"""

from __future__ import annotations

import logging
import socket
import threading
import time
from collections.abc import Callable, Generator
from contextlib import contextmanager
from datetime import timedelta
from functools import partial
from os import getpid
from typing import Final

import psycopg
from agent_mitigation import (
    MitigationSettings,
    an_undo_over,
)
from argus_core import (
    Connections,
    DatabaseSettings,
    ReadMcpEndpoint,
    RunLost,
    TelemetrySettings,
    WriteMcpEndpoint,
    connect_from_env,
    get_settings,
    open_pool,
)
from argus_core.events import StatusChanged, publish
from argus_core.models import IncidentStatus
from argus_core.schema import require_schema
from argus_core.telemetry import ARGUS_RUN_ID
from argus_incidents import (
    EndedByAPerson,
    ended_by_a_person_via,
    events_into,
    events_into_connection,
    inside_the_incidents_trace,
)
from argus_incidents.repository import incidents, runs, taken_actions
from argus_incidents.repository.incidents import NO_TRACE_CONTEXT
from argus_telemetry import start_telemetry
from opentelemetry import baggage, context
from opentelemetry.trace import Tracer
from read_mcp_client import read_mcp
from write_mcp_client import write_mcp

from orchestrator.entrypoint import graph_for, run_incident
from orchestrator.renewing import between_renewals, keep_renewing
from orchestrator.unwinding import taken_actions_from, unwind_incident
from orchestrator.walk.assembling import IncidentMemorySettings, the_store_for

logger = logging.getLogger(__name__)

# How a walk is performed. Injected so that what this module does with a run -
# claim it, renew while it walks, settle it either way - can be tested without
# a graph, a model or an MCP server behind it.
type Walk = Callable[[str], None]

# How an incident that ended without finishing is put back. Injected for the
# same reason `Walk` is: what this module does with a run is assertable without
# a flag provider behind it.
type Unwind = Callable[[str], None]

# What the span one claimed run is worked inside is called.
RUN_SPAN: Final = "run"

# What this process is called in its telemetry, and the directory its runs are
# written under.
_SERVICE: Final = "argus-worker"


@contextmanager
def _the_claim_kept_alive(held: runs.Run,
                          lease: timedelta,
                          connections: Connections) -> Generator[None]:
    """Renews this run's claim for as long as the body is running.

    Without this the walk simply lost the run part-way through. `claim` takes
    back a run whose lease has expired and *resumes* it from its checkpoint, so
    one incident was walked twice at once - two agents reading the same evidence,
    each free to act on the world, and every model call billed twice. It was
    found in a recording corpus, where one walk's answers had been stored under
    another walk's name because both were live together.

    On its own connection and in its own thread: the connection this worker
    claims with belongs to the caller, and a psycopg connection is not two
    threads' to share. How it renews is `keep_renewing`'s.
    """
    stop = threading.Event()
    renewing = threading.Thread(
        target=keep_renewing, args=(held, lease, connections, stop.wait),
        name=f"renew-{held.id}", daemon=True
    )
    renewing.start()

    try:
        yield
    finally:
        stop.set()
        renewing.join(timeout=between_renewals(lease))


def take_one_run(conn: psycopg.Connection,
                 claimed_by: str,
                 lease: timedelta,
                 walk: Walk,
                 unwind: Unwind,
                 ended_by_a_person: EndedByAPerson,
                 connections: Connections = connect_from_env,
                 tracer: Tracer | None = None) -> bool:
    """Takes one run if there is one, walks it, and says whether it found any.

    Answers `False` for an empty queue rather than blocking on it, so the
    waiting is the caller's to decide - a loop that sleeps, a test that does
    not.

    A walk that raises settles the run as failed and does not re-raise: one
    incident Argus could not finish must not stop it working on the next, and
    the failure is recorded where the incident can be read beside it. It is
    also unwound, because a run that failed is a run that ended without
    finishing - the same thing a withdrawal makes of one, and the same answer.
    The moment worth picturing is a rate limit arriving at the Code-Fix node,
    after a mitigation has already been applied: a run that only writes
    "failed" in the queue there leaves production altered, no postmortem
    written and nothing remembered, and no later run is coming to tidy up
    after the one that died.

    The same question is asked either side of the walk: has a person ended
    this incident, and how. An incident withdrawn before anybody claimed it is
    never walked - `run_incident`'s first act is to mark it `investigating`,
    which would take an incident a human had ended and put it back on the
    board. One withdrawn partway through is walked, stops at its next node
    boundary, and is unwound on the way out. One nobody stopped is walked and
    leaves the world as the walk left it.

    A resolution is walked whenever it came, and never unwound. The person who
    reported the incident over is owed the write-up, which only the walk
    writes, and has the world as it is - putting Argus's changes back behind
    them would be Argus second-guessing the one report it does not test. That
    holds for a run that failed too, which is the one place it could slip: a
    failed run is otherwise unwound.

    Unwinding here rather than inside the walk because it is not part of
    investigating anything: it is what the process does with an incident that
    ended without finishing, and it has to happen for a run that was never
    walked at all.

    The whole run - walk, unwind and settling - is one span continuing the
    trace the incident kept from its alert, so an incident is one trace however
    many runs it takes. The run's id is in the baggage beside the incident's,
    for every log line written anywhere inside it. `tracer` defaults to the
    process's own.
    """
    claimed = runs.claim(conn, claimed_by, lease)

    if claimed is None:
        return False

    # Read on a connection of its own rather than on `conn`, which is held for
    # the whole run: a read left uncommitted there is a transaction open across
    # the walk, and the walk can begin with DDL that waits for every open
    # transaction to end.
    with connections() as reading:
        incident = incidents.get(reading, claimed.incident_id)

    kept = incident.trace_context if incident is not None else NO_TRACE_CONTEXT

    with (
        inside_the_incidents_trace(claimed.incident_id, kept, RUN_SPAN, tracer=tracer) as span,
        _the_run_in_the_baggage(claimed.id)
    ):
        span.set_attribute(ARGUS_RUN_ID, claimed.id)
        logger.info("run claimed", extra={"worker": claimed_by})

        try:
            with _the_claim_kept_alive(claimed, lease, connections):
                walked = ended_by_a_person(claimed.incident_id) is not IncidentStatus.WITHDRAWN

                if walked:
                    walk(claimed.incident_id)

                if ended_by_a_person(claimed.incident_id) is IncidentStatus.WITHDRAWN:
                    logger.info("incident withdrawn, unwinding", extra={"walked": walked})
                    unwind(claimed.incident_id)
        except RunLost:
            _the_run_was_lost()
        except Exception as failure:
            logger.exception("run failed")

            try:
                _put_back_what_it_changed(unwind, ended_by_a_person, claimed.incident_id)
            except RunLost:
                _the_run_was_lost()
            else:
                if not _settled_as_failed(conn, claimed, failure):
                    _the_run_was_lost()
        else:
            if _settled_as_finished(conn, claimed):
                logger.info("run finished")
            else:
                _the_run_was_lost()

    return True


def _settled_as_failed(conn: psycopg.Connection,
                       held: runs.Run,
                       failure: Exception) -> bool:
    """Settles a run whose walk failed, and answers whether this claim still
    held it to settle.

    One transaction, committed once: the claims it left open, the incident
    handed to a person, and the run's failure. A failed run is never taken
    again, so a claim it left open would read as an action in flight for good;
    and the three are one moment, so a reader never finds the run failed with
    its incident still mid-walk. The failure is written last, so every write
    before it is made while the run still reads as this claim's.

    Where the run was taken back, none of it is written: the incident is
    another walk's now, and failing it, escalating it or settling its claims
    from here would end that walk part-way through.
    """
    with conn.transaction() as settling:
        taken_actions.settle_claims(conn, held.incident_id)
        _the_incident_needs_a_person(conn, held.incident_id, failure)
        settled = runs.fail(conn, held, f"{type(failure).__name__}: {failure}")

        if not settled:
            raise psycopg.Rollback(settling)

    return settled


def _settled_as_finished(conn: psycopg.Connection, held: runs.Run) -> bool:
    """Settles a run walked to its end, and answers whether this claim still
    held it to settle - in one commit, or in none where it was taken back.

    A run that finished has normally answered every claim it made. The one it
    has not is the run taken back from a dead worker and found withdrawn -
    unwound, never walked, and finished with the dead worker's claim still open.
    """
    with conn.transaction() as settling:
        taken_actions.settle_claims(conn, held.incident_id)
        settled = runs.finish(conn, held)

        if not settled:
            raise psycopg.Rollback(settling)

    return settled


def _the_run_was_lost() -> None:
    """Says once that this run is another claim's now, and that nothing was
    written about it from here."""
    logger.warning("run lost, leaving it to whoever holds it now")


@contextmanager
def _the_run_in_the_baggage(run_id: str) -> Generator[None]:
    """The run's id in the baggage for as long as the run is worked, and gone after."""
    named = context.attach(baggage.set_baggage(ARGUS_RUN_ID, run_id))

    try:
        yield
    finally:
        context.detach(named)


def _the_incident_needs_a_person(conn: psycopg.Connection,
                                 incident_id: str,
                                 failure: Exception) -> None:
    """Moves an incident whose walk stopped to `escalated`, and says why.

    The run being marked failed is a fact about the queue, and nothing reads the
    queue to find out how an incident is going. Without this the incident keeps
    whatever status the walk had set on the way in - `mitigating`, most often,
    since that is where the longest waits are - and a failed run is terminal, so
    nothing re-claims it. That status is then not a phase the incident is passing
    through. It is where the incident stays, reading as work in progress that
    nothing is going to pick up.

    `escalated` because it is what the walk already means by "a person is needed
    and Argus has no move left", and an exception nobody planned for is the
    plainest case of it. The alternative - a status of its own for a walk that
    crashed - would be a sixth thing every reader has to learn in order to
    discover that it means what `escalated` already means.

    In the transaction that settles the run, and inside a block of its own
    within it: the failure is the record that must survive, and a transition
    that could not be written must not take it down - the block is rolled back
    alone, and the run's failure is still written after it. So a failed run
    whose incident could not be moved is possible, and logged. Committing is
    the settling's, which writes this, the claims and the failure as one. The
    transition and the sentence explaining it are one write, for the reason
    `transition` gives: the column says where the incident is, and the event is
    the only thing that says what put it there.

    The exception's type and message are the whole of the detail. A stack trace
    is what the log is for; what a person reading the incident needs is which
    kind of failure it was, because a refused model, a database that went away
    and a bug in a node ask for three different responses.

    Swallows its own failure, and has to: this runs inside the handler for a
    walk that already failed, and a database that will not take the transition
    would otherwise replace a recorded failure with an unrecorded one. The log
    is the fallback, which is where this sat in its entirety before.

    Not over a withdrawal, and not said about one either. A person who withdrew
    the incident has it in hand, so the row refuses the move - and a line
    telling everyone watching that it was escalated would contradict it. The
    transition goes first for that reason: whether there is anything to say is
    its answer.
    """
    try:
        with conn.transaction():
            narrating = StatusChanged(incident_id=incident_id,
                                      to_status=IncidentStatus.ESCALATED,
                                      detail=f"the walk stopped without finishing: "
                                             f"{type(failure).__name__}: {failure}")
            escalated = incidents.transition(conn, incident_id, IncidentStatus.ESCALATED,
                                             at=narrating.at)

            if escalated:
                publish(narrating, events_into_connection(conn))
    except Exception:
        logger.exception("incident could not be marked escalated after its run failed")


def _put_back_what_it_changed(unwind: Unwind,
                              ended_by_a_person: EndedByAPerson,
                              incident_id: str) -> None:
    """Unwinds an incident whose run failed, and survives failing to.

    Unless a person resolved it. The resolution promised to leave every change
    in place, and a write-up that raised after the report is a failed run like
    any other - so this is the one place the promise could be broken. Where the
    ending cannot be read, nothing is put back either: a change left in place
    is one a person can put right, and undoing a resolution's mitigations is
    the error the check exists to prevent.

    Guarded because this runs inside the handler for a failure that has
    already happened. An unwind that raised from there would take the whole
    handler with it: the run would never be marked failed, so the one record
    saying this incident stopped being worked would not exist, and it would
    sit claimed until its lease expired. Two failures in a row must not cost
    more than one.

    Logged rather than swallowed. That putting the changes back also went
    wrong is a second fact about the incident and a worse one - somebody has
    to go and look - but it is not the reason the run failed, and it does not
    belong in the queue in place of it.

    All but `RunLost`, which is not a failure to put anything back: the run is
    another claim's, and the caller's answer to that is to write nothing more.
    """
    try:
        ending = ended_by_a_person(incident_id)
    except Exception:
        logger.exception("whether a person ended the incident could not be read "
                         "after a failed run, so nothing was put back")
        return

    if ending is IncidentStatus.RESOLVED:
        logger.info("incident resolved by a person, leaving its changes in place")
        return

    try:
        unwind(incident_id)
    except RunLost:
        raise
    except Exception:
        logger.exception("changes could not be put back after a failed run")


def work_forever(connections: Connections,
                 walk: Walk,
                 unwind: Unwind,
                 ended_by_a_person: EndedByAPerson) -> None:
    """Takes runs for as long as the process lives.

    Looks again immediately after taking work and waits only when it found
    none: the interval is the delay a queued incident pays before anything
    starts on it, and paying it between two waiting runs would add it to an
    incident that was already in line.

    Holds one connection for the queue and nothing else. What a walk needs, the
    walk was given when it was built - this loop's own connection is only ever
    the claim, the lease and the settling.
    """
    settings = get_settings()
    lease = timedelta(seconds=settings.run_lease_seconds)
    idle_wait = settings.run_poll_interval_seconds
    me = this_worker()

    with connections() as conn:
        while True:
            if not take_one_run(conn, me, lease, walk, unwind, ended_by_a_person,
                                connections):
                time.sleep(idle_wait)


def main() -> None:
    """The process itself: a pool, three sessions, then take runs until killed.

    Where everything this process needs is built, and the only place that knows
    a pool exists, that either MCP server has an address, or that the vector
    store does. A `main` rather than bare module-level code, so that importing
    this module - which the tests do - starts nothing and opens nothing.

    The clients are held for the life of the worker, which is the point of them:
    one session per tier, reused by every retrieval of every incident this
    process walks, rather than a connection and an MCP handshake per tool call.
    Neither dials anything until the first call, so a worker that finds an empty
    queue and is killed never opened a socket.

    The store is held on the same terms, and by the same owner: one client for
    both ends of long-term memory, opened here and closed here, or none at all
    where this deployment remembers nothing.
    """
    settings = get_settings()
    mitigation = MitigationSettings.of(settings)

    with (
        # First in and last out, so that closing it - which flushes what is
        # still batched - comes after everything that could have reported.
        start_telemetry(TelemetrySettings.of(settings), _SERVICE),
        open_pool(DatabaseSettings.of(settings)) as pool,
        read_mcp(ReadMcpEndpoint.of(settings)) as read,
        write_mcp(WriteMcpEndpoint.of(settings)) as write,
        the_store_for(IncidentMemorySettings.of(settings)) as store,
    ):
        connections = pool.connection

        # Before anything is claimed. A worker that took a run and then found no
        # table to record it in would have marked an incident as being worked on
        # by a process that is about to die.
        with pool.connection() as conn:
            require_schema(conn)

        graph_of = graph_for(connections, read, write, store)

        work_forever(
            connections,
            walk=partial(run_incident, connections=connections, graph_of=graph_of),
            unwind=partial(unwind_incident,
                           # The same binding the walk uses. A withdrawal puts
                           # back every change an incident made, which is every
                           # kind of change it could have made - so an undo
                           # assembled here from a subset of the walk's
                           # collaborators would fail on whichever kind this
                           # copy had not heard about.
                           undo=an_undo_over(write, mitigation),
                           taken_actions_of=taken_actions_from(connections),
                           publisher=events_into(connections)),
            ended_by_a_person=ended_by_a_person_via(connections),
        )


def this_worker() -> str:
    """Who a claim is held by, in a form a person reading the table can act on.

    The host and the process, because the question asked of a stuck run is
    always "is that still running, and where" - and a random id answers neither
    half of it.
    """
    return f"{socket.gethostname()}/{getpid()}"


if __name__ == "__main__":
    main()
