from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from argus_core.ids import new_id
from argus_core.models.actor import Actor
from argus_core.models.alert import Alert
from argus_core.models.cause import CauseType
from argus_core.models.hypothesis import Hypothesis
from argus_core.models.incident import Incident
from argus_core.models.incident_status import IncidentStatus
from argus_core.models.taken_action import TakenAction
from argus_core.models.timeline_event import TimelineEvent
from argus_core.models.undo_descriptor import UndoDescriptor
from argus_testkit import Assertion, Scenario, all_of
from argus_web.views.incidents import (
    Candidate,
    IncidentDetail,
    IncidentSummary,
    build_incident_detail,
    build_incident_summary,
)

"""Shaping an incident's rows into what a reader is shown.

No database here: the rows these take are what the repositories already return,
and every question below is about the arrangement rather than the retrieval -
which attempt belongs to which candidate, what an untried candidate looks like,
and what happens to an attempt that names no candidate at all.

The order everything arrives in is kept rather than re-imposed. Ranking
candidates and sequencing actions are decisions the investigation made, and a
view that sorted them again would be a second opinion about them - so the
assertions read the lists as lists, in the order they came.
"""

_OPENED_AT = datetime(2026, 8, 30, 10, 15, tzinfo=UTC)

NOTHING_WAS_TRIED: list[TakenAction] = []
NOTHING_WAS_FORMED: list[Hypothesis] = []
NOTHING_MOVED: list[TimelineEvent] = []

REFUTED = "refuted"
CONFIRMED = "confirmed"


@pytest.mark.unit
def test_an_attempt_is_shown_against_the_candidate_it_was_taken_for() -> None:
    # Attached to the candidate, because "what did we try for this
    # explanation?" is the question a reader has while looking at one.
    an_incident = _an_incident()
    the_first_candidate = _a_candidate(an_incident.id, subject="first", rank=1)
    the_second_candidate = _a_candidate(an_incident.id, subject="second", rank=2)

    Scenario() \
        .given(
            each_candidate_was_tried_once := [
                _an_attempt(an_incident.id, the_first_candidate.id, outcome=REFUTED),
                _an_attempt(an_incident.id, the_second_candidate.id, outcome=CONFIRMED)
            ]
        ) \
        .when(lambda: build_incident_detail(
            an_incident,
            candidates=[the_first_candidate, the_second_candidate],
            attempts=each_candidate_was_tried_once,
            timeline=NOTHING_MOVED
        )) \
        .then(_the_attempts_shown_per_candidate_are(
            [("first", [REFUTED]), ("second", [CONFIRMED])]
        ))


@pytest.mark.unit
def test_a_candidate_the_walk_never_reached_is_shown_as_untried() -> None:
    # "Never reached" and "tried and refuted" are the difference between a walk
    # that ran out of options and one that stopped because it was right.
    an_incident = _an_incident()

    Scenario() \
        .given(
            a_candidate_never_reached := _a_candidate(
                an_incident.id, subject="never reached", rank=2
            )
        ) \
        .when(lambda: build_incident_detail(
            an_incident,
            candidates=[a_candidate_never_reached],
            attempts=NOTHING_WAS_TRIED,
            timeline=NOTHING_MOVED
        )) \
        .then(all_of(_the_first_candidate_was_tested(False),
                     _the_first_candidate_resulted_in(None),
                     _the_attempts_shown_per_candidate_are([("never reached", [])])))


@pytest.mark.unit
def test_a_refuted_attempt_is_shown_as_having_been_put_back() -> None:
    # A reversible action that did not help is undone before its verdict is
    # returned. A page showing the attempt without that would leave a reader
    # believing the flag is still flipped.
    an_incident = _an_incident()
    the_refuted_candidate = _a_candidate(an_incident.id, subject="refuted", rank=1)
    the_confirmed_candidate = _a_candidate(an_incident.id, subject="confirmed", rank=2)

    Scenario() \
        .given(
            one_of_each_verdict := [
                _an_attempt(an_incident.id, the_refuted_candidate.id, outcome=REFUTED),
                _an_attempt(an_incident.id, the_confirmed_candidate.id, outcome=CONFIRMED)
            ]
        ) \
        .when(lambda: build_incident_detail(
            an_incident,
            candidates=[the_refuted_candidate, the_confirmed_candidate],
            attempts=one_of_each_verdict,
            timeline=NOTHING_MOVED
        )) \
        .then(_the_attempts_were_undone([True, False]))


