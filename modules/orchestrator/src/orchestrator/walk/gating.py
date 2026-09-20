"""The one thing standing between a proposed action and the call that performs it."""

from __future__ import annotations

from collections.abc import Sequence

from agent_mitigation import a_mitigation_answers
from argus_core.events import ActionRefused, Publisher, nobody, publish
from argus_core.models import (
    Action,
    Attempt,
    FailureMode,
    Refusal,
    the_identity_of,
)

from orchestrator.walk.deltas import StateDelta
from orchestrator.walk.ports import Admitted, RecordOutcome
from orchestrator.walk.routes import MITIGATING_ROUTE, NEXT_CANDIDATE_ROUTE
from orchestrator.walk.state import IncidentState

# What the candidate's own row says stopped it, one sentence per reason. The
# row is read beside the other candidates rather than on the timeline, so it
# says what happened to *this* explanation in full - where the published event
# carries the value anything counting refusals reads.
_WHAT_THE_ROW_SAYS = {
    Refusal.NO_MITIGATION_PROPOSED: "no mitigation was proposed for this cause",
    Refusal.NOTHING_ANSWERS_THIS_MODE: "no mitigation Argus can take answers "
                                       "this kind of failure",
    Refusal.NOT_A_GENERIC_MITIGATION: "actions of this kind are not among the "
                                      "mitigations Argus may take unasked",
    Refusal.ALREADY_TRIED_ENOUGH: "this has already been tried on this subject "
                                  "as often as the incident allows"
}


def tier_gate_node(
    state: IncidentState,
    record_outcome: RecordOutcome,
    admitted: Admitted,
    attempts_per_subject: int,
    publisher: Publisher = nobody
) -> StateDelta:
    """Refuses to let an action reach its call unless its kind is pre-authorised
    (spec §13).

    The one check, and the reason it lives here rather than inside the agent
    that performs the write: a guarantee enforced by the code it constrains is a
    convention, not a guarantee. What admits an action is membership of the
    closed set of generic mitigations - a kind somebody declared and defended -
    and not any property of the particular action, however it is labelled. An
    incident with no action at all has nothing for this stage to admit.

    A rejection is recorded and the walk moves on, rather than ending the
    incident. The gate is judging *this* action, and the explanations after it
    on the list may be answered by a mitigation that is admitted - stopping here
    would let one unauthorised proposal spend the whole of Argus's autonomy.
    Where nothing follows, the node that decides that says so.

    It moves the incident nowhere - a rejection is the end of this attempt, not
    of the incident, so the status is `mitigating` before and after. The
    refusal is published from here rather than returned as a sentence for
    somebody else to write down: this is the only place that knows a refusal
    happened, and the walk's narration accounts for a node that *moved* the
    incident, which this one does not.

    Admission is not the only question. A mitigation in the set may be applied
    to one subject only so many times within one incident, because the risk a
    repeatable mitigation carries is repetition rather than irreversibility: a
    restart can be taken again and again, each one buying a few minutes, and a
    restart loop is what operators actually guard against - with a limit, not
    with an approval step.

    Silently passing an ungated action would be the failure this node exists to
    make impossible; silently dropping it would leave an incident that simply
    stopped.
    """
    refusal = _why_the_action_cannot_proceed(
        state.proposed_action,
        admitted,
        state.attempts,
        attempts_per_subject,
        state.hypothesis.failure_mode if state.hypothesis is not None else None
    )

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


def _why_the_action_cannot_proceed(action: Action | None,
                                   admitted: Admitted,
                                   attempts: Sequence[Attempt],
                                   attempts_per_subject: int,
                                   failure_mode: FailureMode | None) -> Refusal | None:
    """Which refusal this is, or `None` when there is none to give.

    Four rejections reach the same status for different reasons, and a human
    reading the incident needs to know which: a kind of failure nothing answers,
    nothing to do about a cause that does have an answer, something to do that
    nobody pre-authorised, or something that has already been done to this
    subject as often as it may be. Answered as the value, so that the sentence a
    reader sees is derived from it in one place rather than written here and
    matched on somewhere else.

    The first two are both "no action arrived", and telling them apart is the
    whole reason the mode is read here. Which modes have an answer is asked of
    the policy that holds the mapping rather than looked up locally: a gate
    keeping its own copy of what Argus can do is a second copy to fall out of
    step with the first.

    Admission is asked of the set of declared mitigations rather than read off
    the action. Nothing about an instance can put its kind in or out of that
    set, and an action that could answer for its own admissibility would be one
    that admits itself.

    The cap is asked last, because it is the narrowest question: it presumes an
    action that is admitted in general and asks only whether *this* incident
    has had enough of it.
    """
    if action is None:
        # A mode nobody determined is not a mode nothing answers. There was
        # nothing to look a mitigation up by, which is the investigation coming
        # up short - and telling a reader that this kind of failure has no
        # answer would be saying something about a kind nobody named.
        if failure_mode is not None and not a_mitigation_answers(failure_mode):
            return Refusal.NOTHING_ANSWERS_THIS_MODE

        return Refusal.NO_MITIGATION_PROPOSED

    if not admitted(action):
        return Refusal.NOT_A_GENERIC_MITIGATION

    if _times_already_tried(action, attempts) >= attempts_per_subject:
        return Refusal.ALREADY_TRIED_ENOUGH

    return None


def _times_already_tried(action: Action, attempts: Sequence[Attempt]) -> int:
    """How often this incident has already done this to this subject.

    Both halves matter, which is why the comparison is against an identity
    rather than against two fields. Per subject, because restarting one service
    says nothing about whether another may be restarted - the blast radius of a
    mitigation is the thing it acts on. And per kind, because a flag put back
    and a service restarted are different experiments that happen to share a
    name in the record. Written as two comparisons, either half could be
    dropped by an edit and the cap would go on looking like a cap.
    """
    return sum(1 for attempt in attempts if attempt.identity == the_identity_of(action))


def route_after_gate(state: IncidentState) -> str:
    """Where the gate sends an incident: on to the action, or on to whatever
    comes after an action that will not be taken.

    A rejected action clears `proposed_action`, which is what distinguishes the
    two - the status is `mitigating` either way, because a rejection at the gate
    is not the end of the incident, only the end of this attempt.
    """
    return MITIGATING_ROUTE if state.proposed_action is not None else NEXT_CANDIDATE_ROUTE
