"""The worker process: what walks incidents.

How a run is taken, walked and settled is `orchestrator.worker`'s; this opens
what the process holds - its pools, a session to each tier, the store - and
hands the loop the walk and the unwind built over them.
"""

from __future__ import annotations

from functools import partial
from typing import Final

from core import (
    DatabaseSettings,
    Holding,
    ReadMcpEndpoint,
    TelemetrySettings,
    WriteMcpEndpoint,
    get_settings,
    open_pool,
)
from core.schema import require_schema
from incident_record import ended_by_a_person_via
from mitigation import an_undo_over
from orchestrator.entrypoint import CHECKPOINTER_CONNECTIONS, graph_for, run_incident
from orchestrator.unwinding import (
    taken_actions_from,
    undone_recorded_through,
    unwind_incident,
)
from orchestrator.worker import RunSettings, work_forever
from read_mcp_client import read_mcp
from telemetry import start_telemetry
from telemetry.langfuse import LangfuseSettings, to_langfuse
from write_mcp_client import write_mcp

from apps.worker.assembling import IncidentMemorySettings, Vendors, against, the_store_for

# What this process is called in its telemetry, and the directory its runs are
# written under.
_SERVICE: Final = "argus-worker"


def main() -> None:
    """The process itself: a pool, three sessions, then take runs until killed.

    Where everything this process needs is built, and the only place that knows
    a pool exists, that either MCP server has an address, or that the vector
    store does. A `main` rather than bare module-level code, so that importing
    this module starts nothing and opens nothing.

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

    The walk's collaborators are assembled here, once, and handed to the graph,
    which compiles them on the first run: assembling them reaches nothing.
    """
    settings = get_settings()
    vendors = Vendors.read()
    database = DatabaseSettings.of(settings)
    holding = Holding()

    with (
        # First in and last out, so that closing it - which flushes what is
        # still batched - comes after everything that could have reported.
        start_telemetry(TelemetrySettings.of(settings), _SERVICE,
                        also=to_langfuse(LangfuseSettings())),
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

        graph_of = graph_for(
            checkpoints,
            against(connections, read, write, store, holding, settings=settings, vendors=vendors)
        )

        work_forever(
            connections,
            walk=partial(run_incident,
                         connections=connections,
                         graph_of=graph_of,
                         max_rounds=settings.investigation_max_rounds,
                         max_candidates=settings.investigation_max_candidates),
            unwind=partial(unwind_incident,
                           # The same binding the walk uses. A withdrawal puts
                           # back every change an incident made, which is every
                           # kind of change it could have made - so an undo
                           # assembled here from a subset of the walk's
                           # collaborators would fail on whichever kind this
                           # copy had not heard about.
                           undo=an_undo_over(write),
                           taken_actions_of=taken_actions_from(connections),
                           record_undone=undone_recorded_through(connections),
                           # The holding the write client reads, so each
                           # put-back is marked with the action it puts back.
                           acting_for=holding.acting_for),
            ended_by_a_person=ended_by_a_person_via(connections),
            holding=holding,
            settings=RunSettings.of(settings)
        )