@pytest.mark.unit
def test_an_attempt_with_no_verdict_yet_is_shown_as_undecided_rather_than_undone() -> None:
    # An action taken a second ago has no answer yet, and calling that "not
    # undone" is right while calling it "refuted" or "confirmed" would not be.
    an_incident = _an_incident()
    a_candidate_being_acted_on = _a_candidate(an_incident.id, subject="in flight", rank=1)

    Scenario() \
        .given(
            an_attempt_the_service_has_not_answered := [
                _an_attempt(an_incident.id, a_candidate_being_acted_on.id, outcome=None)
            ]
        ) \
        .when(lambda: build_incident_detail(
            an_incident,
            candidates=[a_candidate_being_acted_on],
            attempts=an_attempt_the_service_has_not_answered,
            timeline=NOTHING_MOVED
        )) \
        .then(all_of(_the_attempts_shown_per_candidate_are([("in flight", [None])]),
                     _the_attempts_were_undone([False])))


@pytest.mark.unit
def test_an_attempt_naming_no_candidate_is_still_shown() -> None:
    # `action.hypothesis_id` is nullable, so an action can arrive attributed to
    # nothing. Dropping it would delete a change Argus made to the service from
    # the only account of what it did.
    an_incident = _an_incident()
    some_candidate = _a_candidate(an_incident.id, subject="a-flag", rank=1)

    Scenario() \
        .given(
            an_attempt_attributed_to_nothing := [
                _an_attempt(an_incident.id, None, outcome=CONFIRMED)
            ]
        ) \
        .when(lambda: build_incident_detail(
            an_incident,
            candidates=[some_candidate],
            attempts=an_attempt_attributed_to_nothing,
            timeline=NOTHING_MOVED
        )) \
        .then(all_of(_the_attempts_shown_per_candidate_are([("a-flag", [])]),
                     _the_unattributed_attempts_are([CONFIRMED])))


@pytest.mark.unit
def test_a_candidate_carries_the_evidence_it_was_formed_from() -> None:
    # Evidence in a collection of its own makes a reader correlate claims to
    # timestamps, which is the reader investigating the incident again.
    an_incident = _an_incident()
    what_it_was_formed_from = [
        "error rate rose at 10:14", "a-flag was enabled at 10:13"
    ]

    Scenario() \
        .given(
            a_candidate_that_cited_two_things := _a_candidate(
                an_incident.id, subject="a-flag", rank=1, evidence=what_it_was_formed_from
            )
        ) \
        .when(lambda: build_incident_detail(
            an_incident,
            candidates=[a_candidate_that_cited_two_things],
            attempts=NOTHING_WAS_TRIED,
            timeline=NOTHING_MOVED
        )) \
        .then(_the_first_candidate_cites(what_it_was_formed_from))


@pytest.mark.unit
def test_an_incident_is_shown_with_the_alert_it_opened_on() -> None:
    # The row stores the alert as the JSON it was normalized into. A reader
    # gets the alert back, not the payload it was stored as.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate", severity="critical")

    Scenario() \
        .given(an_incident_opened_on_it := _an_incident(alert=some_alert)) \
        .when(lambda: build_incident_summary(an_incident_opened_on_it)) \
        .then(_it_opened_on(some_alert))


@pytest.mark.unit
def test_an_incident_is_shown_with_the_transitions_it_went_through() -> None:
    # The status is where the incident ended. The transitions are how it got
    # there, and they are the only record of an incident that moved twice.
    an_incident = _an_incident()

    Scenario() \
        .given(
            it_moved_twice := [
                _a_transition(
                    an_incident.id, IncidentStatus.INVESTIGATING, "incident created"
                ),
                _a_transition(
                    an_incident.id, IncidentStatus.RESOLVED, "mitigation attempted"
                )
            ]
        ) \
        .when(lambda: build_incident_detail(
            an_incident,
            candidates=NOTHING_WAS_FORMED,
            attempts=NOTHING_WAS_TRIED,
            timeline=it_moved_twice
        )) \
        .then(_the_timeline_reads(
            [IncidentStatus.INVESTIGATING, IncidentStatus.RESOLVED]
        ))


@pytest.mark.unit
def test_an_incident_that_formed_no_candidate_is_shown_as_empty() -> None:
    # An incident that escalated before forming a hypothesis is a real incident
    # with nothing to show, which is not the same as an unknown one.
    Scenario() \
        .given(an_incident_that_explained_nothing := _an_incident()) \
        .when(lambda: build_incident_detail(
            an_incident_that_explained_nothing,
            candidates=NOTHING_WAS_FORMED,
            attempts=NOTHING_WAS_TRIED,
            timeline=NOTHING_MOVED
        )) \
        .then(_the_attempts_shown_per_candidate_are([]))


def _an_incident(alert: Alert | None = None) -> Incident:
    return Incident(
        id=new_id(),
        alert_payload=(alert or Alert(service="io-shop", alert_name="HighErrorRate"))
        .model_dump(mode="json"),
        status=IncidentStatus.INVESTIGATING,
        slack_channel_id=None,
        pr_url=None,
        created_at=_OPENED_AT,
        ended_at=None
    )


