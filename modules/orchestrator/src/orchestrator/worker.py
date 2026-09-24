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
from collections.abc import Callable, Iterator
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
    WriteMcpEndpoint,
    connect_from_env,
    get_settings,
    open_pool,
)
from argus_core.schema import require_schema
from argus_incidents import IsStillWanted, events_into, wanted_via
from argus_incidents.repository import runs
from read_mcp_client import read_mcp
from write_mcp_client import write_mcp

from orchestrator.entrypoint import graph_for, run_incident
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

# How often the claim is renewed, as a fraction of the lease. A third, so two
# renewals may be missed - a slow query, a process the operating system paused -
# before anything else is entitled to take the run for abandoned.
_RENEWALS_PER_LEASE: Final = 3


@contextmanager
def _the_claim_kept_alive(run_id: str,
                          lease: timedelta,
                          connections: Connections) -> Iterator[None]:
    """Renews this run's claim for as long as the body is running.

    A lease bounds how long a *stopped* worker's run waits before somebody takes
    it back. It is not a budget for the walk, and must not be read as one: the
    investigation is allowed 1,800 seconds and Code-Fix 1,100, either of which
    outlasts the 720 the lease is set to.

    Without this the walk simply lost the run part-way through. `claim` takes
    back a run whose lease has expired and *resumes* it from its checkpoint, so
    one incident was walked twice at once - two agents reading the same evidence,
    each free to act on the world, and every model call billed twice. It was
    found in a recording corpus, where one walk's answers had been stored under
    another walk's name because both were live together.

    On its own connection and in its own thread: the connection this worker
    claims with belongs to the caller, and a psycopg connection is not two
    threads' to share.

    A renewal that fails stops the renewing and nothing else. The walk is what
    matters; a database that cannot be reached will fail the run's settling in a
    moment anyway, and this thread taking a live investigation down with it would
    be the more expensive of the two.
    """
    stop = threading.Event()
    every = lease.total_seconds() / _RENEWALS_PER_LEASE

    def keep_renewing() -> None:
        while not stop.wait(every):
            try:
                with connections() as renewing_conn:
                    runs.renew(renewing_conn, run_id, lease)
            except Exception:
                logger.exception("the claim on run %s could not be renewed", run_id)
                return

    renewing = threading.Thread(
        target=keep_renewing, name=f"renew-{run_id}", daemon=True
    )
    renewing.start()

    try:
        yield
    finally:
        stop.set()
        renewing.join(timeout=every)


def take_one_run(conn: psycopg.Connection,
                 claimed_by: str,
                 lease: timedelta,
                 walk: Walk,
                 unwind: Unwind,
                 still_wanted: IsStillWanted,
                 connections: Connections = connect_from_env) -> bool:
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

    The same question is asked either side of the walk, and three cases fall
    out of the two. An incident withdrawn before anybody claimed it is never
    walked - `run_incident`'s first act is to mark it `investigating`, which
    would take an incident a human had ended and put it back on the board. One
    withdrawn partway through is walked, stops at its next node boundary, and is
    unwound on the way out. One nobody stopped is walked and leaves the world as
    the walk left it.

    Unwinding here rather than inside the walk because it is not part of
    investigating anything: it is what the process does with an incident that
    ended without finishing, and it has to happen for a run that was never
    walked at all.
    """
    claimed = runs.claim(conn, claimed_by, lease)

    if claimed is None:
        return False

    try:
        with _the_claim_kept_alive(claimed.id, lease, connections):
            if still_wanted(claimed.incident_id):
                walk(claimed.incident_id)

            if not still_wanted(claimed.incident_id):
                unwind(claimed.incident_id)
    except Exception as failure:
        logger.exception("run %s for incident %s failed",
                         claimed.id, claimed.incident_id)
        _put_back_what_it_changed(unwind, claimed.incident_id)
        runs.fail(conn, claimed.id, f"{type(failure).__name__}: {failure}")
    else:
        runs.finish(conn, claimed.id)

    return True


def _put_back_what_it_changed(unwind: Unwind, incident_id: str) -> None:
    """Unwinds an incident whose run failed, and survives failing to.

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
    """
    try:
        unwind(incident_id)
    except Exception:
        logger.exception(
            "putting back the changes of incident %s after a failed run also failed",
            incident_id
        )


def work_forever(connections: Connections,
                 walk: Walk,
                 unwind: Unwind,
                 still_wanted: IsStillWanted) -> None:
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

    logger.info("worker %s waiting for runs", me)

    with connections() as conn:
        while True:
            if not take_one_run(conn, me, lease, walk, unwind, still_wanted,
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
    logging.basicConfig(level=logging.INFO)

    settings = get_settings()
    mitigation = MitigationSettings.of(settings)

    with (
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
            still_wanted=wanted_via(connections),
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
