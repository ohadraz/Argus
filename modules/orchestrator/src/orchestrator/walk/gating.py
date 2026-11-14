"""The one thing standing between a proposed action and the call that performs it."""

from __future__ import annotations

import logging
from collections.abc import Sequence

from agent_mitigation import is_within_reach, why_nothing_was_proposed
from argus_core.events import (
    ActionRecommended,
    ActionRefused,
    Publisher,
    nobody,
    publish,
)
from argus_core.models import (
    Action,
    Attempt,
    Circumstances,
    Hypothesis,
    Refusal,
    ServiceDependency,
    reports_what_it_changed,
    the_identity_of,
    the_subject_of,
    why_it_was_refused,
)

from orchestrator.walk.candidates import the_circumstances
from orchestrator.walk.deltas import Narration, StateDelta
from orchestrator.walk.ports import Admitted, RecordOutcome
from orchestrator.walk.routes import (
    FIXING_ROUTE,
    MITIGATING_ROUTE,
    NEXT_CANDIDATE_ROUTE,
)
from orchestrator.walk.state import IncidentState

logger = logging.getLogger(__name__)

# The refusals that are the diagnosis saying Argus takes nothing for this kind
# of failure, for one reason or the other. Both end the mitigation phase the
# same way; what differs is the sentence, and a reader's next call.
_THE_MODE_HAS_NO_MITIGATION = frozenset({
    Refusal.SOMEBODY_ELSES_SERVICE,
    Refusal.WOULD_UNDO_A_MEANT_CHANGE
})


