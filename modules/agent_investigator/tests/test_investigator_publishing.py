from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from agent_investigator import Findings, investigate
from argus_core.events import (
    HypothesisFormed,
    IncidentEvent,
    LogsRetrieved,
    MetricsRetrieved,
    OnsetDetected,
    Publisher,
    RetrievalChannel,
    RetrievalRequested,
)
from argus_core.ids import new_id
from argus_core.models.alert import Alert
from argus_core.models.cause import CauseType
from argus_core.models.hypothesis import Hypothesis
from argus_core.models.metrics import MetricBucket

"""What the Investigator says about its own work.

The loop already decides which window to read and which minute the incident
started in; none of that survived the call until now. These say it is
published as it happens - the channel, the window, what came back, and every
explanation formed from it - and that an investigation nobody is listening to
reaches exactly the same conclusion.
"""


@pytest.mark.unit
def test_the_metrics_it_read_are_published_with_the_buckets_that_came_back() -> None:
    # The page shows the table Argus read. Publishing the request without the
    # answer would leave a narration that says it looked and never says at what.
    published: list[IncidentEvent] = []

    _an_investigation_publishing_to(published)

    retrieved = _the_only(MetricsRetrieved, published)
    assert [bucket.error_rate for bucket in retrieved.buckets] == _AN_INCIDENT_STARTING_CALM


@pytest.mark.unit
def test_the_channel_it_asked_is_published_before_the_answer() -> None:
    # A channel that failed is a fact about the investigation; a narration that
    # only ever mentions channels that answered hides the ones that did not.
    published: list[IncidentEvent] = []

    _an_investigation_publishing_to(published)

    asked = [event.channel for event in published if isinstance(event, RetrievalRequested)]
    assert RetrievalChannel.METRICS in asked
    assert RetrievalChannel.LOGS in asked
    assert RetrievalChannel.CHANGES in asked


@pytest.mark.unit
def test_the_onset_it_found_is_published() -> None:
    # Which minute the incident started is the loop's own decision, not the
    # model's, and it is what every window after it is anchored on.
    published: list[IncidentEvent] = []

    _an_investigation_publishing_to(published)

    assert _the_only(OnsetDetected, published).onset == _THE_MINUTE_IT_BROKE


@pytest.mark.unit
def test_a_log_window_is_published_with_both_bounds_and_the_lines_it_returned() -> None:
    # "Argus read the logs" is not readable. "Argus read the logs between
    # 10:02 and 10:12, and here they are" is the whole point of the stream.
    published: list[IncidentEvent] = []
    the_lines_it_read = ["2026-08-30T10:03:00Z ERROR io-shop: division by zero"]

    _an_investigation_publishing_to(published, log_lines=the_lines_it_read)

    retrieved = _the_only(LogsRetrieved, published)
    assert retrieved.window_start < retrieved.window_end
    assert retrieved.lines == the_lines_it_read


@pytest.mark.unit
def test_every_candidate_it_formed_is_published() -> None:
    # The runner-up is what makes a walk a walk. A narration carrying only the
    # answer that was acted on describes a guess that happened to be right.
    published: list[IncidentEvent] = []
    best = _a_candidate(subject="the-primary", confidence=0.9, rank=1)
    runner_up = _a_candidate(subject="the-runner-up", confidence=0.6, rank=2)

    _an_investigation_publishing_to(published, candidates=[best, runner_up])

    formed = [event for event in published if isinstance(event, HypothesisFormed)]
    assert [event.subject for event in formed] == ["the-primary", "the-runner-up"]


@pytest.mark.unit
def test_a_published_candidate_is_the_candidate_that_was_returned() -> None:
    # The narration and the walk have to be the same hypothesis seen twice, or
    # a reader is left reconciling two accounts of one investigation.
    published: list[IncidentEvent] = []
    some_candidate = _a_candidate(subject="a-flag", confidence=0.9, rank=1)

    findings = _an_investigation_publishing_to(published, candidates=[some_candidate])

    formed = _the_only(HypothesisFormed, published)
    assert formed.hypothesis_id == findings.candidates[0].id


