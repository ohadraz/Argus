from __future__ import annotations

from typing import Any, Protocol

from agent_codefix import propose_fix
from agent_communicator import notify
from agent_investigator import investigate as _investigate
from agent_mitigation import Action, Outcome, Verdict, propose_action, take_action
from agent_mitigation.tools import fetch_recent_flag_changes
from agent_postmortem import write_postmortem
from argus_core.config import get_settings
from argus_core.db import connect
from argus_core.models.actor import Actor
from argus_core.models.alert import Alert
from argus_core.models.flag_change import FlagChange
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


class FetchFlagChanges(Protocol):
    def __call__(self) -> list[FlagChange]: ...


class TakeAction(Protocol):
    def __call__(self, action: Action) -> Outcome: ...


class RecordAction(Protocol):
    def __call__(
        self,
        incident_id: str,
        action_type: str,
        outcome: str,
        undo_descriptor: dict[str, Any],
    ) -> None: ...


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


def _record_action(
    incident_id: str, action_type: str, outcome: str, undo_descriptor: dict[str, Any]
) -> None:
    with connect() as conn:
        actions.record(
            conn,
            incident_id,
            action_type=action_type,
            outcome=outcome,
            undo_descriptor=undo_descriptor,
        )


def mitigation_proposal_node(
    state: IncidentState,
    fetch_flag_changes: FetchFlagChanges = fetch_recent_flag_changes,
) -> dict[str, Any]:
    """Chooses the reversible action that answers the hypothesis, and stops
    there (spec §7.3).

    Nothing here changes anything: it reads what the provider recorded as
    having changed and asks Mitigation which action follows, deterministically
    and without a model. Separating this from the node that acts is what leaves
    somewhere for the gate to stand - a gate the acting code could skip is not
    a gate.

    A provider that cannot be read proposes nothing rather than raising. "I
    could not find out what changed" and "nothing changed" lead to the same
    place - no action, and a human - and neither is a reason to fail the graph.
    """
    if state.hypothesis is None:
        return {"proposed_action": None}

    try:
        flag_changes = fetch_flag_changes()
    except Exception:
        return {"proposed_action": None}

    return {"proposed_action": propose_action(state.hypothesis, flag_changes)}


def tier_gate_node(
    state: IncidentState,
    transition_incident: TransitionIncident = _transition_incident,
) -> dict[str, Any]:
    """Refuses to let a reversible action reach its call without a way back
    (spec §13).

    The one check, and the reason it lives here rather than inside the agent
    that performs the write: a guarantee enforced by the code it constrains is
    a convention, not a guarantee. An action with no undo descriptor is not
    reversible however it is labelled, and an incident with no action at all
    has nothing for this stage to admit.

    Rejection escalates, and says so on the timeline. Silently passing an
    ungated action would be the failure this node exists to make impossible;
    silently dropping it would leave an incident that simply stopped.
    """
    reason = _why_the_action_cannot_proceed(state.proposed_action)

    if reason is None:
        return {}

    transition_incident(
        state.incident_id,
        IncidentStatus.ESCALATED,
        actor=Actor.MITIGATION,
        action="action rejected at the tier gate",
        result=reason,
    )

    return {"status": IncidentStatus.ESCALATED}


def _why_the_action_cannot_proceed(action: Action | None) -> str | None:
    """The timeline's account of a rejection, or `None` when there is none to
    give. Two rejections reach the same status for different reasons, and a
    human reading the incident needs to know which: nothing to do at all, or
    something to do that could not be undone."""
    if action is None:
        return "no reversible action was proposed for this cause"

    if not action.undo_descriptor:
        return (
            f"the proposed action [{action.action_type}] on [{action.flag}] "
            f"carries no undo descriptor, so it is not reversible"
        )

    return None


