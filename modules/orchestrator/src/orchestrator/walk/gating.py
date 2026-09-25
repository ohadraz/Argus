"""The one thing standing between a proposed action and the call that performs it."""

from __future__ import annotations

from collections.abc import Sequence

from agent_mitigation import a_mitigation_answers, is_within_reach
from argus_core.events import ActionRefused, Publisher, nobody, publish
from argus_core.models import (
    Action,
    Attempt,
    FailureMode,
    Refusal,
    ServiceDependency,
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
#
# A subscript rather than a `get`, deliberately: a refusal nobody has written a
# sentence for is a refusal a reader would see as a blank row and take for a
# candidate nothing happened to. What that costs is why it is reached through
# the function below rather than read here - see `what_the_row_says`.
_WHAT_THE_ROW_SAYS = {
    Refusal.NO_MITIGATION_PROPOSED: "no mitigation was proposed for this cause",
    Refusal.NOTHING_ANSWERS_THIS_MODE: "no mitigation Argus can take answers "
                                       "this kind of failure",
    Refusal.NOT_A_GENERIC_MITIGATION: "actions of this kind are not among the "
                                      "mitigations Argus may take unasked",
    Refusal.ALREADY_TRIED_ENOUGH: "this has already been tried on this subject "
                                  "as often as the incident allows",
    Refusal.OUTSIDE_WHAT_ARGUS_MAY_TOUCH: "this is addressed to a service "
                                          "outside the estate Argus may act on"
}


def what_the_row_says(refusal: Refusal) -> str:
    """The sentence a refused candidate's row carries, for one refusal.

    Public, and one line long, because the table it reads is a subscript on the
    walk itself. A refusal with no entry does not degrade to a blank row - it
    raises inside the gate, before anything has been tried and before anything
    has been said, so the incident ends rather than its account being spoiled.
    The narration's twin of this table cost exactly that once, in the milder
    place, and was answered with a test over the whole enum; that test needs
    something taking a `Refusal`, and the node takes a state it derives one
    from.

    So this is the unit, rather than a private name a test reaches past its own
    rules to touch. Deriving the sentence and deciding the refusal are two jobs
    anyway: one is a rendering, the other is the one judgement standing between
    a proposal and production.
    """
    return _WHAT_THE_ROW_SAYS[refusal]


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

    Admission is a question about the kind; where the action is aimed is a
    question about the instance, and the two are asked separately because they
    fail for different reasons. A kind nobody pre-authorised asks somebody to
    widen a declared set; an address outside the estate usually asks somebody to
    correct an entry in the service register. Until a mitigation could be aimed
    at a service the alert never named there was nothing here to ask - the
    subject came from the alert, so it was by construction something Argus was
    already acting on.

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
        state.alert.service,
        state.dependencies,
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
                       result=what_the_row_says(refusal))

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
                                   alerting_service: str,
                                   dependencies: Sequence[ServiceDependency],
                                   attempts: Sequence[Attempt],
                                   attempts_per_subject: int,
                                   failure_mode: FailureMode | None) -> Refusal | None:
    """Which refusal this is, or `None` when there is none to give.

    Five rejections reach the same status for different reasons, and a human
    reading the incident needs to know which: a kind of failure nothing answers,
    nothing to do about a cause that does have an answer, something to do that
    nobody pre-authorised, something aimed at a service Argus may not touch, or
    something that has already been done to this subject as often as it may be.
    Answered as the value, so that the sentence a reader sees is derived from it
    in one place rather than written here and matched on somewhere else.

    The first two are both "no action arrived", and telling them apart is the
    whole reason the mode is read here. Which modes have an answer is asked of
    the policy that holds the mapping rather than looked up locally: a gate
    keeping its own copy of what Argus can do is a second copy to fall out of
    step with the first.

    Admission is asked of the set of declared mitigations rather than read off
    the action. Nothing about an instance can put its kind in or out of that
    set, and an action that could answer for its own admissibility would be one
    that admits itself.

    Where it is aimed is asked after its kind and before the cap, which is the
    order the questions actually narrow in: whether Argus does this sort of
    thing at all, then whether it may do it *there*, then whether it has done it
    there often enough already. Asked before the kind it would report an address
    as the problem with an action nobody pre-authorised anywhere.

    Reach is asked of the agent that holds the rule, the way admissibility and
    the mapping of modes to mitigations are - and unlike those two it is not a
    seam a test replaces, because being out of reach is expressible as data. An
    action addressed elsewhere and a register that does not vouch for it is the
    whole of the case, where a kind nobody pre-authorised cannot be built at all
    now that every action type Argus has is in the declared set.

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

    if not is_within_reach(action, alerting_service, dependencies):
        return Refusal.OUTSIDE_WHAT_ARGUS_MAY_TOUCH

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
