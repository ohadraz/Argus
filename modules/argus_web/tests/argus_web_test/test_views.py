from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from argus_core.ids import new_id
from argus_core.models.actor import Actor
from argus_core.models.alert import Alert
from argus_core.models.cause import CauseType
from argus_core.models.hypothesis import Hypothesis
from argus_core.models.incident_status import IncidentStatus
from argus_web.views import build_incident_detail, build_incident_summary
from orchestrator.repository.actions import Action
from orchestrator.repository.incidents import Incident
from orchestrator.repository.timeline import TimelineEvent

"""Shaping an incident's rows into what a reader is shown.

No database here: the rows these take are what the repositories already return,
and every question below is about the arrangement rather than the retrieval -
which attempt belongs to which candidate, what an untried candidate looks like,
and what happens to an attempt that names no candidate at all.
"""


@pytest.mark.unit
def test_an_attempt_is_shown_against_the_candidate_it_was_taken_for() -> None:
    # Attached to the candidate, because "what did we try for this
    # explanation?" is the question a reader has while looking at one.
    an_incident = _an_incident()
    first = _a_candidate(an_incident.id, subject="first", rank=1)
    second = _a_candidate(an_incident.id, subject="second", rank=2)

    detail = build_incident_detail(
        an_incident,
        candidates=[first, second],
        attempts=[
            _an_attempt(an_incident.id, first.id, outcome="refuted"),
            _an_attempt(an_incident.id, second.id, outcome="confirmed"),
        ],
        timeline=[],
    )

    shown = [
        (candidate.subject, [attempt.outcome for attempt in candidate.attempts])
        for candidate in detail.candidates
    ]
    assert shown == [("first", ["refuted"]), ("second", ["confirmed"])]


@pytest.mark.unit
def test_a_candidate_the_walk_never_reached_is_shown_as_untried() -> None:
    # "Never reached" and "tried and refuted" are the difference between a walk
    # that ran out of options and one that stopped because it was right.
    an_incident = _an_incident()
    never_reached = _a_candidate(an_incident.id, subject="never reached", rank=2)

    detail = build_incident_detail(
        an_incident, candidates=[never_reached], attempts=[], timeline=[]
    )

    shown = detail.candidates[0]
    assert shown.tested is False
    assert shown.result is None
    assert shown.attempts == []


@pytest.mark.unit
def test_a_refuted_attempt_is_shown_as_having_been_put_back() -> None:
    # A reversible action that did not help is undone before its verdict is
    # returned. A page showing the attempt without that would leave a reader
    # believing the flag is still flipped.
    an_incident = _an_incident()
    refuted = _a_candidate(an_incident.id, subject="refuted", rank=1)
    confirmed = _a_candidate(an_incident.id, subject="confirmed", rank=2)

    detail = build_incident_detail(
        an_incident,
        candidates=[refuted, confirmed],
        attempts=[
            _an_attempt(an_incident.id, refuted.id, outcome="refuted"),
            _an_attempt(an_incident.id, confirmed.id, outcome="confirmed"),
        ],
        timeline=[],
    )

    assert detail.candidates[0].attempts[0].undone is True
    assert detail.candidates[1].attempts[0].undone is False


@pytest.mark.unit
def test_an_attempt_with_no_verdict_yet_is_shown_as_undecided_rather_than_undone() -> None:
    # An action taken a second ago has no answer yet, and calling that "not
    # undone" is right while calling it "refuted" or "confirmed" would not be.
    an_incident = _an_incident()
    in_flight = _a_candidate(an_incident.id, subject="in flight", rank=1)

    detail = build_incident_detail(
        an_incident,
        candidates=[in_flight],
        attempts=[_an_attempt(an_incident.id, in_flight.id, outcome=None)],
        timeline=[],
    )

    attempt = detail.candidates[0].attempts[0]
    assert attempt.outcome is None
    assert attempt.undone is False


