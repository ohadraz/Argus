from __future__ import annotations

from argus_core.config import get_settings
from argus_core.db import connect
from argus_core.models import Alert, IncidentState
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph.state import CompiledStateGraph

from orchestrator import persistence
from orchestrator.graph import build_graph

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
        incident_id = persistence.create_incident(conn, alert)

    graph = _get_graph()
    initial_state = IncidentState(incident_id=incident_id, alert=alert, status="investigating")
    graph.invoke(initial_state, config={"configurable": {"thread_id": incident_id}})

    return incident_id
