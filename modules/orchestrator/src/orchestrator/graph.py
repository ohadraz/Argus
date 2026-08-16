from __future__ import annotations

from typing import Any

from agent_codefix import propose_fix
from agent_communicator import notify
from agent_investigator import investigate
from agent_mitigation import mitigate
from agent_postmortem import write_postmortem
from argus_core.db import connect
from argus_core.models import IncidentState, IncidentStatus
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from orchestrator import persistence

MITIGATE_THRESHOLD = 0.75


def tier_gate_node(state: IncidentState) -> dict[str, Any]:
    """No-op pass-through - exists in the graph's shape, enforces nothing
    yet (spec §13, stubbed per design.md Non-Goals)."""
    return {}


def investigator_node(state: IncidentState) -> dict[str, Any]:
    hypothesis, confidence = investigate(state.alert)
    next_status: IncidentStatus = "mitigating" if confidence >= MITIGATE_THRESHOLD else "escalated"
    with connect() as conn:
        persistence.record_hypothesis(conn, state.incident_id, hypothesis, confidence)
        persistence.transition(
            conn,
            state.incident_id,
            next_status,
            actor="investigator",
            action="hypothesis formed",
            result=hypothesis,
            confidence=confidence,
        )
    return {"hypothesis": hypothesis, "confidence": confidence, "status": next_status}


def route_after_investigation(state: IncidentState) -> str:
    return "mitigating" if state.status == "mitigating" else "escalated"


def mitigation_node(state: IncidentState) -> dict[str, Any]:
    outcome = mitigate(state.hypothesis or "")
    if outcome == "confirmed":
        next_status: IncidentStatus = "resolved"
    elif outcome == "refuted":
        next_status = "fixing"
    else:
        next_status = "escalated"
    with connect() as conn:
        persistence.record_action(
            conn, state.incident_id, action_type="reversible-mitigation", outcome=outcome
        )
        persistence.transition(
            conn,
            state.incident_id,
            next_status,
            actor="mitigation",
            action="mitigation attempted",
            result=outcome,
        )
    return {"action_outcome": outcome, "status": next_status}


def route_after_mitigation(state: IncidentState) -> str:
    if state.status == "resolved":
        return "resolved"
    if state.status == "fixing":
        return "fixing"
    return "escalated"


def codefix_node(state: IncidentState) -> dict[str, Any]:
    """Real node so the graph's shape matches spec §10's full FSM
    (design.md Non-Goals) - not reached by this change's happy path."""
    propose_fix(state.hypothesis or "")
    return {}


def route_after_codefix(state: IncidentState) -> str:
    return "resolved" if state.status == "resolved" else "escalated"


def communicator_node(state: IncidentState) -> dict[str, Any]:
    """Real node so the graph's shape matches spec §10's full FSM
    (design.md Non-Goals) - not reached by this change's happy path."""
    notify(state.incident_id, "escalating")
    return {}


def postmortem_node(state: IncidentState) -> dict[str, Any]:
    content = write_postmortem(state.incident_id)
    with connect() as conn:
        persistence.record_postmortem(conn, state.incident_id, content)
    return {}


def build_graph(checkpointer: BaseCheckpointSaver[Any]) -> CompiledStateGraph[IncidentState]:
    """Assembles spec §10's incident FSM as a LangGraph `StateGraph` (§7.1) -
    every sub-agent and the tier-gate node are present, and every edge from
    §10's diagram is wired, even though this change's happy path only
    drives `investigating -> mitigating -> resolved`."""
    graph: StateGraph[IncidentState] = StateGraph(IncidentState)
    graph.add_node("tier_gate", tier_gate_node)
    graph.add_node("investigator", investigator_node)
    graph.add_node("mitigation", mitigation_node)
    graph.add_node("codefix", codefix_node)
    graph.add_node("communicator", communicator_node)
    graph.add_node("postmortem", postmortem_node)

    graph.add_edge(START, "tier_gate")
    graph.add_edge("tier_gate", "investigator")
    graph.add_conditional_edges(
        "investigator",
        route_after_investigation,
        {"mitigating": "mitigation", "escalated": "communicator"},
    )
    graph.add_conditional_edges(
        "mitigation",
        route_after_mitigation,
        {"resolved": "postmortem", "fixing": "codefix", "escalated": "communicator"},
    )
    graph.add_conditional_edges(
        "codefix",
        route_after_codefix,
        {"resolved": "postmortem", "escalated": "communicator"},
    )
    graph.add_edge("communicator", "postmortem")
    graph.add_edge("postmortem", END)

    return graph.compile(checkpointer=checkpointer)
