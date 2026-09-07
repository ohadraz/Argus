from __future__ import annotations

from collections.abc import Callable

from argus_core.config import get_settings
from argus_core.db import Connections
from argus_core.models.actor import Actor
from argus_core.models.alert import Alert
from argus_core.models.incident_state import IncidentState
from argus_core.models.incident_status import IncidentStatus
from argus_incidents.repository import incidents
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph.state import CompiledStateGraph

from orchestrator.graph import build_graph, recursion_limit

"""How an incident is walked. Starting one is `argus_incidents.intake`.

The two live apart because importing this builds the graph and everything
under it: a process that can reach here can run an investigation, and the
process receiving alerts must not be able to. Nothing about a run depends on
the connection the alert arrived on, which is what makes an investigation
survive a gateway timeout - and what makes the checkpointer worth having, since
a run nobody is holding can be picked up by whoever comes next.
"""

# Where the graph a walk runs on comes from. A parameter rather than a global
# reached through: the thread a resumed run continues on is the whole of what
# makes a resume a resume, and it is not assertable through a module-level
# builder that wants a database, a checkpointer and a model behind it.
type GraphOf = Callable[[], CompiledStateGraph[IncidentState]]


def graph_for(connections: Connections) -> GraphOf:
    """The compiled graph, built once for the process that asks and kept.

    Built lazily and held, because compiling it sets up a checkpointer and the
    whole node wiring, and a walk should not pay for that on every run. Held by
    the closure rather than at module level, so two processes - or a suite and
    the application inside it - are two graphs against two sets of connections
    rather than one that whichever ran first got to decide.

    The checkpointer's context manager is kept alongside the graph deliberately:
    it owns the connection the checkpointer writes on, and letting it be
    collected would close that out from under the compiled graph.
    """
    graph: CompiledStateGraph[IncidentState] | None = None
    checkpointer_cm: object | None = None

    def compiled() -> CompiledStateGraph[IncidentState]:
        nonlocal graph, checkpointer_cm

        if graph is None:
            checkpointer_cm = PostgresSaver.from_conn_string(
                get_settings().database_url
            )
            checkpointer = checkpointer_cm.__enter__()
            checkpointer.setup()
            graph = build_graph(checkpointer, connections)

        return graph

    return compiled


def run_incident(incident_id: str,
                 connections: Connections,
                 graph_of: GraphOf) -> None:
    """Walks one incident's graph to whatever end it reaches.

    Called by the worker that claimed the run, never by the alert endpoint.
    The alert is read back from the incident rather than carried alongside the
    run: it is already recorded there, and a second copy travelling with the
    run would be a second version of the same fact to keep in step.

    Invoked on the incident's own id as the thread, so a run taken up after
    its worker stopped resumes against what the checkpointer already holds
    instead of walking the incident a second time.

    `graph_of` is a parameter so that which thread a walk resumes on can be
    asserted without a model, an MCP server or a real checkpointer behind it -
    the one property of this function that a test has any business pinning.
    """
    with connections() as conn:
        incident = incidents.get(conn, incident_id)

    if incident is None:
        raise LookupError(f"no incident [{incident_id}] to run")

    # The first thing a walk does, before any node runs: the incident stops
    # being one nobody is on. Written here rather than by a node, because a
    # node's status is derived from the work it did (`status_after`) and this
    # one is derived from the fact that work has started at all.
    #
    # Idempotent by way of the status it writes: a resumed run re-announces an
    # investigation that is already under way, which is true again each time it
    # is taken up.
    with connections() as conn:
        incidents.transition(
            conn,
            incident_id,
            IncidentStatus.INVESTIGATING,
            actor=Actor.ORCHESTRATOR,
            action="investigation started",
        )

    settings = get_settings()
    initial_state = IncidentState(
        incident_id=incident_id,
        alert=Alert.model_validate(incident.alert_payload),
        status=IncidentStatus.INVESTIGATING,
    )
    graph_of().invoke(
        initial_state,
        config={
            "configurable": {"thread_id": incident_id},
            # The walk is a real cycle in the graph, so the default budget of
            # 25 traversals is one an ordinary incident can exhaust. Derived
            # from the settings that bound the walk, never guessed.
            "recursion_limit": recursion_limit(
                settings.investigation_max_rounds,
                settings.investigation_max_candidates,
            ),
        },
    )
