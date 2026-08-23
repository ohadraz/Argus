from __future__ import annotations

from typing import Any, Protocol

from agent_codefix import propose_fix
from agent_communicator import notify
from agent_investigator import investigate as _investigate
from agent_mitigation import mitigate
from agent_postmortem import write_postmortem
from argus_core.config import get_settings
from argus_core.db import connect
from argus_core.models.actor import Actor
from argus_core.models.alert import Alert
from argus_core.models.hypothesis import Hypothesis
from argus_core.models.incident_state import IncidentState
from argus_core.models.incident_status import IncidentStatus
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from orchestrator.repository import actions, hypotheses, incidents, postmortems


class Investigate(Protocol):
    def __call__(self, alert: Alert, incident_id: str) -> Hypothesis: ...


class RecordHypothesis(Protocol):
    def __call__(self, hypothesis: Hypothesis) -> None: ...


class TransitionIncident(Protocol):
    def __call__(
        self,
        incident_id: str,
        to_status: IncidentStatus,
        actor: Actor,
        action: str,
        result: str | None = None,
        confidence: float | None = None,
    ) -> None: ...


def _record_hypothesis(hypothesis: Hypothesis) -> None:
    with connect() as conn:
        hypotheses.record(conn, hypothesis)


def _transition_incident(
    incident_id: str,
    to_status: IncidentStatus,
    actor: Actor,
    action: str,
    result: str | None = None,
    confidence: float | None = None,
) -> None:
    with connect() as conn:
        incidents.transition(
            conn, incident_id, to_status, actor=actor, action=action,
            result=result, confidence=confidence,
        )


def tier_gate_node(state: IncidentState) -> dict[str, Any]:
    """No-op pass-through - exists in the graph's shape, enforces nothing
    yet (spec §13, stubbed per design.md Non-Goals)."""
    return {}


def investigator_node(
    state: IncidentState,
    investigate: Investigate = _investigate,
    record_hypothesis: RecordHypothesis = _record_hypothesis,
    transition_incident: TransitionIncident = _transition_incident,
) -> dict[str, Any]:
    """Forms a hypothesis, decides mitigate-vs-escalate by confidence, and
    persists both the hypothesis and the resulting status transition
    (spec §7.2, §10). `investigate`/`record_hypothesis`/`transition_incident`
    default to the real investigation call and repository writes,
    injectable so this node's routing/persistence logic can be unit
    tested without a live Target Service or database - mirroring the seam
    `agent_investigator.investigate()`'s own `fetch_logs` parameter already
    established."""
    hypothesis = investigate(alert=state.alert, incident_id=state.incident_id)
    mitigate_threshold = get_settings().mitigate_threshold
    next_status: IncidentStatus = (
        IncidentStatus.MITIGATING
        if hypothesis.is_confident_enough(mitigate_threshold)
        else IncidentStatus.ESCALATED
    )
    record_hypothesis(hypothesis)
    transition_incident(
        state.incident_id,
        next_status,
        actor=Actor.INVESTIGATOR,
        action="hypothesis formed",
        result=hypothesis.summary,
        confidence=hypothesis.confidence,
    )
    return {
        "hypothesis": hypothesis,
        "confidence": hypothesis.confidence,
        "status": next_status,
    }


def route_after_investigation(state: IncidentState) -> str:
    return "mitigating" if state.status == IncidentStatus.MITIGATING else "escalated"


def mitigation_node(state: IncidentState) -> dict[str, Any]:
    # The stub takes text. A real Mitigation agent needs the whole hypothesis -
    # `cause_type` is what tells it which flag to revert (§7.3) - so this
    # narrowing goes away with the stub.
    outcome = mitigate(state.hypothesis.summary if state.hypothesis else "")
    if outcome == "confirmed":
        next_status: IncidentStatus = IncidentStatus.RESOLVED
    elif outcome == "refuted":
        next_status = IncidentStatus.FIXING
    else:
        next_status = IncidentStatus.ESCALATED
    with connect() as conn:
        actions.record(
            conn, state.incident_id, action_type="reversible-mitigation", outcome=outcome
        )
        incidents.transition(
            conn,
            state.incident_id,
            next_status,
            actor=Actor.MITIGATION,
            action="mitigation attempted",
            result=outcome,
        )
    return {"action_outcome": outcome, "status": next_status}


def route_after_mitigation(state: IncidentState) -> str:
    if state.status == IncidentStatus.RESOLVED:
        return "resolved"
    if state.status == IncidentStatus.FIXING:
        return "fixing"
    return "escalated"


def codefix_node(state: IncidentState) -> dict[str, Any]:
    """Real node so the graph's shape matches spec §10's full FSM
    (design.md Non-Goals) - not reached by this change's happy path."""
    propose_fix(state.hypothesis.summary if state.hypothesis else "")
    return {}


def route_after_codefix(state: IncidentState) -> str:
    return "resolved" if state.status == IncidentStatus.RESOLVED else "escalated"


def communicator_node(state: IncidentState) -> dict[str, Any]:
    """Real node so the graph's shape matches spec §10's full FSM
    (design.md Non-Goals) - not reached by this change's happy path."""
    notify(state.incident_id, "escalating")
    return {}


def postmortem_node(state: IncidentState) -> dict[str, Any]:
    content = write_postmortem(state.incident_id)
    with connect() as conn:
        postmortems.record(conn, state.incident_id, content)
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
