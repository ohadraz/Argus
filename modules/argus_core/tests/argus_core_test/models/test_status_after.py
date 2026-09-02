from __future__ import annotations

from typing import Any

import pytest
from argus_core.models.alert import Alert
from argus_core.models.cause import CauseType
from argus_core.models.hypothesis import Hypothesis
from argus_core.models.incident_state import IncidentState
from argus_core.models.incident_status import IncidentStatus, status_after

"""Where an incident stands, derived from what has been done to it.

The state machine stated once, as a function. Every node in the graph produces
work - a verdict measured against re-queried metrics, a candidate list, an
attempt that did not help - and the status is a conclusion about that work
rather than a decision any node gets to make. Asked here in isolation, with no
graph, because a rule that can only be exercised by running the whole machine
is a rule nobody checks.
"""

SOME_MAX_ROUNDS = 3


@pytest.mark.unit
def test_an_incident_nothing_has_happened_to_yet_is_being_investigated() -> None:
    assert status_after(_an_incident(), SOME_MAX_ROUNDS) is IncidentStatus.INVESTIGATING


@pytest.mark.unit
def test_a_confirmed_action_resolves_the_incident() -> None:
    # The one route to `resolved`, and it goes through evidence: `confirmed`
    # means the metrics were re-queried after the change and had recovered.
    assert status_after(
        _an_incident(candidates=[_a_candidate()], action_outcome="confirmed"),
        SOME_MAX_ROUNDS,
    ) is IncidentStatus.RESOLVED


@pytest.mark.unit
def test_a_refuted_action_with_a_candidate_left_is_still_mitigating() -> None:
    # A change was made, it did not help, and the next explanation is about to
    # be tried. Same phase of the same incident.
    assert status_after(
        _an_incident(
            candidates=[_a_candidate(), _a_candidate()],
            candidate_index=0,
            action_outcome="refuted",
        ),
        SOME_MAX_ROUNDS,
    ) is IncidentStatus.MITIGATING


@pytest.mark.unit
def test_an_action_that_could_not_be_taken_escalates() -> None:
    # Not a third verdict on the hypothesis: nothing was changed and nothing was
    # measured, so a further experiment would run against a world Argus cannot
    # describe.
    assert status_after(
        _an_incident(candidates=[_a_candidate()], action_outcome="escalated"),
        SOME_MAX_ROUNDS,
    ) is IncidentStatus.ESCALATED


@pytest.mark.unit
def test_an_investigation_that_found_nothing_worth_trying_escalates() -> None:
    # Rounds remain and are deliberately not spent. The ReAct loop widened its
    # window as far as it could within this round, so another one would read the
    # same evidence to reach the same answer - unlike a refuted attempt, which
    # is something a re-read cannot produce.
    a_round_that_found_nothing = _an_incident(
        candidates=[_a_candidate()],
        nothing_worth_trying=True,
        rounds=1,
    )

    assert status_after(a_round_that_found_nothing, SOME_MAX_ROUNDS) is IncidentStatus.ESCALATED


@pytest.mark.unit
def test_a_walk_out_of_candidates_with_rounds_left_investigates_again() -> None:
    # What buys the round is the refutation, not a wider window: Argus changed
    # production and the service did not answer, which the model has not seen.
    a_walk_past_its_last_candidate = _an_incident(
        candidates=[_a_candidate(), _a_candidate()],
        candidate_index=2,
        action_outcome="refuted",
        rounds=1,
    )

    assert status_after(
        a_walk_past_its_last_candidate, SOME_MAX_ROUNDS
    ) is IncidentStatus.INVESTIGATING


@pytest.mark.unit
def test_a_walk_out_of_candidates_and_rounds_looks_for_a_permanent_fix() -> None:
    a_walk_with_nothing_left = _an_incident(
        candidates=[_a_candidate()],
        candidate_index=1,
        action_outcome="refuted",
        rounds=SOME_MAX_ROUNDS,
    )

    assert status_after(a_walk_with_nothing_left, SOME_MAX_ROUNDS) is IncidentStatus.FIXING


@pytest.mark.unit
def test_a_code_fix_that_was_found_resolves_the_incident() -> None:
    assert status_after(
        _an_incident(candidate_index=1, rounds=SOME_MAX_ROUNDS, fix_found=True),
        SOME_MAX_ROUNDS,
    ) is IncidentStatus.RESOLVED


@pytest.mark.unit
def test_a_code_fix_that_was_not_found_escalates() -> None:
    # The last move Argus has. Past it there is a human and nothing else, which
    # is what makes this the only place `escalated` follows `fixing`.
    assert status_after(
        _an_incident(candidate_index=1, rounds=SOME_MAX_ROUNDS, fix_found=False),
        SOME_MAX_ROUNDS,
    ) is IncidentStatus.ESCALATED


@pytest.mark.unit
def test_the_same_state_always_derives_the_same_status() -> None:
    # The property the whole design rests on. A status reached by inference
    # could differ between two readings of one incident, and an incident whose
    # own record cannot be reproduced is not an audit trail.
    some_state = _an_incident(
        candidates=[_a_candidate(), _a_candidate()],
        candidate_index=1,
        action_outcome="refuted",
        rounds=2,
    )

    assert status_after(some_state, SOME_MAX_ROUNDS) is status_after(some_state, SOME_MAX_ROUNDS)


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
        **what_has_happened,
    )


def _a_candidate() -> Hypothesis:
    return Hypothesis(
        incident_id="buki-123",
        summary="the monthly-spend flag was switched on",
        cause_type=CauseType.FEATURE_FLAG_TOGGLE,
        confidence=0.8,
        supporting_evidence=[],
        subject="monthly-spend-feature",
    )