def tier_gate_node(
    state: IncidentState,
    record_outcome: RecordOutcome,
    admitted: Admitted,
    attempts_per_subject: int,
    publisher: Publisher = nobody
) -> StateDelta:
    """Refuses to let an action reach its call unless it is pre-authorised, aimed
    within the estate, inside the cap, and confirmable (spec §13).

    Four questions rather than one, and the reason they live here rather than
    inside the agent that performs the write: a guarantee enforced by the code
    it constrains is a convention, not a guarantee. What admits an action is
    membership of the closed set of generic mitigations - a kind somebody
    declared and defended - and not any property of the particular action,
    however it is labelled. An incident with no action at all has nothing for
    this stage to admit.

    Five of the eight rejections are recorded and the walk moves on, rather than
    ending the incident. The gate is judging *this* action, and the explanations
    after it on the list may be answered by a mitigation that is admitted -
    stopping there would let one unauthorised proposal spend the whole of
    Argus's autonomy. Where nothing follows, the node that decides that says so.

    Three stop instead, because none is a judgement on the action. One rejects
    the possibility of confirming *any* action on this incident, so the next
    candidate would be refused for the same reason and would overwrite the
    recommendation with its own on the way past. The other two are the diagnosis
    saying Argus takes no mitigation for this kind of failure - the fault is in
    another company's service, or the one action that reaches it would undo a
    change somebody meant: the candidate in hand is the likeliest explanation
    still standing, and acting on a less likely one would be acting against it.

    Those five refusals move the incident nowhere - a rejection is the end of
    this attempt, not of the incident, so the status is `mitigating` before and
    after. The three that stop do move it, because none is an attempt that
    failed but an ending: one leaves a recommendation and the other two a mode
    Argus takes nothing for, and the status derives from each. So this node
    narrates in exactly those cases and in no other, a narration for a move that
    did not happen being a line in the account describing nothing.

    The refusal is published from here rather than returned as a sentence for
    somebody else to write down: this is the only place that knows a refusal
    happened.

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
        state.hypothesis,
        # Built as the proposal node built them, so the gate says why nothing
        # was proposed from the record the proposal was made against.
        the_circumstances(state.alert, state.flag_changes, state.deployments,
                          state.placement, deployment_changes=state.deployment_changes,
                          onset=state.onset),
        # The two facts confirmability is read off. Dated by the alert rather
        # than measured from the service's own series, and whether any reading
        # covers the incident's minutes - both properties of the evidence, and
        # neither a judgement about the action.
        state.alert.stated_onset is not None,
        state.readings_cover_the_incident
    )

    if refusal is None:
        return StateDelta()

    proposed = state.proposed_action
    logger.info("action refused", extra={
        "refusal": refusal,
        "action_type": proposed.action_type if proposed is not None else None,
        "subject": the_subject_of(proposed) if proposed is not None else None
    })

    # The candidate's own row says it was never put to the question, and why.
    if state.hypothesis is not None:
        record_outcome(state.hypothesis.id,
                       tested=False,
                       result=why_it_was_refused(refusal))

    somebody_elses = refusal is Refusal.SOMEBODY_ELSES_SERVICE
    publish(
        ActionRefused(
            incident_id=state.incident_id,
            hypothesis_id=state.hypothesis.id if state.hypothesis is not None else None,
            candidate_number=(state.hypothesis.number if state.hypothesis is not None
                              else None),
            refusal=refusal,
            dependency=(_the_entry_blamed(state.hypothesis, state.dependencies)
                        if somebody_elses else None)
        ),
        publisher
    )

    # Kept only for the refusal that nothing could confirm. The others either
    # reject something Argus should not do - and passing one of those on would be
    # telling a person to go and do the thing Argus was stopped from doing - or
    # had no action to pass on.
    recommended = (
        state.proposed_action
        if refusal is Refusal.NOTHING_COULD_CONFIRM_IT else None
    )

    if recommended is not None:
        # A second event rather than a field on the refusal above, because the
        # two are different findings: that one says something did not happen
        # and why, and this is the only thing anybody can act on.
        publish(
            ActionRecommended(
                incident_id=state.incident_id,
                hypothesis_id=(
                    state.hypothesis.id if state.hypothesis is not None else None
                ),
                candidate_number=(
                    state.hypothesis.number if state.hypothesis is not None else None
                ),
                action_type=recommended.action_type,
                subject=the_identity_of(recommended).subject
            ),
            publisher
        )

    if refusal in _THE_MODE_HAS_NO_MITIGATION:
        # The other refusals that end the mitigation phase, and they move the
        # incident, so they are narrated as the recommendation is.
        return StateDelta(
            proposed_action=None,
            the_mode_has_no_mitigation=True,
            # Whose fault it was, so Code-Fix is not asked to write a change
            # around another company's outage: the refusal's line says whom
            # to ask instead.
            somebody_elses_fault_for=(state.hypothesis.id
                                      if somebody_elses and state.hypothesis is not None
                                      else None),
            narration=Narration(action="no mitigation taken")
        )

    return StateDelta(
        proposed_action=None,
        recommended_action=recommended,
        # Only where there is a recommendation, because only then does this
        # return move the incident. The other five refusals that reach it end an
        # attempt and leave the status where it was, and the walk refuses a move
        # nothing accounts for - which is how this was found, one case after the
        # ending was written.
        #
        # What was done alone, without the reason: the refusal's own line gives
        # it one line above, and said again on the move the account reads the
        # same sentence twice in a row.
        narration=(
            Narration(action="action recommended")
            if recommended is not None else None
        )
    )


def _the_entry_blamed(hypothesis: Hypothesis | None,
                      dependencies: Sequence[ServiceDependency]) -> ServiceDependency | None:
    """The register's entry for the service a candidate blames, where it is
    another company's - or `None` where the register lists no such service.

    By its name or its host, whatever case the model wrote it in: the subject
    is the model's choice, and one draw names "io-pay" where another names
    "api.io-pay.example". An entry the register marks as ours is not this:
    the refusal says the failure is another company's, and naming one of our
    own services beside it would contradict it.
    """
    if hypothesis is None or hypothesis.subject is None:
        return None

    blamed = hypothesis.subject.casefold()

    return next((entry for entry in dependencies
                 if not entry.is_ours
                 and blamed in (entry.name.casefold(), entry.host.casefold())), None)


def _why_the_action_cannot_proceed(action: Action | None,
                                   admitted: Admitted,
                                   alerting_service: str,
                                   dependencies: Sequence[ServiceDependency],
                                   attempts: Sequence[Attempt],
                                   attempts_per_subject: int,
                                   hypothesis: Hypothesis | None,
                                   circumstances: Circumstances | None,
                                   dated_by_the_alert: bool,
                                   readings_cover_the_incident: bool) -> Refusal | None:
    """Which refusal this is, or `None` when there is none to give.

    The rejections reach their statuses for different reasons, and a human
    reading the incident needs to know which: a kind of failure Argus takes
    nothing for and why, a change the candidate named that the record does not
    hold, nothing to do about a cause that does have an answer, something to
    do that nobody pre-authorised, something aimed at a service
    Argus may not touch, or something that has already been done to this subject
    as often as it may be. Answered as the value, so that the sentence a reader
    sees is derived from it in one place rather than written here and matched on
    somewhere else.

    The first three are all "no action arrived", and telling them apart is the
    whole reason the candidate and the record it was proposed against are read
    here. Which is which is asked of the policy that holds the mapping rather
    than worked out locally: a gate keeping its own copy of what Argus can do
    is a second copy to fall out of step with the first.

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

    The cap is asked last of the questions about the action, because it is the
    narrowest: it presumes an action that is admitted in general and asks only
    whether *this* incident has had enough of it.

    Confirmability is asked after all of them, because it is not a question
    about the action at all. The kind may be pre-authorised, the subject Argus's
    to touch, the cap nowhere near, and the action exactly right - and it still
    must not be taken if nothing would say afterwards whether it worked.
    Reporting that ahead of the others would tell somebody their register is
    fine and their declared set is fine about an action that was neither.

    It is known from two facts about the evidence, and it is still one inference
    rather than a policy with a knob. An onset stated by the alert means the
    metrics measured none, which means no series departed - so there is no level
    to watch coming back down. That much has always held. What it does not settle
    on its own is whether the channel can be watched coming back *at all*,
    because a channel returns in two ways: a level falling, or a reading
    existing.

    So the second fact is whether any reading covers the incident's minutes.
    Where they do, the channel is already saying everything it will ever say and
    will say the same thing after the change goes back; the only thing that would
    answer is whatever raised the alert, running again on a schedule Argus does
    not control - days away, or never. Where they do not, the channel is saying
    nothing yet and will say something, and its saying anything is the
    confirmation.

    An action taken with nothing to judge it would be taken, reported and never
    judged, which is worse than one not taken because the incident looks handled.
    An action *refused* where the readings would have returned is the same cost
    the other way round: a change Argus could have made and confirmed within a
    minute, left as a recommendation, on an incident that reads as handled.
    """
    if action is None:
        return why_nothing_was_proposed(hypothesis, circumstances)

    if not admitted(action):
        return Refusal.NOT_A_GENERIC_MITIGATION

    if not is_within_reach(action, alerting_service, dependencies):
        return Refusal.OUTSIDE_WHAT_ARGUS_MAY_TOUCH

    if _times_already_tried(action, attempts) >= attempts_per_subject:
        return Refusal.ALREADY_TRIED_ENOUGH

    # The service's own window is not the only witness. An action whose answer is
    # a statement about the world rather than an acknowledgement of a request has
    # already said what it did, and asking a flat window to agree would be asking
    # the one channel that cannot speak. So the refusal needs all three: the
    # alert dated the incident, the readings already cover it, *and* the action
    # would report nothing of its own.
    #
    # Read off the kind rather than off an answer, because there is no answer yet
    # - this is decided before anything is performed, which is the whole reason
    # it is a property of the kind and declared beside what admits one unasked.
    if (
        dated_by_the_alert
        and readings_cover_the_incident
        and not reports_what_it_changed(action.action_type)
    ):
        return Refusal.NOTHING_COULD_CONFIRM_IT

    return None


def _times_already_tried(action: Action, attempts: Sequence[Attempt]) -> int:
    """How often this incident has already done this to this subject.

    Both halves matter, which is why the comparison is against an identity
    rather than against two fields. Per subject, because restarting one service
    says nothing about whether another may be restarted - the blast radius of a
    mitigation is the thing it acts on. And per kind, because a flag reverted
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

    Unless the refusal was one of the three that end the mitigation phase instead
    of moving on to the next explanation. The other refusals reject a particular
    action and leave the rest of the list worth trying. Nothing could confirm it
    rejects the possibility of confirming any action on this incident, so the
    next candidate would be refused for the same reason and would overwrite the
    recommendation with its own on the way past. The two that say Argus takes
    nothing for the mode are the diagnosis saying no mitigation applies, and the
    next candidate is a less likely reading of the same evidence - in a
    deliberate change the monitoring did not follow, reliably the rollback that
    would undo it.

    Third, and on to Code-Fix rather than out of the graph, for the reason a
    mitigation that *worked* goes there: nobody is going to take an action, so
    the fault is still where it was and still worth a patch. Here it is the
    only thing anybody gets.
    """
    if state.recommended_action is not None or state.the_mode_has_no_mitigation:
        return FIXING_ROUTE

    return MITIGATING_ROUTE if state.proposed_action is not None else NEXT_CANDIDATE_ROUTE
