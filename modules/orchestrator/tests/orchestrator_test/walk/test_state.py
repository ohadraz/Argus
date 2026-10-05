"""The walk's state, and where an incident stands given what has been done to it.

The state machine stated once, as a function. Every node in the graph produces
work - a verdict measured against re-queried metrics, a candidate list, an
attempt that did not help - and the status is a conclusion about that work
rather than a decision any node gets to make. Asked here in isolation, with no
graph, because a rule that can only be exercised by running the whole machine
is a rule nobody checks.

The state's own defaults are asserted here too, for the reason they are asserted
anywhere: `hypothesis` and `confidence` arriving as `None` is what lets a node
tell "not yet" from "nothing to find", and a model that silently required them
would make every node's first read a crash.
"""
from __future__ import annotations

from typing import Any

import pytest
from argus_core.models import (
    DEPLOYMENT_PLATFORM,
    Alert,
    Disproof,
    FailureMode,
    FlagUndo,
    Hypothesis,
    IncidentStatus,
    RevertFeatureFlag,
)
from argus_testkit import Assertion, Scenario, an_error_was_raised, attempting
from orchestrator.walk.state import IncidentState, status_after
from pydantic import ValidationError

SOME_MAX_ROUNDS = 3


@pytest.mark.unit
def test_an_incident_nothing_has_happened_to_yet_is_being_investigated() -> None:
    Scenario() \
        .given(
            an_untouched_incident := _an_incident()
        ) \
        .when(
            lambda: status_after(an_untouched_incident, SOME_MAX_ROUNDS)
        ) \
        .then(
            _the_status_is(IncidentStatus.INVESTIGATING)
        )


@pytest.mark.unit
def test_a_confirmed_action_mitigates_the_incident() -> None:
    # The one route to `mitigated`, and it goes through evidence: `confirmed`
    # means the metrics were re-queried after the change and had recovered.
    #
    # Mitigated rather than resolved, because a reverted flag is a workaround
    # holding a fault off rather than the fault being gone. What would resolve
    # it is the permanent fix being merged, which is nobody here's to do.
    Scenario() \
        .given(
            a_confirmed_attempt := _an_incident(
                candidates=[_a_candidate()], action_outcome="confirmed"
            )
        ) \
        .when(
            lambda: status_after(a_confirmed_attempt, SOME_MAX_ROUNDS)
        ) \
        .then(
            _the_status_is(IncidentStatus.MITIGATED)
        )


@pytest.mark.unit
def test_a_refuted_action_with_a_candidate_left_is_still_mitigating() -> None:
    # A change was made, it did not help, and the next explanation is about to
    # be tried. Same phase of the same incident.
    Scenario() \
        .given(
            a_refutation_with_somewhere_to_go := _an_incident(
                candidates=[_a_candidate(), _a_candidate()],
                candidate_index=0,
                action_outcome="refuted"
            )
        ) \
        .when(
            lambda: status_after(a_refutation_with_somewhere_to_go, SOME_MAX_ROUNDS)
        ) \
        .then(
            _the_status_is(IncidentStatus.MITIGATING)
        )


@pytest.mark.unit
def test_an_action_that_could_not_be_taken_escalates() -> None:
    # Not a third verdict on the hypothesis: nothing was changed and nothing was
    # measured, so a further experiment would run against a world Argus cannot
    # describe.
    Scenario() \
        .given(
            an_attempt_that_never_ran := _an_incident(
                candidates=[_a_candidate()], action_outcome="escalated"
            )
        ) \
        .when(
            lambda: status_after(an_attempt_that_never_ran, SOME_MAX_ROUNDS)
        ) \
        .then(
            _the_status_is(IncidentStatus.ESCALATED)
        )


@pytest.mark.unit
def test_an_investigation_that_found_nothing_worth_trying_escalates() -> None:
    # Rounds remain and are deliberately not spent. The ReAct loop widened its
    # window as far as it could within this round, so another one would read the
    # same evidence to reach the same answer - unlike a refuted attempt, which
    # is something a re-read cannot produce.
    Scenario() \
        .given(
            a_round_that_found_nothing := _an_incident(
                candidates=[_a_candidate()],
                nothing_worth_trying=True,
                rounds=1
            )
        ) \
        .when(
            lambda: status_after(a_round_that_found_nothing, SOME_MAX_ROUNDS)
        ) \
        .then(
            _the_status_is(IncidentStatus.ESCALATED)
        )