def _a_candidate(incident_id: str,
                 subject: str,
                 rank: int,
                 evidence: list[str] | None = None) -> Hypothesis:
    return Hypothesis(
        incident_id=incident_id,
        summary=f"dont care - {subject}",
        cause_type=CauseType.FEATURE_FLAG_TOGGLE,
        confidence=0.9,
        supporting_evidence=evidence or [],
        subject=subject,
        rank=rank
    )


def _an_attempt(incident_id: str,
                hypothesis_id: str | None,
                outcome: str | None) -> TakenAction:
    return TakenAction(
        id=new_id(),
        incident_id=incident_id,
        hypothesis_id=hypothesis_id,
        type="revert-feature-flag",
        target=None,
        reversible=True,
        tier=None,
        undo_descriptor=UndoDescriptor(flag="dont-care", was_enabled=True),
        outcome=outcome,
        taken_at=_OPENED_AT + timedelta(minutes=1),
        approved_by=None
    )


def _a_transition(incident_id: str,
                  to_status: IncidentStatus,
                  action: str) -> TimelineEvent:
    return TimelineEvent(
        id=new_id(),
        incident_id=incident_id,
        to_status=to_status,
        actor=Actor.ORCHESTRATOR,
        action=action,
        result=None,
        confidence=None,
        created_at=_OPENED_AT + timedelta(minutes=1)
    )


def _the_attempts_shown_per_candidate_are(
    expected: list[tuple[str | None, list[str | None]]]
) -> Assertion[IncidentDetail]:
    """Every candidate with what was tried for it, in order, as one value.

    Asserted whole because the arrangement is the subject: a candidate carrying
    somebody else's attempt is as wrong as one carrying none, and a check that
    named only the candidate it expected could not see the first kind.
    """
    def assertion(detail: IncidentDetail) -> bool:
        shown = [
            (candidate.subject, [attempt.outcome for attempt in candidate.attempts])
            for candidate in detail.candidates
        ]

        if shown != expected:
            raise AssertionError(f"expected {expected}, got {shown}")

        return True

    return assertion


def _the_attempts_were_undone(expected: list[bool]) -> Assertion[IncidentDetail]:
    def assertion(detail: IncidentDetail) -> bool:
        undone = [
            attempt.undone
            for candidate in detail.candidates
            for attempt in candidate.attempts
        ]

        if undone != expected:
            raise AssertionError(f"expected {expected} undone, got {undone}")

        return True

    return assertion


def _the_unattributed_attempts_are(expected: list[str | None]) -> Assertion[IncidentDetail]:
    def assertion(detail: IncidentDetail) -> bool:
        shown = [attempt.outcome for attempt in detail.unattributed_attempts]

        if shown != expected:
            raise AssertionError(
                f"expected {expected} attributed to nothing, got {shown}"
            )

        return True

    return assertion


def _the_first_candidate_was_tested(expected: bool) -> Assertion[IncidentDetail]:
    def assertion(detail: IncidentDetail) -> bool:
        tested = _the_first(detail).tested

        if tested is not expected:
            raise AssertionError(f"expected tested [{expected}], got [{tested}]")

        return True

    return assertion


def _the_first_candidate_resulted_in(expected: str | None) -> Assertion[IncidentDetail]:
    def assertion(detail: IncidentDetail) -> bool:
        result = _the_first(detail).result

        if result != expected:
            raise AssertionError(f"expected the result [{expected}], got [{result}]")

        return True

    return assertion


def _the_first_candidate_cites(expected: list[str]) -> Assertion[IncidentDetail]:
    def assertion(detail: IncidentDetail) -> bool:
        cited = _the_first(detail).evidence

        if cited != expected:
            raise AssertionError(f"expected the evidence {expected}, got {cited}")

        return True

    return assertion


def _the_timeline_reads(expected: list[IncidentStatus]) -> Assertion[IncidentDetail]:
    def assertion(detail: IncidentDetail) -> bool:
        moved_to = [entry.to_status for entry in detail.timeline]

        if moved_to != expected:
            raise AssertionError(f"expected the timeline {expected}, got {moved_to}")

        return True

    return assertion


def _it_opened_on(expected: Alert) -> Assertion[IncidentSummary]:
    def assertion(summary: IncidentSummary) -> bool:
        if summary.alert != expected:
            raise AssertionError(f"expected the alert [{expected}], got [{summary.alert}]")

        return True

    return assertion


def _the_first(detail: IncidentDetail) -> Candidate:
    """The single candidate a one-candidate incident was shaped into.

    Checked here rather than by indexing inside each assertion, so a detail
    that came back with two fails saying so instead of quietly asserting on
    whichever landed first.
    """
    if len(detail.candidates) != 1:
        raise AssertionError(f"expected one candidate, got {len(detail.candidates)}")

    return detail.candidates[0]
