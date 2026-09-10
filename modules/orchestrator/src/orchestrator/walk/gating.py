"""The one thing standing between a proposed action and the call that performs it."""

from __future__ import annotations

from typing import Any

from argus_core.models.action import Action
from argus_core.models.incident_state import IncidentState

from orchestrator.walk.narrating import Narration
from orchestrator.walk.ports import RecordOutcome
from orchestrator.walk.routes import MITIGATING_ROUTE, NEXT_CANDIDATE_ROUTE


def tier_gate_node(
    state: IncidentState,
    record_outcome: RecordOutcome,
) -> dict[str, Any]:
    """Refuses to let a reversible action reach its call without a way back
    (spec §13).

    The one check, and the reason it lives here rather than inside the agent
    that performs the write: a guarantee enforced by the code it constrains is
    a convention, not a guarantee. An action with no undo descriptor is not
    reversible however it is labelled, and an incident with no action at all
    has nothing for this stage to admit.

    A rejection is recorded and the walk moves on, rather than ending the
    incident. The gate is judging *this* action, and the explanations after it
    on the list may be perfectly reversible - stopping here would let one
    unreversible proposal spend the whole of Argus's autonomy. Where nothing
    follows, the node that decides that says so.

    It moves the incident nowhere - a rejection is the end of this attempt, not
    of the incident, so the status is `mitigating` before and after. The
    narration is the whole point of the return: this is the only place that
    knows what was refused and why, and the rejection clears the action on the
    way out.

    Silently passing an ungated action would be the failure this node exists to
    make impossible; silently dropping it would leave an incident that simply
    stopped.
    """
    reason = _why_the_action_cannot_proceed(state.proposed_action)

    if reason is None:
        return {}

    # The candidate's own row says it was never put to the question, and why.
    if state.hypothesis is not None:
        record_outcome(state.hypothesis.id, tested=False, result=reason)

    return {
        "proposed_action": None,
        "narration": Narration(action="action rejected at the tier gate", result=reason),
    }


def _why_the_action_cannot_proceed(action: Action | None) -> str | None:
    """The timeline's account of a rejection, or `None` when there is none to
    give. Two rejections reach the same status for different reasons, and a
    human reading the incident needs to know which: nothing to do at all, or
    something to do that could not be undone."""
    if action is None:
        return "no reversible action was proposed for this cause"

    if action.undo_descriptor is None:
        return (
            f"the proposed action [{action.action_type}] on [{action.flag}] "
            f"carries no undo descriptor, so it is not reversible"
        )

    return None


def route_after_gate(state: IncidentState) -> str:
    """Where the gate sends an incident: on to the action, or on to whatever
    comes after an action that will not be taken.

    A rejected action clears `proposed_action`, which is what distinguishes the
    two - the status is `mitigating` either way, because a rejection at the gate
    is not the end of the incident, only the end of this attempt.
    """
    return MITIGATING_ROUTE if state.proposed_action is not None else NEXT_CANDIDATE_ROUTE
