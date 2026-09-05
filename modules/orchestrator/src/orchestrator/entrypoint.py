from __future__ import annotations

from collections.abc import Callable

from argus_core.config import get_settings
from argus_core.db import connect
from argus_core.models.actor import Actor
from argus_core.models.alert import Alert
from argus_core.models.incident_state import IncidentState
from argus_core.models.incident_status import IncidentStatus
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph.state import CompiledStateGraph

from orchestrator.graph import build_graph, recursion_limit
from orchestrator.repository import incidents

"""How an incident is walked. Starting one is `orchestrator.intake`.

The two live apart because importing this builds the graph and everything
under it: a process that can reach here can run an investigation, and the
process receiving alerts must not be able to. Nothing about a run depends on
the connection the alert arrived on, which is what makes an investigation
survive a gateway timeout - and what makes the checkpointer worth having, since
a run nobody is holding can be picked up by whoever comes next.
"""

# Lazily built once per process and kept alive for the process lifetime -
# acceptable for this walking-skeleton's single-process demo scope; a real
# deployment would manage this via an app lifespan hook instead.
# `_checkpointer_cm` must stay referenced at module level: it owns the
# underlying connection, and letting it get garbage-collected closes it out
# from under the compiled graph.
_checkpointer_cm: object | None = None
_compiled_graph: CompiledStateGraph[IncidentState] | None = None

# Where the graph a walk runs on comes from. A parameter rather than a global
# reached through: the thread a resumed run continues on is the whole of what
# makes a resume a resume, and it is not assertable through a module-level
# builder that wants a database, a checkpointer and a model behind it.
type GraphOf = Callable[[], CompiledStateGraph[IncidentState]]


def _get_graph() -> CompiledStateGraph[IncidentState]:
    global _checkpointer_cm, _compiled_graph
    if _compiled_graph is None:
        _checkpointer_cm = PostgresSaver.from_conn_string(get_settings().database_url)
        checkpointer = _checkpointer_cm.__enter__()
        checkpointer.setup()
        _compiled_graph = build_graph(checkpointer)
    return _compiled_graph


def run_incident(incident_id: str, graph_of: GraphOf = _get_graph) -> None:
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
    with connect() as conn:
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
    with connect() as conn:
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