@pytest.mark.unit
def test_a_published_candidate_carries_what_it_was_formed_from() -> None:
    # A claim without its evidence is an assertion, and a page that shows one
    # asks an audience to take Argus's word for it. The evidence is already on
    # the hypothesis; publishing it is what lets the account show the working
    # rather than only the conclusion.
    published: list[IncidentEvent] = []
    what_it_rests_on = [
        "monthly-spend-feature began evaluating on at 10:05",
        "the error rate left its baseline at 10:06",
    ]
    some_candidate = _a_candidate(
        subject="monthly-spend-feature", confidence=0.9, rank=1, evidence=what_it_rests_on
    )

    _an_investigation_publishing_to(published, candidates=[some_candidate])

    assert _the_only(HypothesisFormed, published).evidence == what_it_rests_on


@pytest.mark.unit
def test_an_investigation_nobody_is_listening_to_concludes_the_same_thing() -> None:
    # The account is never part of the work. This is the test that says so.
    published: list[IncidentEvent] = []
    some_candidate = _a_candidate(subject="a-flag", confidence=0.9, rank=1)

    listened_to = _an_investigation_publishing_to(published, candidates=[some_candidate])
    unheard = _an_investigation(candidates=[some_candidate])

    assert [candidate.subject for candidate in listened_to.candidates] == [
        candidate.subject for candidate in unheard.candidates
    ]
    assert listened_to.can_widen == unheard.can_widen


_THE_ALERT_FIRED_AT = datetime(2026, 8, 30, 10, 8, tzinfo=UTC)
_AN_INCIDENT_STARTING_CALM = [0.01, 0.01, 0.01, 0.40, 0.42]
_THE_MINUTE_IT_BROKE = "2026-08-30T10:06:00Z"
_DONT_CARE_LOGS = ["2026-08-30T10:03:00Z INFO io-shop: something happened"]


def _an_investigation_publishing_to(published: list[IncidentEvent],
                                    log_lines: list[str] | None = None,
                                    candidates: list[Hypothesis] | None = None) -> Findings:
    return _an_investigation(log_lines, candidates, publisher=published.append)


def _an_investigation(log_lines: list[str] | None = None,
                      candidates: list[Hypothesis] | None = None,
                      publisher: Publisher | None = None) -> Findings:
    answered = candidates or [_a_candidate(subject="a-flag", confidence=0.9, rank=1)]

    return investigate(
        Alert(service="io-shop", alert_name="HighErrorRate", started_at=_THE_ALERT_FIRED_AT),
        incident_id=answered[0].incident_id,
        fetch_metrics=lambda dont_care_anchor: _a_window_of(_AN_INCIDENT_STARTING_CALM),
        fetch_logs=lambda dont_care_start, dont_care_end: log_lines or _DONT_CARE_LOGS,
        fetch_change_events=lambda *dont_care_args: [],
        propose_hypotheses=lambda dont_care_evidence: answered,
        publisher=publisher if publisher is not None else _nobody,
    )


def _nobody(dont_care_event: IncidentEvent) -> None:
    """An investigation with nothing listening, spelled out rather than left to
    the default - the point of the test is that the two agree."""


def _a_candidate(subject: str,
                 confidence: float,
                 rank: int,
                 evidence: list[str] | None = None) -> Hypothesis:
    return Hypothesis(
        incident_id=_SOME_INCIDENT_ID,
        summary=f"dont care - {subject}",
        cause_type=CauseType.FEATURE_FLAG_TOGGLE,
        confidence=confidence,
        supporting_evidence=evidence or [],
        subject=subject,
        rank=rank,
    )


def _a_window_of(error_rates: list[float]) -> list[MetricBucket]:
    """Minutes ending at the alert, the incident starting inside them."""
    first_minute = _THE_ALERT_FIRED_AT - timedelta(minutes=len(error_rates))

    return [
        MetricBucket(
            bucket_id=(first_minute + timedelta(minutes=offset)).strftime(
                "%Y-%m-%dT%H:%M:00Z"
            ),
            error_rate=error_rate,
            p50_ms=90,
            p95_ms=220,
            request_volume=200,
        )
        for offset, error_rate in enumerate(error_rates)
    ]


def _the_only[Event](kind: type[Event], published: list[IncidentEvent]) -> Event:
    found = [event for event in published if isinstance(event, kind)]

    assert len(found) == 1, f"Expected one {kind.__name__}, got {len(found)}."

    return found[0]


_SOME_INCIDENT_ID = new_id()
