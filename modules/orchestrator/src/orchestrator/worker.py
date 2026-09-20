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
import time
from collections.abc import Callable
from datetime import timedelta
from functools import partial
from os import getpid

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


def take_one_run(conn: psycopg.Connection,
                 claimed_by: str,
                 lease: timedelta,
                 walk: Walk,
                 unwind: Unwind,
                 still_wanted: IsStillWanted) -> bool:
    """Takes one run if there is one, walks it, and says whether it found any.

    Answers `False` for an empty queue rather than blocking on it, so the
    waiting is the caller's to decide - a loop that sleeps, a test that does
    not.

    A walk that raises settles the run as failed and does not re-raise: one
    incident Argus could not finish must not stop it working on the next, and
    the failure is recorded where the incident can be read beside it.

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
        if still_wanted(claimed.incident_id):
            walk(claimed.incident_id)

        if not still_wanted(claimed.incident_id):
            unwind(claimed.incident_id)
    except Exception as failure:
        logger.exception("run %s for incident %s failed",
                         claimed.id, claimed.incident_id)
        runs.fail(conn, claimed.id, f"{type(failure).__name__}: {failure}")
    else:
        runs.finish(conn, claimed.id)

    return True


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
            if not take_one_run(conn, me, lease, walk, unwind, still_wanted):
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
