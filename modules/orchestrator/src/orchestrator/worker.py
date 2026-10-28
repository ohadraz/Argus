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
    Fence,
    Holding,
    ReadMcpEndpoint,
    Settings,
    TelemetrySettings,
    WriteMcpEndpoint,
    connect_from_env,
    fence,
    get_settings,
    open_pool,
    was_lost,
)
from argus_core.events import StatusChanged, publish
from argus_core.llm import ModelUnavailable
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
from pydantic import BaseModel, ConfigDict
from read_mcp_client import read_mcp
from write_mcp_client import write_mcp

from orchestrator.entrypoint import CHECKPOINTER_CONNECTIONS, graph_for, run_incident
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

# How much longer each wait before trying again is than the one before.
_EACH_WAIT_OVER_THE_LAST: Final = 5


class TryingAgain(BaseModel):
    """How a run whose walk could not get an answer from the model for now is
    tried again: `attempts` tries in all, the wait before the second one
    `first_wait`, and each wait after that five times the one before.

    `attempts` counts the first try, so one means never tried again.
    """

    model_config = ConfigDict(frozen=True)

    attempts: int
    first_wait: timedelta

    @classmethod
    def of(cls, settings: Settings) -> TryingAgain:
        return cls(attempts=settings.run_attempts,
                   first_wait=timedelta(seconds=settings.run_first_retry_wait_seconds))

    def wait_after(self, retries: int) -> timedelta:
        """The wait before the next try, once a run has been requeued `retries`
        times before."""
        # Named for its type: an int raised to an int is `Any` to mypy, since a
        # negative power would be a float.
        grown: int = _EACH_WAIT_OVER_THE_LAST ** retries

        return self.first_wait * grown


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
                 tracer: Tracer | None = None,
                 holding: Holding | None = None,
                 trying_again: TryingAgain | None = None) -> bool:
    """Takes one run if there is one, walks it, and says whether it found any.

    Answers `False` for an empty queue rather than blocking on it, so the
    waiting is the caller's to decide - a loop that sleeps, a test that does
    not.

    A walk that raises because the model could not be reached for now is
    requeued to be tried again, as `trying_again` says - the process's own
    settings where nobody said. Nothing about the incident is wrong, and the
    same question a minute later gets an answer: the run is resumed from its
    checkpoint by whichever claim takes it next, so the incident stays where
    the walk had taken it and nothing it changed is put back. Its last try
    fails as any other failure does.

    Any other walk that raises settles the run as failed and does not re-raise:
    one incident Argus could not finish must not stop it working on the next,
    and the failure is recorded where the incident can be read beside it.
    Before the walk reached an ending, the incident is also escalated and
    unwound, because a run that failed there is a run that ended without
    finishing - the same thing a withdrawal makes of one, and the same answer:
    a change it made may be standing for a reason nobody will now finish
    judging, and no later run is coming to tidy up after the one that died.
    After an ending of the walk's own - mitigated, escalated, recommended,
    disproven - neither: the walk failed in what comes after its ending, the
    write-up above all, and escalating a mitigated incident or putting back the
    fix it confirmed would undo what the walk had finished.

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

    And all of it is written for this claim of the run (`argus_core.fencing`):
    the run is what the process is `holding` while it is worked, which fences
    every connection the walk is handed as it is handed out, and this worker's
    own connection is fenced with it until the run is settled. A store that
    refuses a write because the run was taken back meanwhile has said the run
    is lost, wherever it said it, and is answered as `RunLost` is - with
    nothing written after it. `holding` is the process's own where the walk's
    connections are fenced by it, and nobody's otherwise.
    """
    claimed = runs.claim(conn, claimed_by, lease)

    if claimed is None:
        return False

    tried_again_as = trying_again if trying_again is not None else TryingAgain.of(get_settings())

    held = Fence(run_id=claimed.id, epoch=claimed.epoch)
    held_by = holding if holding is not None else Holding()

    # Read on a connection of its own, so that `conn` is the claim's, the
    # fence's and the settling's alone.
    with connections() as reading:
        incident = incidents.get(reading, claimed.incident_id)

    kept = incident.trace_context if incident is not None else NO_TRACE_CONTEXT

    with (
        inside_the_incidents_trace(claimed.incident_id, kept, RUN_SPAN, tracer=tracer) as span,
        _the_run_in_the_baggage(claimed.id),
        held_by.of(held),
        _fenced(conn, held)
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
        except Exception as failure:
            if was_lost(failure):
                _the_run_was_lost()
            elif (isinstance(failure, ModelUnavailable)
                  and claimed.retries + 1 < tried_again_as.attempts):
                _requeue_to_try_again(conn, claimed, failure, tried_again_as)
            else:
                logger.exception("run failed")
                _settle_the_failure(conn, claimed, failure, unwind, ended_by_a_person,
                                    connections)
        else:
            if _settled_as_finished(conn, claimed):
                logger.info("run finished")
            else:
                _the_run_was_lost()

    return True


@contextmanager
def _fenced(conn: psycopg.Connection, held: Fence) -> Generator[None]:
    """`conn` writes for `held` while the run is worked, and for nothing after -
    however the run ended, its being lost included."""
    fence(conn, held)

    try:
        yield
    finally:
        fence(conn, None)


def _requeue_to_try_again(conn: psycopg.Connection,
                          held: runs.Run,
                          failure: Exception,
                          trying_again: TryingAgain) -> None:
    """Requeues a run to be tried again, committed - or, where the run
    was taken back, does nothing and says so."""
    if not runs.try_again_later(conn, held, trying_again.wait_after(held.retries)):
        conn.rollback()
        _the_run_was_lost()
        return

    conn.commit()
    logger.warning("run requeued to try again", extra={"retries": held.retries + 1},
                   exc_info=failure)


def _settle_the_failure(conn: psycopg.Connection,
                        held: runs.Run,
                        failure: Exception,
                        unwind: Unwind,
                        ended_by_a_person: EndedByAPerson,
                        connections: Connections) -> None:
    """Puts back what a failed walk changed and settles its run as failed - or,
    where either finds the run taken back, does neither and says so.

    Puts nothing back where the walk had already ended the incident itself -
    see `take_one_run` - nor where how the incident stands cannot be read.
    Whether it is escalated is not this read's to say: the statement that
    escalates refuses an incident that has ended, so a read that failed leaves
    nothing standing mid-walk.
    """
    if _to_be_put_back(connections, held.incident_id):
        try:
            _put_back_what_it_changed(unwind, ended_by_a_person, held.incident_id)
        except Exception as error:
            if not was_lost(error):
                raise

            _the_run_was_lost()
            return

    if not _settled_as_failed(conn, held, failure):
        _the_run_was_lost()


def _to_be_put_back(connections: Connections, incident_id: str) -> bool:
    """Whether a failed run's changes are still to be put back as far as its
    walk is concerned: not where the walk reached an ending of its own, whose
    fix putting back would undo.

    A person's endings are `_put_back_what_it_changed`'s to answer, and an
    incident with no row is one there is nothing to keep. Read on a connection
    of its own, so that the worker's is the settling's alone. Where it cannot
    be read, nothing is put back: undoing the fix of an incident the walk had
    mitigated is the error this exists to prevent, and a change left in place
    is one a person can put right.
    """
    try:
        with connections() as reading:
            incident = incidents.get(reading, incident_id)
    except Exception:
        logger.exception("how the incident stood could not be read after a failed run, "
                         "so nothing was put back")
        return False

    if (incident is not None and incident.status.is_terminal()
            and not incident.status.is_a_persons_ending()):
        logger.info("incident ended by its walk, leaving it as the walk left it")
        return False

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
    from here would end that walk part-way through. The fence on `conn` is
    what says so, refusing the first write; the run's failure is written only
    for the claim that holds it, as a second guard.
    """
    try:
        with conn.transaction() as settling:
            taken_actions.settle_claims(conn, held.incident_id)
            _the_incident_needs_a_person(conn, held.incident_id, failure)
            settled = runs.fail(conn, held, f"{type(failure).__name__}: {failure}")

            if not settled:
                raise psycopg.Rollback(settling)
    except psycopg.Error as refused:
        if not was_lost(refused):
            raise

        return False

    return settled


def _settled_as_finished(conn: psycopg.Connection, held: runs.Run) -> bool:
    """Settles a run walked to its end, and answers whether this claim still
    held it to settle - in one commit, or in none where it was taken back.

    A run that finished has normally answered every claim it made. The one it
    has not is the run taken back from a dead worker and found withdrawn -
    unwound, never walked, and finished with the dead worker's claim still open.
    """
    try:
        with conn.transaction() as settling:
            taken_actions.settle_claims(conn, held.incident_id)
            settled = runs.finish(conn, held)

            if not settled:
                raise psycopg.Rollback(settling)
    except psycopg.Error as refused:
        if not was_lost(refused):
            raise

        return False

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

    Not over any ending, and not said about one either. A person who withdrew
    or resolved the incident has it in hand, and a walk that reached an ending
    of its own and failed after it - in the write-up - stopped nowhere: a line
    telling everyone watching that a mitigated incident was escalated would
    contradict both. The row refuses the move, and the move goes first for
    that reason: whether there is anything to say is its answer.
    """
    try:
        with conn.transaction():
            narrating = StatusChanged(incident_id=incident_id,
                                      to_status=IncidentStatus.ESCALATED,
                                      detail=f"the walk stopped without finishing: "
                                             f"{type(failure).__name__}: {failure}")
            escalated = incidents.escalate_unless_ended(conn, incident_id, at=narrating.at)

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

    All but a lost run, which is not a failure to put anything back: the run is
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
    except Exception as error:
        if was_lost(error):
            raise

        logger.exception("changes could not be put back after a failed run")


def work_forever(connections: Connections,
                 walk: Walk,
                 unwind: Unwind,
                 ended_by_a_person: EndedByAPerson,
                 holding: Holding) -> None:
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
    trying_again = TryingAgain.of(settings)
    me = this_worker()

    with connections() as conn:
        while True:
            if not take_one_run(conn, me, lease, walk, unwind, ended_by_a_person,
                                connections, holding=holding, trying_again=trying_again):
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
    searching long-term memory, opened here and closed here, or none at all
    where this deployment searches none. What a walk files for memory goes
    through the pool like its other rows; the deliverer fills the store.

    Both pools are fenced by what the process is holding, so every connection
    this process opens writes for the run it is walking or for none - the
    checkpointer's as much as a node's. Nothing here opens one any other way.
    """
    settings = get_settings()
    mitigation = MitigationSettings.of(settings)
    database = DatabaseSettings.of(settings)
    holding = Holding()

    with (
        # First in and last out, so that closing it - which flushes what is
        # still batched - comes after everything that could have reported.
        start_telemetry(TelemetrySettings.of(settings), _SERVICE),
        open_pool(database, holding=holding) as pool,
        open_pool(database, holding=holding, connection=CHECKPOINTER_CONNECTIONS) as checkpoints,
        read_mcp(ReadMcpEndpoint.of(settings)) as read,
        # Only the write tier is told what is held: it makes changes, and a
        # change is made only for the claim that holds its run.
        write_mcp(WriteMcpEndpoint.of(settings), holding=holding) as write,
        the_store_for(IncidentMemorySettings.of(settings)) as store
    ):
        connections = pool.connection

        # Before anything is claimed. A worker that took a run and then found no
        # table to record it in would have marked an incident as being worked on
        # by a process that is about to die.
        with pool.connection() as conn:
            require_schema(conn)

        graph_of = graph_for(connections, checkpoints, read, write, store, holding)

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
            holding=holding
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
