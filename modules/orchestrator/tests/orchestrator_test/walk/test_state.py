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
from argus_core.models import Alert, CauseType, Hypothesis, IncidentStatus
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
def test_a_confirmed_action_resolves_the_incident() -> None:
    # The one route to `resolved`, and it goes through evidence: `confirmed`
    # means the metrics were re-queried after the change and had recovered.
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
            _the_status_is(IncidentStatus.RESOLVED)
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
def test_a_code_fix_that_was_found_resolves_the_incident() -> None:
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
            _the_status_is(IncidentStatus.RESOLVED)
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
                lambda: IncidentState(  # type: ignore[call-arg]
                    incident_id=some_incident_id,
                    status=IncidentStatus.INVESTIGATING
                )
            )
        ) \
        .then(
            an_error_was_raised(ValidationError)
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
        cause_type=CauseType.FEATURE_FLAG_TOGGLE,
        confidence=0.8,
        supporting_evidence=[],
        subject="monthly-spend-feature"
    )
