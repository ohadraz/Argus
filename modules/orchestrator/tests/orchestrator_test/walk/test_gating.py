"""The one thing standing between a proposed action and the call that performs it.

A guarantee enforced by the code it constrains is a convention, not a guarantee,
so the check lives here rather than inside the agent that does the write.

What it checks is a fact about the *kind* of action: whether it belongs to the
closed set of generic mitigations somebody declared and defended. Nothing about
a particular action can put its kind in or out of that set, and a kind absent
from it is what §13 refuses to take autonomously - not because it cannot be
undone, but because nobody has pre-authorised it.

Membership is not the only question. A mitigation in the set may be applied to
one subject only so many times within one incident: what a repeatable mitigation
risks is repetition, not irreversibility, and a restart loop is guarded against
with a limit rather than with an approval step.

A rejection is about *this* action, not about the incident. The explanations
after it on the list may be answered by a mitigation Argus may take, so the gate
clears the action, says why, and moves the incident nowhere - whether anything
follows is decided one node further on, in one place.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from argus_core.events import ActionRefused, IncidentEvent
from argus_core.models import (
    RESTART_SERVICE,
    REVERT_FEATURE_FLAG,
    Action,
    ActionIdentity,
    ActionType,
    Alert,
    Attempt,
    FailureMode,
    FlagUndo,
    Hypothesis,
    IncidentStatus,
    Ownership,
    Refusal,
    RestartService,
    RevertFeatureFlag,
    ServiceDependency,
)
from argus_testkit import Assertion, Scenario, all_of
from orchestrator.walk import ports
from orchestrator.walk.deltas import StateDelta
from orchestrator.walk.gating import route_after_gate, tier_gate_node, what_the_row_says
from orchestrator.walk.routes import MITIGATING_ROUTE, NEXT_CANDIDATE_ROUTE
from orchestrator.walk.state import IncidentState

from orchestrator_test.framework.assertions import the_route_is
from orchestrator_test.framework.builders import (
    a_determined_hypothesis,
    a_random_id,
    an_incident_state,
)

DONT_CARE_FLAG = "dont-care-flag"
DONT_CARE_SERVICE = "dont-care-service"
# How many attempts a subject is allowed. Irrelevant to the tests that name it:
# none of those incidents has tried anything yet, so no cap above zero can bind.
DONT_CARE_ATTEMPT_CAP = 1


@pytest.mark.unit
def test_the_gate_lets_an_action_of_a_kind_it_can_put_back_through(
    record_outcome: MagicMock
) -> None:
    Scenario() \
        .given(
            a_gated_incident := _a_mitigating_incident(
                proposing=_a_proposed_action()
            )
        ) \
        .when(lambda: tier_gate_node(a_gated_incident,
                                     record_outcome=record_outcome,
                                     admitted=_a_kind_argus_may_take(),
                                     attempts_per_subject=DONT_CARE_ATTEMPT_CAP)) \
        .then(all_of(_the_gate_changed_nothing(),
                     _no_outcome_was_recorded(record_outcome)))


@pytest.mark.unit
def test_the_gate_rejects_an_action_of_a_kind_argus_may_not_take(
    record_outcome: MagicMock
) -> None:
    # The guarantee cannot rest on the agent that performs the write also
    # policing itself. The action here is perfectly well formed and carries a
    # descriptor - what refuses it is its kind being absent from the set of
    # mitigations somebody declared, which is the last point at which that can
    # still be heard for free.
    published: list[IncidentEvent] = []

    Scenario() \
        .given(
            a_gated_incident := _a_mitigating_incident(
                proposing=_a_proposed_action()
            )
        ) \
        .when(lambda: tier_gate_node(a_gated_incident,
                                     record_outcome=record_outcome,
                                     admitted=_a_kind_argus_may_not_take(),
                                     attempts_per_subject=DONT_CARE_ATTEMPT_CAP,
                                     publisher=published.append)) \
        .then(all_of(_the_action_was_cleared(),
                     _the_incident_was_moved_nowhere(),
                     _nothing_was_narrated(),
                     _the_refusal_was_published(Refusal.NOT_A_GENERIC_MITIGATION,
                                                published)))


@pytest.mark.unit
def test_the_gate_rejects_an_incident_with_no_proposed_action(
    record_outcome: MagicMock
) -> None:
    # The walk reaches the gate whether or not a proposal was made: with no
    # candidate there is nothing to answer, and the refusal is still the only
    # candidate there is nothing to answer, and the refusal is still the only
    # account of why this attempt ended. Admissibility is not what stops this
    # one, so the stand-in admits everything - a refusal here has to come from
    # the absence and nothing else.
    published: list[IncidentEvent] = []

    Scenario() \
        .given(a_gated_incident := _a_mitigating_incident()) \
        .when(lambda: tier_gate_node(a_gated_incident,
                                     record_outcome=record_outcome,
                                     admitted=_a_kind_argus_may_take(),
                                     attempts_per_subject=DONT_CARE_ATTEMPT_CAP,
                                     publisher=published.append)) \
        .then(all_of(_the_action_was_cleared(),
                     _the_incident_was_moved_nowhere(),
                     _nothing_was_narrated(),
                     _the_refusal_was_published(Refusal.NO_MITIGATION_PROPOSED,
                                                published)))


@pytest.mark.unit
def test_a_candidate_the_gate_refused_is_recorded_as_never_having_been_tried(
    record_outcome: MagicMock
) -> None:
    # A refused action is not the candidate being wrong - it is the candidate
    # never having been put to the question, and its row has to say so. The
    # reason is written down here because this is the only place that knows it:
    # the rejection clears the action on the way out.
    Scenario() \
        .given(
            some_candidate := a_determined_hypothesis(a_random_id()),
            a_gated_incident := _a_mitigating_incident(
                proposing=_a_proposed_action(), about=some_candidate
            )
        ) \
        .when(lambda: tier_gate_node(a_gated_incident,
                                     record_outcome=record_outcome,
                                     admitted=_a_kind_argus_may_not_take(),
                                     attempts_per_subject=DONT_CARE_ATTEMPT_CAP)) \
        .then(_the_candidate_was_recorded_as_untried(some_candidate,
                                                     "Argus may take unasked",
                                                     record_outcome))


@pytest.mark.unit
def test_an_admitted_action_is_routed_to_the_node_that_performs_it() -> None:
    Scenario() \
        .given(
            an_admitted_incident := _a_mitigating_incident(
                proposing=_a_proposed_action()
            )
        ) \
        .when(lambda: route_after_gate(an_admitted_incident)) \
        .then(the_route_is(MITIGATING_ROUTE))


@pytest.mark.unit
def test_a_rejected_action_is_handed_to_the_walk() -> None:
    # The gate clears the action it refused rather than marking the incident
    # escalated: the refusal is about this action, and the explanations after
    # it on the list may be answered by one Argus may take. Whether anything
    # the walk's decision, made in one place - so a rejected action reaches no
    # state-changing call, and no premature ending either.
    Scenario() \
        .given(a_rejected_incident := _a_mitigating_incident()) \
        .when(lambda: route_after_gate(a_rejected_incident)) \
        .then(the_route_is(NEXT_CANDIDATE_ROUTE))


@pytest.mark.unit
def test_a_mitigation_already_tried_on_this_subject_as_often_as_allowed_is_refused(
    record_outcome: MagicMock
) -> None:
    # The risk a repeatable mitigation carries is repetition, not
    # irreversibility. A restart loop is what operators actually guard against,
    # and it is guarded with a limit rather than an approval step: nobody is
    # woken to approve the second restart of a service that did not come back.
    published: list[IncidentEvent] = []
    some_leaking_service = "kuki-service"

    Scenario() \
        .given(
            an_incident_that_already_restarted_it := _a_mitigating_incident(
                proposing=_a_proposed_restart(some_leaking_service),
                already_tried=[_an_attempt_to(RESTART_SERVICE, some_leaking_service)]
            )
        ) \
        .when(lambda: tier_gate_node(an_incident_that_already_restarted_it,
                                     record_outcome=record_outcome,
                                     admitted=_a_kind_argus_may_take(),
                                     attempts_per_subject=1,
                                     publisher=published.append)) \
        .then(all_of(_the_action_was_cleared(),
                     _the_incident_was_moved_nowhere(),
                     _nothing_was_narrated(),
                     _the_refusal_was_published(Refusal.ALREADY_TRIED_ENOUGH,
                                                published)))


@pytest.mark.unit
def test_an_allowance_of_two_lets_the_second_attempt_through(
    record_outcome: MagicMock
) -> None:
    # The cap is a number, not a rule against trying twice. A deployment that
    # has decided a second restart is worth the noise says so in its
    # configuration, and the gate reads it rather than holding an opinion.
    some_leaking_service = "kuki-service"

    Scenario() \
        .given(
            an_incident_that_already_restarted_it := _a_mitigating_incident(
                proposing=_a_proposed_restart(some_leaking_service),
                already_tried=[_an_attempt_to(RESTART_SERVICE, some_leaking_service)]
            )
        ) \
        .when(lambda: tier_gate_node(an_incident_that_already_restarted_it,
                                     record_outcome=record_outcome,
                                     admitted=_a_kind_argus_may_take(),
                                     attempts_per_subject=2)) \
        .then(all_of(_the_gate_changed_nothing(),
                     _no_outcome_was_recorded(record_outcome)))


@pytest.mark.unit
def test_restarting_one_service_does_not_spend_another_services_allowance(
    record_outcome: MagicMock
) -> None:
    # The blast radius of a mitigation is the thing it acts on. A cap counted
    # across the incident rather than per subject would let one unlucky service
    # use up what every other service in the incident was owed.
    some_leaking_service = "kuki-service"
    another_service_entirely = "kuki-payments"

    Scenario() \
        .given(
            an_incident_that_restarted_something_else := _a_mitigating_incident(
                proposing=_a_proposed_restart(some_leaking_service),
                already_tried=[_an_attempt_to(RESTART_SERVICE, another_service_entirely)]
            )
        ) \
        .when(lambda: tier_gate_node(an_incident_that_restarted_something_else,
                                     record_outcome=record_outcome,
                                     admitted=_a_kind_argus_may_take(),
                                     attempts_per_subject=1)) \
        .then(all_of(_the_gate_changed_nothing(),
                     _no_outcome_was_recorded(record_outcome)))


@pytest.mark.unit
def test_a_mitigation_of_another_kind_on_the_same_subject_does_not_spend_it(
    record_outcome: MagicMock
) -> None:
    # A flag put back and a service restarted are different experiments that
    # happen to name the same thing. Counted together, a flag that had already
    # been tried would refuse the first restart the incident ever asked for.
    some_leaking_service = "kuki-service"

    Scenario() \
        .given(
            an_incident_that_already_moved_a_flag := _a_mitigating_incident(
                proposing=_a_proposed_restart(some_leaking_service),
                already_tried=[
                    _an_attempt_to(REVERT_FEATURE_FLAG, some_leaking_service)
                ]
            )
        ) \
        .when(lambda: tier_gate_node(an_incident_that_already_moved_a_flag,
                                     record_outcome=record_outcome,
                                     admitted=_a_kind_argus_may_take(),
                                     attempts_per_subject=1)) \
        .then(all_of(_the_gate_changed_nothing(),
                     _no_outcome_was_recorded(record_outcome)))


@pytest.mark.unit
def test_a_candidate_refused_for_having_been_tried_enough_says_so_in_its_row(
    record_outcome: MagicMock
) -> None:
    # Three rejections reach the same status for different reasons, and the
    # row is where a human finds out which. "Nobody authorised this" and "this
    # has been tried already" call for quite different next moves.
    some_leaking_service = "kuki-service"

    Scenario() \
        .given(
            some_candidate := a_determined_hypothesis(a_random_id()),
            an_incident_that_already_restarted_it := _a_mitigating_incident(
                proposing=_a_proposed_restart(some_leaking_service),
                about=some_candidate,
                already_tried=[_an_attempt_to(RESTART_SERVICE, some_leaking_service)]
            )
        ) \
        .when(lambda: tier_gate_node(an_incident_that_already_restarted_it,
                                     record_outcome=record_outcome,
                                     admitted=_a_kind_argus_may_take(),
                                     attempts_per_subject=1)) \
        .then(_the_candidate_was_recorded_as_untried(some_candidate,
                                                     "as often as the incident allows",
                                                     record_outcome))


def _a_mitigating_incident(proposing: Action | None = None,
                           about: Hypothesis | None = None,
                           already_tried: list[Attempt] | None = None,
                           listing: list[ServiceDependency] | None = None
                           ) -> IncidentState:
    some_alert = Alert(service="kuki-service", alert_name="HighErrorRate")
    state = an_incident_state(some_alert, IncidentStatus.MITIGATING)

    return state.model_copy(
        update={
            "hypothesis": about or a_determined_hypothesis(state.incident_id),
            "proposed_action": proposing,
            "attempts": already_tried or [],
            "dependencies": listing or []
        }
    )


def _a_proposed_action() -> Action:
    """A well-formed action, of whatever kind the gate is told this one is.

    One builder rather than the two this file used to carry. What the gate
    admits or refuses is no longer readable off the action - both tests hand it
    the same action and differ only in what the strategy says about its kind.
    """
    return RevertFeatureFlag(
        flag=DONT_CARE_FLAG,
        enabled=False,
        undo_descriptor=FlagUndo(flag=DONT_CARE_FLAG, was_enabled=True)
    )


def _a_proposed_restart(service: str = DONT_CARE_SERVICE) -> Action:
    """The repeatable mitigation, which is what the cap is really about.

    A restart can be taken again and again, each one buying a few minutes, and
    nothing about the action itself says it has been taken before.
    """
    return RestartService(service=service)


def _an_attempt_to(action_type: ActionType, subject: str) -> Attempt:
    """A mitigation this incident already took, and which did not help.

    Only failures reach this list: one that worked ended the incident, and
    there would be no later round to be capped.
    """
    dont_care_moment = "2026-08-20T11:05:00Z"

    return Attempt(
        identity=ActionIdentity(action_type=action_type, subject=subject),
        occurred_at=dont_care_moment
    )


def _a_kind_argus_may_take() -> ports.Admitted:
    def admitted(dont_care_action: Action) -> bool:
        return True

    return admitted


def _a_kind_argus_may_not_take() -> ports.Admitted:
    """An action of a kind nobody has pre-authorised.

    The one shape §13's gate exists for. It cannot be expressed as an action
    any more - every action type Argus has is in the declared set - so it is
    expressed where the truth about it actually lives, which is the set the
    gate is asked about.
    """
    def admitted(dont_care_action: Action) -> bool:
        return False

    return admitted


def _the_gate_changed_nothing() -> Assertion[StateDelta]:
    """An admitted action leaves the state exactly as it arrived. Anything at
    all here would be the gate deciding something, and the gate decides only
    whether to refuse."""
    def assertion(updates: StateDelta) -> bool:
        if updates.model_fields_set:
            raise AssertionError(
                f"Expected the gate to change nothing, it set "
                f"{sorted(updates.model_fields_set)}."
            )

        return True

    return assertion


def _no_outcome_was_recorded(record_outcome: MagicMock) -> Assertion[StateDelta]:
    """The candidate is about to be put to the question, so nothing is known
    about it yet - a row marked with an outcome here would be marked before the
    experiment that produces one."""
    def assertion(dont_care_result: StateDelta) -> bool:
        if record_outcome.call_count != 0:
            raise AssertionError(
                f"Expected no outcome to be recorded, got "
                f"{record_outcome.call_args_list}."
            )

        return True

    return assertion


def _the_action_was_cleared() -> Assertion[StateDelta]:
    def assertion(updates: StateDelta) -> bool:
        if updates.proposed_action is not None:
            raise AssertionError(
                f"Expected the refused action to be cleared, the gate returned "
                f"{updates.proposed_action!r}."
            )

        return True

    return assertion


def _the_incident_was_moved_nowhere() -> Assertion[StateDelta]:
    """A rejection ends this attempt, not the incident: `mitigating` before and
    after, so the gate names no status at all."""
    def assertion(updates: StateDelta) -> bool:
        if "status" in updates.model_fields_set:
            raise AssertionError(
                f"Expected the gate to name no status, it named "
                f"[{updates.status}]."
            )

        return True

    return assertion


def _the_refusal_was_published(expected: Refusal,
                               published: list[IncidentEvent]) -> Assertion[StateDelta]:
    """The gate's own account of what it would not allow.

    Published by this node rather than returned for somebody else to write
    down, the way the proposal publishes the history it rested on: the gate is
    the only place that knows a refusal happened, and a refusal that travelled
    as free text would reach the page as a sentence nobody can count.
    """
    def assertion(dont_care_updates: StateDelta) -> bool:
        refusals = [event for event in published if isinstance(event, ActionRefused)]

        if not refusals:
            raise AssertionError(
                f"Expected the refusal to be published, got "
                f"{[event.kind for event in published]}."
            )

        if refusals[0].refusal is not expected:
            raise AssertionError(
                f"Expected [{expected}] published, got [{refusals[0].refusal}]."
            )

        return True

    return assertion


def _nothing_was_narrated() -> Assertion[StateDelta]:
    """The gate says nothing through the walk's narration.

    Narration is how a node that *moved* the incident accounts for the move,
    and this one moves it nowhere. Returning a sentence here is what used to
    route the refusal into a second, untyped account of the same event.
    """
    def assertion(updates: StateDelta) -> bool:
        if updates.narration is not None:
            raise AssertionError(
                f"Expected the gate to narrate nothing, it said "
                f"[{updates.narration.action}]."
            )

        return True

    return assertion


def _the_candidate_was_recorded_as_untried(candidate: Hypothesis,
                                           reason: str,
                                           record_outcome: MagicMock
                                           ) -> Assertion[StateDelta]:
    def assertion(dont_care_result: StateDelta) -> bool:
        if record_outcome.call_count != 1:
            raise AssertionError(
                f"Expected exactly one outcome to be recorded, got "
                f"{record_outcome.call_count}."
            )

        recorded_about = record_outcome.call_args.args[0]
        if recorded_about != candidate.id:
            raise AssertionError(
                f"Expected the outcome to be about [{candidate.id}], it was "
                f"about [{recorded_about}]."
            )

        recorded = record_outcome.call_args.kwargs
        if recorded["tested"] is not False:
            raise AssertionError(
                "Expected the candidate to be recorded as never having been tried."
            )

        if reason not in recorded["result"]:
            raise AssertionError(
                f"Expected the reason to say [{reason}], it said "
                f"[{recorded['result']}]."
            )

        return True

    return assertion


@pytest.mark.unit
def test_a_mode_nothing_answers_is_refused_in_its_own_words(
    record_outcome: MagicMock
) -> None:
    # Two silences reach this node, and a reader has to be able to tell them
    # apart. This one is a decision: the cause is known, and no mitigation Argus
    # may take reaches it - somebody outside this system has to act. The other
    # is a gap: the mitigation exists and could not identify what to act on.
    published: list[IncidentEvent] = []

    Scenario() \
        .given(
            a_gated_incident := _a_mitigating_incident(
                about=_a_cause_with_no_mitigation()
            )
        ) \
        .when(lambda: tier_gate_node(a_gated_incident,
                                     record_outcome=record_outcome,
                                     admitted=_a_kind_argus_may_take(),
                                     attempts_per_subject=DONT_CARE_ATTEMPT_CAP,
                                     publisher=published.append)) \
        .then(all_of(_the_action_was_cleared(),
                     _the_incident_was_moved_nowhere(),
                     _the_refusal_was_published(Refusal.NOTHING_ANSWERS_THIS_MODE,
                                                published)))


@pytest.mark.unit
def test_a_cause_nobody_could_act_on_is_still_refused_as_unproposed(
    record_outcome: MagicMock
) -> None:
    # The other silence, kept as it was. A flag toggle is answered by a revert,
    # so an incident that reached the gate without one had a mitigation and no
    # subject to point it at - which is the evidence being thin rather than
    # Argus having nothing to offer.
    published: list[IncidentEvent] = []

    Scenario() \
        .given(a_gated_incident := _a_mitigating_incident()) \
        .when(lambda: tier_gate_node(a_gated_incident,
                                     record_outcome=record_outcome,
                                     admitted=_a_kind_argus_may_take(),
                                     attempts_per_subject=DONT_CARE_ATTEMPT_CAP,
                                     publisher=published.append)) \
        .then(_the_refusal_was_published(Refusal.NO_MITIGATION_PROPOSED, published))


@pytest.mark.unit
def test_the_candidate_row_says_nothing_answers_this_kind_of_failure(
    record_outcome: MagicMock
) -> None:
    # The row is read beside the other candidates rather than on the timeline,
    # so it has to say what happened to this explanation in full - and "no
    # mitigation was proposed" would read, wrongly, as an investigation that
    # came up short.
    some_candidate = _a_cause_with_no_mitigation()

    Scenario() \
        .given(
            a_gated_incident := _a_mitigating_incident(about=some_candidate)
        ) \
        .when(lambda: tier_gate_node(a_gated_incident,
                                     record_outcome=record_outcome,
                                     admitted=_a_kind_argus_may_take(),
                                     attempts_per_subject=DONT_CARE_ATTEMPT_CAP)) \
        .then(_the_candidate_was_recorded_as_untried(
            some_candidate,
            "no mitigation Argus can take answers this kind of failure",
            record_outcome))


def _a_cause_with_no_mitigation() -> Hypothesis:
    """A hypothesis naming the one mode nothing in the closed set answers.

    Built from the determined one rather than from scratch, because everything
    else about it is beside the point: what the gate reads is the mode, and a
    second full builder would be a second place for a candidate's shape to
    drift.
    """
    state_id = a_random_id()

    return a_determined_hypothesis(state_id).model_copy(
        update={"failure_mode": FailureMode.UPSTREAM_DEPENDENCY_FAILURE}
    )


@pytest.mark.unit
def test_a_candidate_that_named_no_mode_is_refused_as_unproposed(
    record_outcome: MagicMock
) -> None:
    # A mode nobody determined is not a mode nothing answers. There was nothing
    # to look a mitigation up by, which is the investigation coming up short -
    # and telling a reader that this kind of failure has no answer would be
    # saying something about a kind nobody named.
    published: list[IncidentEvent] = []

    Scenario() \
        .given(
            a_gated_incident := _a_mitigating_incident(about=_a_cause_nobody_named())
        ) \
        .when(lambda: tier_gate_node(a_gated_incident,
                                     record_outcome=record_outcome,
                                     admitted=_a_kind_argus_may_take(),
                                     attempts_per_subject=DONT_CARE_ATTEMPT_CAP,
                                     publisher=published.append)) \
        .then(_the_refusal_was_published(Refusal.NO_MITIGATION_PROPOSED, published))


@pytest.mark.unit
def test_an_action_addressed_outside_the_estate_is_refused(
    record_outcome: MagicMock
) -> None:
    # The second gate, and the first refusal that is about the *instance*
    # rather than the kind. A restart is pre-authorised, and this one names a
    # service the register has nothing to say about - which is where a mistyped
    # name, a third party's, and one a model invented all land together.
    published: list[IncidentEvent] = []

    Scenario() \
        .given(
            an_incident_aimed_elsewhere := _a_mitigating_incident(
                proposing=_a_proposed_restart("io-billing"),
                listing=[_a_dependency_of_ours("io-pricing")]
            )
        ) \
        .when(lambda: tier_gate_node(an_incident_aimed_elsewhere,
                                     record_outcome=record_outcome,
                                     admitted=_a_kind_argus_may_take(),
                                     attempts_per_subject=DONT_CARE_ATTEMPT_CAP,
                                     publisher=published.append)) \
        .then(all_of(_the_action_was_cleared(),
                     _the_incident_was_moved_nowhere(),
                     _nothing_was_narrated(),
                     _the_refusal_was_published(
                         Refusal.OUTSIDE_WHAT_ARGUS_MAY_TOUCH, published)))


@pytest.mark.unit
def test_a_restart_of_a_dependency_the_register_calls_ours_is_let_through(
    record_outcome: MagicMock
) -> None:
    # The whole point of the mode at the gate: a service Argus was never paged
    # about, touched anyway, because the register says the alerting service
    # calls it and the organisation owns it. Without this the second gate would
    # be a refusal with no matching permission.
    Scenario() \
        .given(
            an_incident_blaming_a_dependency := _a_mitigating_incident(
                proposing=_a_proposed_restart("io-pricing"),
                listing=[_a_dependency_of_ours("io-pricing")]
            )
        ) \
        .when(lambda: tier_gate_node(an_incident_blaming_a_dependency,
                                     record_outcome=record_outcome,
                                     admitted=_a_kind_argus_may_take(),
                                     attempts_per_subject=DONT_CARE_ATTEMPT_CAP)) \
        .then(all_of(_the_gate_changed_nothing(),
                     _no_outcome_was_recorded(record_outcome)))


@pytest.mark.unit
def test_a_candidate_refused_for_where_it_was_aimed_says_so_in_its_row(
    record_outcome: MagicMock
) -> None:
    # "Argus does not do that" and "Argus does not touch that" ask different
    # people for different things - one to widen a declared set, the other to
    # correct an entry in the register - and the row is where whoever picks the
    # incident up finds out which was meant.
    Scenario() \
        .given(
            some_candidate := a_determined_hypothesis(a_random_id()),
            an_incident_aimed_elsewhere := _a_mitigating_incident(
                proposing=_a_proposed_restart("io-billing"),
                about=some_candidate
            )
        ) \
        .when(lambda: tier_gate_node(an_incident_aimed_elsewhere,
                                     record_outcome=record_outcome,
                                     admitted=_a_kind_argus_may_take(),
                                     attempts_per_subject=DONT_CARE_ATTEMPT_CAP)) \
        .then(_the_candidate_was_recorded_as_untried(
            some_candidate,
            "outside the estate Argus may act on",
            record_outcome))


@pytest.mark.unit
def test_every_refusal_has_a_sentence_for_the_candidates_row() -> None:
    # The same subscript the narration carried, in a worse place. A refusal
    # with no sentence here does not degrade to a blank row - it raises inside
    # the gate, which is on the walk itself rather than on the page, so a sixth
    # refusal would end the incident instead of spoiling its account.
    #
    # Over the whole enum rather than per member, for the reason the narration's
    # is: what must hold is that no refusal reaches a candidate's row as a value
    # nobody wrote a sentence for, and a test naming the five that exist today
    # would say nothing about the sixth.
    Scenario() \
        .given(every_reason_to_refuse := list(Refusal)) \
        .when(lambda: {
            refusal: _what_the_row_would_say_about(refusal)
            for refusal in every_reason_to_refuse
        }) \
        .then(_every_refusal_was_put_into_words())


def _what_the_row_would_say_about(refusal: Refusal) -> str:
    """The row's sentence for one refusal, or the empty string where there is none.

    Caught rather than allowed to raise, so the assertion below names every
    refusal without a sentence instead of the test ending on the first one.
    """
    try:
        return what_the_row_says(refusal)
    except KeyError:
        return ""


def _every_refusal_was_put_into_words() -> Assertion[dict[Refusal, str]]:
    def assertion(said: dict[Refusal, str]) -> bool:
        wordless = [refusal.value for refusal, sentence in said.items() if not sentence]

        if wordless:
            raise AssertionError(
                f"{sorted(wordless)} have no sentence, so a candidate refused "
                f"for one of those reasons fails the walk at the gate - before "
                f"anything has been tried and before anything has been said."
            )

        return True

    return assertion


def _a_dependency_of_ours(name: str) -> ServiceDependency:
    """One entry the register marks as the organisation's own.

    Only the name and the ownership decide anything here; the rest is what an
    entry happens to carry.
    """
    return ServiceDependency(
        name=name,
        purpose="dont care",
        host=f"{name}.io-internal.svc",
        owner="dont-care-team",
        ownership=Ownership.INTERNAL
    )


def _a_cause_nobody_named() -> Hypothesis:
    """A candidate that reached the gate having determined no mode at all.

    Rare but reachable: the walk escalates an undetermined investigation before
    this node, and a candidate whose mode this version cannot spell arrives
    here looking exactly like one.
    """
    return a_determined_hypothesis(a_random_id()).model_copy(
        update={"failure_mode": None}
    )