def route_after_gate(state: IncidentState) -> str:
    return "escalated" if state.status == IncidentStatus.ESCALATED else "mitigating"


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
    tested without a live Target Service or database - mirroring the seams
    `agent_investigator.investigate()` establishes for its own retrieval and
    model calls."""
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
        action=_what_the_investigation_did(hypothesis),
        result=hypothesis.summary,
        confidence=hypothesis.confidence,
    )
    return {
        "hypothesis": hypothesis,
        "confidence": hypothesis.confidence,
        "status": next_status,
    }


def _what_the_investigation_did(hypothesis: Hypothesis) -> str:
    """What the timeline records the Investigator as having done (spec §11.2).

    Two escalations reach this line for different reasons, and the timeline is
    where a human finds out which. A named cause below the threshold means a
    hypothesis was formed and is on file to be doubted; no cause at all means
    the loop read everything it was allowed to and still had nothing - the
    next step there is more evidence, not a second opinion on the first.
    """
    return "hypothesis formed" if hypothesis.cause_type is not None else "insufficient evidence"


def route_after_investigation(state: IncidentState) -> str:
    return "mitigating" if state.status == IncidentStatus.MITIGATING else "escalated"


def mitigation_node(
    state: IncidentState,
    take: TakeAction = take_action,
    record_action: RecordAction = _record_action,
    transition_incident: TransitionIncident = _transition_incident,
) -> dict[str, Any]:
    """Performs the action the gate admitted, and records what came of it
    (spec §7.3, §11.1).

    Reached only through the gate, so the action is known to exist and to carry
    a way back. `resolved` follows from a confirmed verdict alone: an incident
    marked resolved while the condition that caused it is still in effect is
    worse than one left open, because nobody looks at it again.

    The row records the descriptor the *write tier returned* rather than the
    one proposed, since that is the account of what actually changed.
    """
    if state.proposed_action is None:
        return _nothing_to_act_on(state, transition_incident)

    result = take(state.proposed_action)
    outcome = str(result.verdict)
    next_status = _status_after(result.verdict)

    record_action(
        state.incident_id,
        action_type=state.proposed_action.action_type,
        outcome=outcome,
        undo_descriptor=result.undo_descriptor,
    )
    transition_incident(
        state.incident_id,
        next_status,
        actor=Actor.MITIGATION,
        action="mitigation attempted",
        result=result.detail,
    )

    return {"action_outcome": outcome, "status": next_status}


def _status_after(verdict: Verdict) -> IncidentStatus:
    if verdict is Verdict.CONFIRMED:
        return IncidentStatus.RESOLVED

    if verdict is Verdict.REFUTED:
        return IncidentStatus.FIXING

    return IncidentStatus.ESCALATED


def _nothing_to_act_on(
    state: IncidentState, transition_incident: TransitionIncident
) -> dict[str, Any]:
    """The unreachable case, handled rather than assumed away.

    The gate escalates an unproposed action, so nothing should arrive here
    without one. A node that indexed into `None` on the day that stopped being
    true would fail inside a state-changing step, which is the worst place to
    discover it.
    """
    outcome = str(Verdict.ESCALATED)
    transition_incident(
        state.incident_id,
        IncidentStatus.ESCALATED,
        actor=Actor.MITIGATION,
        action="mitigation attempted",
        result="no action reached the mitigation step",
    )

    return {"action_outcome": outcome, "status": IncidentStatus.ESCALATED}


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
    graph.add_node("investigator", investigator_node)
    graph.add_node("mitigation_proposal", mitigation_proposal_node)
    graph.add_node("tier_gate", tier_gate_node)
    graph.add_node("mitigation", mitigation_node)
    graph.add_node("codefix", codefix_node)
    graph.add_node("communicator", communicator_node)
    graph.add_node("postmortem", postmortem_node)

    graph.add_edge(START, "investigator")
    graph.add_conditional_edges(
        "investigator",
        route_after_investigation,
        {"mitigating": "mitigation_proposal", "escalated": "communicator"},
    )
    # The gate stands between the proposal and the call that performs it
    # (spec §13) - not at the start of the graph, where it would guard nothing
    # because no action exists yet to be judged.
    graph.add_edge("mitigation_proposal", "tier_gate")
    graph.add_conditional_edges(
        "tier_gate",
        route_after_gate,
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