@pytest.mark.unit
def test_a_walk_out_of_candidates_with_rounds_left_investigates_again() -> None:
    # What buys the round is the refutation, not a wider window: Argus changed
    # production and the service did not answer, which the model has not seen.
    Scenario() \
        .given(
            a_walk_past_its_last_candidate := _an_incident(
                candidates=[_a_candidate(), _a_candidate()],
                candidate_index=2,
                action_outcome="refuted",
                rounds=1
            )
        ) \
        .when(
            lambda: status_after(a_walk_past_its_last_candidate, SOME_MAX_ROUNDS)
        ) \
        .then(
            _the_status_is(IncidentStatus.INVESTIGATING)
        )


@pytest.mark.unit
def test_a_walk_out_of_candidates_and_rounds_looks_for_a_permanent_fix() -> None:
    Scenario() \
        .given(
            a_walk_with_nothing_left := _an_incident(
                candidates=[_a_candidate()],
                candidate_index=1,
                action_outcome="refuted",
                rounds=SOME_MAX_ROUNDS
            )
        ) \
        .when(
            lambda: status_after(a_walk_with_nothing_left, SOME_MAX_ROUNDS)
        ) \
        .then(
            _the_status_is(IncidentStatus.FIXING)
        )


@pytest.mark.unit
def test_a_walk_out_of_reachable_candidates_escalates_rather_than_investigating() -> None:
    # Another round would re-read the same evidence and arrive at candidates on
    # the same dead platform, so what looks like a walk with rounds left is a walk
    # with nothing left to do. The rounds are there, and they cannot help.
    Scenario() \
        .given(
            a_walk_whose_platform_is_down := _an_incident(
                candidates=[_a_candidate(), _a_candidate()],
                candidate_index=2,
                action_outcome="platform-unreachable",
                unreachable_platforms=[DEPLOYMENT_PLATFORM],
                rounds=1
            )
        ) \
        .when(
            lambda: status_after(a_walk_whose_platform_is_down, SOME_MAX_ROUNDS)
        ) \
        .then(
            _the_status_is(IncidentStatus.ESCALATED)
        )


@pytest.mark.unit
def test_a_walk_with_a_reachable_candidate_left_is_still_mitigating() -> None:
    # The case that decides where this belongs, and the one the obvious
    # implementation gets wrong. At the moment the rollback comes back, the
    # platform is down and nothing is confirmed - both true - and the flag revert
    # is still ahead at a valid index. A branch asked before the walk's own
    # arithmetic returns `escalated` here and ends the incident this whole change
    # exists to mitigate.
    #
    # Which is why the platform turns the past-the-end tail into an escalation
    # rather than standing in front of the index check: a rule that cannot fire
    # while a reachable candidate remains cannot make this mistake.
    Scenario() \
        .given(
            a_walk_with_the_flag_still_ahead := _an_incident(
                candidates=[_a_candidate(), _a_candidate()],
                candidate_index=1,
                action_outcome="platform-unreachable",
                unreachable_platforms=[DEPLOYMENT_PLATFORM],
                rounds=1
            )
        ) \
        .when(
            lambda: status_after(a_walk_with_the_flag_still_ahead, SOME_MAX_ROUNDS)
        ) \
        .then(
            _the_status_is(IncidentStatus.MITIGATING)
        )


@pytest.mark.unit
def test_a_platform_that_went_down_does_not_undo_a_confirmed_mitigation() -> None:
    # The walk reached the flag revert, it worked, and the platform is still down.
    # The incident is mitigated: what an unreachable platform took away is actions
    # nobody needs any more, and a status derived from it here would report the
    # one ending this scenario exists to reach as an escalation.
    Scenario() \
        .given(
            a_walk_the_flag_revert_saved := _an_incident(
                candidates=[_a_candidate(), _a_candidate()],
                candidate_index=2,
                action_outcome="confirmed",
                unreachable_platforms=[DEPLOYMENT_PLATFORM],
                rounds=1
            )
        ) \
        .when(
            lambda: status_after(a_walk_the_flag_revert_saved, SOME_MAX_ROUNDS)
        ) \
        .then(
            _the_status_is(IncidentStatus.MITIGATED)
        )


@pytest.mark.unit
def test_a_code_fix_found_without_a_mitigation_still_escalates() -> None:
    # A fix reached this way is one Argus arrived at having stopped nothing:
    # the symptom is still happening and a draft pull request does not stop it.
    # Calling that resolved said the incident was over while the shop was still
    # failing - the status answers "did the symptom stop", and the proposal is
    # something attached to the incident rather than a state of it.
    Scenario() \
        .given(
            a_fix_that_was_found := _an_incident(
                candidate_index=1, rounds=SOME_MAX_ROUNDS, fix_found=True
            )
        ) \
        .when(
            lambda: status_after(a_fix_that_was_found, SOME_MAX_ROUNDS)
        ) \
        .then(
            _the_status_is(IncidentStatus.ESCALATED)
        )


