"""The one thing standing between a proposed action and the call that performs it."""

from __future__ import annotations

from argus_core.events import ActionRefused, Publisher, nobody, publish
from argus_core.models.action import Action
from argus_core.models.incident_state import IncidentState
from argus_core.models.refusal import Refusal

from orchestrator.walk.deltas import StateDelta
from orchestrator.walk.ports import RecordOutcome
from orchestrator.walk.routes import MITIGATING_ROUTE, NEXT_CANDIDATE_ROUTE

# What the candidate's own row says stopped it, one sentence per reason. The
# row is read beside the other candidates rather than on the timeline, so it
# says what happened to *this* explanation in full - where the published event
# carries the value anything counting refusals reads.
_WHAT_THE_ROW_SAYS = {
    Refusal.NO_REVERSIBLE_ACTION: "no reversible action was proposed for this cause",
    Refusal.NOT_REVERSIBLE: "the proposed action carries no undo descriptor, so it "
                            "is not reversible"
}


def tier_gate_node(
    state: IncidentState,
    record_outcome: RecordOutcome,
    publisher: Publisher = nobody
) -> StateDelta:
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
    refusal is published from here rather than returned as a sentence for
    somebody else to write down: this is the only place that knows a refusal
    happened, and the walk's narration accounts for a node that *moved* the
    incident, which this one does not.

    Silently passing an ungated action would be the failure this node exists to
    make impossible; silently dropping it would leave an incident that simply
    stopped.
    """
    refusal = _why_the_action_cannot_proceed(state.proposed_action)

    if refusal is None:
        return StateDelta()

    # The candidate's own row says it was never put to the question, and why.
    if state.hypothesis is not None:
        record_outcome(state.hypothesis.id,
                       tested=False,
                       result=_WHAT_THE_ROW_SAYS[refusal])

    publish(
        ActionRefused(
            incident_id=state.incident_id,
            hypothesis_id=state.hypothesis.id if state.hypothesis is not None else None,
            refusal=refusal
        ),
        publisher
    )

    return StateDelta(proposed_action=None)


def _why_the_action_cannot_proceed(action: Action | None) -> Refusal | None:
    """Which refusal this is, or `None` when there is none to give.

    Two rejections reach the same status for different reasons, and a human
    reading the incident needs to know which: nothing to do at all, or
    something to do that could not be undone. Answered as the value, so that
    the sentence a reader sees is derived from it in one place rather than
    written here and matched on somewhere else."""
    if action is None:
        return Refusal.NO_REVERSIBLE_ACTION

    if action.undo_descriptor is None:
        return Refusal.NOT_REVERSIBLE

    return None


def route_after_gate(state: IncidentState) -> str:
    """Where the gate sends an incident: on to the action, or on to whatever
    comes after an action that will not be taken.

    A rejected action clears `proposed_action`, which is what distinguishes the
    two - the status is `mitigating` either way, because a rejection at the gate
    is not the end of the incident, only the end of this attempt.
    """
    return MITIGATING_ROUTE if state.proposed_action is not None else NEXT_CANDIDATE_ROUTE
