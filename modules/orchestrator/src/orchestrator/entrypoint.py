from __future__ import annotations

from argus_core.config import get_settings
from argus_core.db import connect
from argus_core.models.alert import Alert
from argus_core.models.incident_state import IncidentState
from argus_core.models.incident_status import IncidentStatus
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph.state import CompiledStateGraph

from orchestrator.graph import build_graph, recursion_limit
from orchestrator.publishing import acknowledge_alert
from orchestrator.repository import incidents

# Lazily built once per process and kept alive for the process lifetime -
# acceptable for this walking-skeleton's single-process demo scope; a real
# deployment would manage this via an app lifespan hook instead.
# `_checkpointer_cm` must stay referenced at module level: it owns the
# underlying connection, and letting it get garbage-collected closes it out
# from under the compiled graph.
_checkpointer_cm: object | None = None
_compiled_graph: CompiledStateGraph[IncidentState] | None = None


def _get_graph() -> CompiledStateGraph[IncidentState]:
    global _checkpointer_cm, _compiled_graph
    if _compiled_graph is None:
        _checkpointer_cm = PostgresSaver.from_conn_string(get_settings().database_url)
        checkpointer = _checkpointer_cm.__enter__()
        checkpointer.setup()
        _compiled_graph = build_graph(checkpointer)
    return _compiled_graph


def create_incident_and_run(alert: Alert) -> str:
    """The Orchestrator's entrypoint (spec §7.1): creates the `Incident` row
    and invokes the graph, called by `argus_web` (§7.9) with a normalized
    `Alert` domain object - never a vendor's raw payload."""
    with connect() as conn:
        incident_id = incidents.create(conn, alert)

    # The story's first line, published from here because by the time a node
    # runs the alert has already been received - and published after the row
    # exists, so there is an incident for it to belong to.
    acknowledge_alert(incident_id, alert)

    graph = _get_graph()
    settings = get_settings()
    initial_state = IncidentState(
        incident_id=incident_id, alert=alert, status=IncidentStatus.INVESTIGATING
    )
    graph.invoke(
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

    return incident_id