@pytest.mark.unit
def test_an_attempt_naming_no_candidate_is_still_shown() -> None:
    # `action.hypothesis_id` is nullable, so an action can arrive attributed to
    # nothing. Dropping it would delete a change Argus made to the service from
    # the only account of what it did.
    an_incident = _an_incident()
    a_candidate = _a_candidate(an_incident.id, subject="a-flag", rank=1)

    detail = build_incident_detail(
        an_incident,
        candidates=[a_candidate],
        attempts=[_an_attempt(an_incident.id, None, outcome="confirmed")],
        timeline=[],
    )

    assert detail.candidates[0].attempts == []
    assert [attempt.outcome for attempt in detail.unattributed_attempts] == ["confirmed"]


@pytest.mark.unit
def test_a_candidate_carries_the_evidence_it_was_formed_from() -> None:
    # Evidence in a collection of its own makes a reader correlate claims to
    # timestamps, which is the reader investigating the incident again.
    an_incident = _an_incident()
    a_candidate = _a_candidate(
        an_incident.id,
        subject="a-flag",
        rank=1,
        evidence=["error rate rose at 10:14", "a-flag was enabled at 10:13"],
    )

    detail = build_incident_detail(
        an_incident, candidates=[a_candidate], attempts=[], timeline=[]
    )

    assert detail.candidates[0].evidence == [
        "error rate rose at 10:14",
        "a-flag was enabled at 10:13",
    ]


@pytest.mark.unit
def test_an_incident_is_shown_with_the_alert_it_opened_on() -> None:
    # The row stores the alert as the JSON it was normalized into. A reader
    # gets the alert back, not the payload it was stored as.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate", severity="critical")

    summary = build_incident_summary(_an_incident(alert=some_alert))

    assert summary.alert == some_alert


@pytest.mark.unit
def test_an_incident_is_shown_with_the_transitions_it_went_through() -> None:
    # The status is where the incident ended. The transitions are how it got
    # there, and they are the only record of an incident that moved twice.
    an_incident = _an_incident()

    detail = build_incident_detail(
        an_incident,
        candidates=[],
        attempts=[],
        timeline=[
            _a_transition(an_incident.id, IncidentStatus.INVESTIGATING, "incident created"),
            _a_transition(an_incident.id, IncidentStatus.RESOLVED, "mitigation attempted"),
        ],
    )

    assert [entry.to_status for entry in detail.timeline] == [
        IncidentStatus.INVESTIGATING,
        IncidentStatus.RESOLVED,
    ]


@pytest.mark.unit
def test_an_incident_that_formed_no_candidate_is_shown_as_empty() -> None:
    # An incident that escalated before forming a hypothesis is a real incident
    # with nothing to show, which is not the same as an unknown one.
    detail = build_incident_detail(
        _an_incident(), candidates=[], attempts=[], timeline=[]
    )

    assert detail.candidates == []


def _an_incident(alert: Alert | None = None) -> Incident:
    return Incident(
        id=new_id(),
        alert_payload=(alert or Alert(service="io-shop", alert_name="HighErrorRate"))
        .model_dump(mode="json"),
        status=IncidentStatus.INVESTIGATING,
        slack_channel_id=None,
        pr_url=None,
        created_at=datetime(2026, 8, 30, 10, 15, tzinfo=UTC),
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
        rank=rank,
    )


def _an_attempt(incident_id: str,
                hypothesis_id: str | None,
                outcome: str | None) -> Action:
    return Action(
        id=new_id(),
        incident_id=incident_id,
        hypothesis_id=hypothesis_id,
        type="revert-feature-flag",
        target=None,
        reversible=True,
        tier=None,
        undo_descriptor={"flag": "dont-care", "was_enabled": True},
        outcome=outcome,
        taken_at=datetime(2026, 8, 30, 10, 16, tzinfo=UTC),
        approved_by=None,
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
        created_at=datetime(2026, 8, 30, 10, 15, tzinfo=UTC) + timedelta(minutes=1),
    )