@pytest.mark.unit
def test_a_code_fix_that_was_not_found_escalates() -> None:
    # The last move Argus has. Past it there is a human and nothing else, which
    # is what makes this the only place `escalated` follows `fixing`.
    Scenario() \
        .given(
            a_fix_that_was_not_found := _an_incident(
                candidate_index=1, rounds=SOME_MAX_ROUNDS, fix_found=False
            )
        ) \
        .when(
            lambda: status_after(a_fix_that_was_not_found, SOME_MAX_ROUNDS)
        ) \
        .then(
            _the_status_is(IncidentStatus.ESCALATED)
        )


@pytest.mark.unit
def test_an_action_nobody_could_confirm_is_recommended_rather_than_escalated() -> None:
    # The same ordering trap `mitigated` has, and the same fix. This walk goes
    # on to Code-Fix - the fault is in the code whether or not anybody takes the
    # action - so `fix_found` is set by the time the status is derived, and
    # asking it first would report the incident escalated and lose the one
    # thing it exists to say.
    #
    # Escalated would also be untrue. Argus did not run out of moves; it had a
    # move, named it, and declined to take it because nothing would have said
    # afterwards whether it worked. A reader of the two needs to know whether to
    # work out what to do or to go and do a named thing.
    Scenario() \
        .given(
            an_incident_carrying_a_recommendation := _an_incident(
                candidate_index=1,
                rounds=SOME_MAX_ROUNDS,
                fix_found=True,
                recommended_action=_some_action()
            )
        ) \
        .when(
            lambda: status_after(an_incident_carrying_a_recommendation, SOME_MAX_ROUNDS)
        ) \
        .then(
            _the_status_is(IncidentStatus.RECOMMENDED)
        )


@pytest.mark.unit
def test_a_mode_nothing_answers_is_looking_for_a_fix_with_its_candidate_still_in_hand() -> None:
    # The gate ended the mitigation phase with the candidate it held, so the
    # index still points at it - and an index that points at a candidate reads
    # as one under test. Nothing is: no mitigation answers this mode, and the
    # walk is on its way to Code-Fix, which is what `fixing` means. Once Code-Fix
    # has answered, the rule above it decides, and the incident escalates with or
    # without a proposal.
    Scenario() \
        .given(
            an_incident_nothing_answers := _an_incident(
                candidates=[_a_candidate()],
                candidate_index=0,
                nothing_answers_the_mode=True
            )
        ) \
        .when(
            lambda: status_after(an_incident_nothing_answers, SOME_MAX_ROUNDS)
        ) \
        .then(
            _the_status_is(IncidentStatus.FIXING)
        )


@pytest.mark.unit
def test_a_mitigated_incident_stays_mitigated_once_a_fix_is_proposed() -> None:
    # The new path: a mitigation worked, and Code-Fix then ran and proposed
    # something. Both facts are set on the state at once, so the order the
    # questions are asked in decides the answer - and asking `fix_found` first
    # would report an incident whose symptom demonstrably stopped as escalated.
    Scenario() \
        .given(
            a_mitigation_that_also_got_a_fix := _an_incident(
                candidates=[_a_candidate()],
                action_outcome="confirmed",
                fix_found=True
            )
        ) \
        .when(
            lambda: status_after(a_mitigation_that_also_got_a_fix, SOME_MAX_ROUNDS)
        ) \
        .then(
            _the_status_is(IncidentStatus.MITIGATED)
        )


@pytest.mark.unit
def test_the_same_state_always_derives_the_same_status() -> None:
    # The property the whole design rests on. A status reached by inference
    # could differ between two readings of one incident, and an incident whose
    # own record cannot be reproduced is not an audit trail.
    Scenario() \
        .given(
            some_state := _an_incident(
                candidates=[_a_candidate(), _a_candidate()],
                candidate_index=1,
                action_outcome="refuted",
                rounds=2
            )
        ) \
        .when(
            lambda: [
                status_after(some_state, SOME_MAX_ROUNDS),
                status_after(some_state, SOME_MAX_ROUNDS)
            ]
        ) \
        .then(
            _every_reading_agreed()
        )


@pytest.mark.unit
def test_an_alarm_the_window_contradicted_is_disproven_rather_than_escalated() -> None:
    # Asked before every other question here, and the ordering is the whole of
    # it. An investigation that disproved the alarm also offered no candidate
    # worth trying - it offered none at all - so `nothing_worth_trying` is set
    # beside the disproof, and the first rule to match decides. Asked in the
    # order the escalation rules already sit in, this would report `escalated`
    # and lose the one thing the ending exists to say.
    #
    # The two are opposite findings, not grades of one. Escalated sends a
    # responder to look at the service; this sends them to look at the rule,
    # because the service was well across every minute that was judged.
    Scenario() \
        .given(
            an_incident_whose_alarm_was_contradicted := _an_incident(
                nothing_worth_trying=True,
                disproof=_a_disproof()
            )
        ) \
        .when(
            lambda: status_after(
                an_incident_whose_alarm_was_contradicted, SOME_MAX_ROUNDS
            )
        ) \
        .then(
            _the_status_is(IncidentStatus.DISPROVEN)
        )


@pytest.mark.unit
def test_an_investigation_that_found_nothing_is_escalated_as_it_always_was() -> None:
    # The other half, asserted beside it because this is the branch every
    # existing incident with nothing to try takes, and the one the rule above
    # could quietly widen. No disproof means the window was never evidence
    # against the alarm - so Argus could not explain the incident rather than
    # having established there was none.
    Scenario() \
        .given(
            an_incident_nothing_was_found_for := _an_incident(
                nothing_worth_trying=True
            )
        ) \
        .when(
            lambda: status_after(an_incident_nothing_was_found_for, SOME_MAX_ROUNDS)
        ) \
        .then(
            _the_status_is(IncidentStatus.ESCALATED)
        )


@pytest.mark.unit
def test_a_state_nothing_has_been_found_for_yet_assumes_nothing() -> None:
    Scenario() \
        .given(
            some_incident_id := "buki-123",
            some_alert := Alert(service="kuki-service", alert_name="HighErrorRate")
        ) \
        .when(
            lambda: IncidentState(
                incident_id=some_incident_id,
                alert=some_alert,
                status=IncidentStatus.INVESTIGATING
            )
        ) \
        .then(
            _nothing_was_assumed_about("hypothesis", "confidence")
        )


@pytest.mark.unit
def test_a_state_with_no_alert_is_refused() -> None:
    # The alert is what the incident is about. A state that could be built
    # without one would let a walk start with nothing to investigate.
    Scenario() \
        .given(
            some_incident_id := "buki-123"
        ) \
        .when(
            attempting(
                lambda: IncidentState.model_validate({
                    "incident_id": some_incident_id,
                    "status": IncidentStatus.INVESTIGATING
                })
            )
        ) \
        .then(
            an_error_was_raised(ValidationError)
        )


def _a_disproof() -> Disproof:
    return Disproof(
        signals_judged=("error_rate", "p95_ms"),
        earliest_minute="2026-10-03T09:00Z",
        latest_minute="2026-10-03T09:29Z",
        minutes_judged=30
    )


def _the_status_is(expected: IncidentStatus) -> Assertion[IncidentStatus]:
    def assertion(reached: IncidentStatus) -> bool:
        if reached is not expected:
            raise AssertionError(f"Expected [{expected}], got [{reached}].")

        return True

    return assertion


def _every_reading_agreed() -> Assertion[list[IncidentStatus]]:
    def assertion(readings: list[IncidentStatus]) -> bool:
        if len(set(readings)) != 1:
            raise AssertionError(f"Expected one status from every reading, got {readings}.")

        return True

    return assertion


def _nothing_was_assumed_about(*fields: str) -> Assertion[IncidentState]:
    """That each named field came back `None` rather than filled in.

    Named rather than checked one at a time, because the claim is about the
    model's posture towards what it has not been told - and a field that
    quietly grew a default would pass a test written about its neighbour.
    """
    def assertion(state: IncidentState) -> bool:
        assumed = {field: getattr(state, field) for field in fields}
        filled = {field: value for field, value in assumed.items() if value is not None}

        if filled:
            raise AssertionError(f"Expected nothing assumed, got {filled}.")

        return True

    return assertion


def _an_incident(**what_has_happened: Any) -> IncidentState:
    dont_care_alert = Alert(service="kuki", alert_name="HighErrorRate")

    return IncidentState(
        incident_id="buki-123",
        alert=dont_care_alert,
        # The status the state arrives carrying is deliberately never read: if
        # the reducer consulted it, it would be deriving a status from a status,
        # and the node that set the previous one would be back in the business
        # this change takes it out of.
        status=IncidentStatus.INVESTIGATING,
        **what_has_happened
    )


def _a_candidate() -> Hypothesis:
    return Hypothesis(
        incident_id="buki-123",
        summary="the monthly-spend flag was switched on",
        failure_mode=FailureMode.FEATURE_FLAG_TOGGLE,
        confidence=0.8,
        supporting_evidence=[],
        subject="monthly-spend-feature"
    )


def _some_action() -> RevertFeatureFlag:
    """An action of whatever kind, since what matters here is that one exists.

    The status turns on there being a recommendation at all, not on what it
    recommends - so this says as little as an `Action` can be built saying.
    """
    return RevertFeatureFlag(
        flag="some-flag",
        enabled=False,
        undo_descriptor=FlagUndo(flag="some-flag", was_enabled=True)
    )
