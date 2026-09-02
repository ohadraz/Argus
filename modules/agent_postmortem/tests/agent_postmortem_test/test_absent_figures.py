from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from agent_postmortem import (
    ENGAGEMENT_UNAVAILABLE_ASSUMPTION,
    REVENUE_UNAVAILABLE_ASSUMPTION,
    IncidentEvidence,
    PostmortemDocument,
    write_postmortem,
)
from agent_postmortem.sources import Engagement, EngagementAnswer, Metrics, Revenue
from argus_core.llm.client import LLMClient
from argus_core.models.metrics import MetricBucket
from argus_core.models.tool_definition import ToolDefinition
from argus_core.models.transcript import Transcript
from argus_core.models.turn import ToolCall, Turn
from argus_testkit import Assertion, Scenario, all_of

"""A figure nobody could answer, and the difference between that and zero.

The distinction this file exists for is one a reader cannot make for
themselves: a postmortem reporting no loss and a postmortem that could not
find out are the same blank on the page, and only one of them is a
measurement. So every absence here has to arrive with the reason beside it.

A source that is down is not evidence about the incident. Reading it as zero
revenue, or as nobody having responded, invents a finding out of an outage in
Argus's own dependencies - and it is the flattering direction to get wrong,
which is what makes it worth a file.
"""

INCIDENT_START = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)
INCIDENT_END = INCIDENT_START + timedelta(minutes=30)

DONT_CARE_INCIDENT_ID = "e2e2e2e2-0000-4000-8000-000000000002"
DONT_CARE_TOKENS_SPENT = 1_000
DONT_CARE_HOURLY_REVENUE = 4_800
DONT_CARE_IMPACT_WEIGHT = 0.5
DONT_CARE_ENGAGED_MINUTES = 25
DONT_CARE_RESPONDERS = 2
DONT_CARE_REVENUE_WINDOW = timedelta(hours=1)


@pytest.mark.unit
def test_a_revenue_source_that_cannot_be_read_estimates_nothing_rather_than_zero() -> None:
    # Zero here would be a postmortem telling an executive the outage cost
    # them nothing, on the strength of a service Argus failed to reach.
    Scenario() \
        .given(
            an_evidence_bundle := _an_evidence_bundle()
        ) \
        .when(
            lambda: write_postmortem(
                an_evidence_bundle,
                revenue=_a_revenue_source_that_cannot_answer(),
                engagement=_an_engagement_source_reporting(
                    minutes=DONT_CARE_ENGAGED_MINUTES,
                    responders=DONT_CARE_RESPONDERS),
                metrics=_metrics_showing_a_rise(),
                llm=_a_model_answering(DONT_CARE_IMPACT_WEIGHT)
            )
        ) \
        .then(
            all_of(
                _estimates_nothing(),
                _discloses_the_assumption(REVENUE_UNAVAILABLE_ASSUMPTION)
            )
        )


@pytest.mark.unit
def test_metrics_that_cannot_be_read_estimate_nothing_rather_than_zero() -> None:
    # The other term that can go missing. Without a rise in errors there is
    # nothing to scale the revenue rate by, and an incident whose metrics were
    # unreadable is not an incident that cost nothing.
    Scenario() \
        .given(
            an_evidence_bundle := _an_evidence_bundle()
        ) \
        .when(
            lambda: write_postmortem(
                an_evidence_bundle,
                revenue=_a_revenue_source_reporting(DONT_CARE_HOURLY_REVENUE),
                engagement=_an_engagement_source_reporting(
                    minutes=DONT_CARE_ENGAGED_MINUTES,
                    responders=DONT_CARE_RESPONDERS),
                metrics=_metrics_that_answer_with_nothing(),
                llm=_a_model_answering(DONT_CARE_IMPACT_WEIGHT)
            )
        ) \
        .then(
            _estimates_nothing()
        )


@pytest.mark.unit
def test_an_engagement_source_that_cannot_be_read_reports_no_engineer_minutes() -> None:
    # Which is where this starts, since no such source exists yet: every
    # postmortem written today takes this path, and it has to read as an
    # unanswered question rather than as an incident nobody worked on.
    Scenario() \
        .given(
            an_evidence_bundle := _an_evidence_bundle()
        ) \
        .when(
            lambda: write_postmortem(
                an_evidence_bundle,
                revenue=_a_revenue_source_reporting(DONT_CARE_HOURLY_REVENUE),
                engagement=_an_engagement_source_that_cannot_answer(),
                metrics=_metrics_showing_a_rise(),
                llm=_a_model_answering(DONT_CARE_IMPACT_WEIGHT)
            )
        ) \
        .then(
            all_of(
                _reports_no_engineer_minutes(),
                _discloses_the_assumption(ENGAGEMENT_UNAVAILABLE_ASSUMPTION)
            )
        )


@pytest.mark.unit
def test_an_incident_nobody_responded_to_reports_no_minutes_and_says_nothing_was_missing() -> None:
    # The case the type exists to separate. A source that answered "nobody"
    # has measured something: Argus handled it alone. That is zero minutes,
    # not an unanswered question, and it must not carry the same apology.
    nobody = 0

    Scenario() \
        .given(
            an_evidence_bundle := _an_evidence_bundle()
        ) \
        .when(
            lambda: write_postmortem(
                an_evidence_bundle,
                revenue=_a_revenue_source_reporting(DONT_CARE_HOURLY_REVENUE),
                engagement=_an_engagement_source_reporting(minutes=nobody,
                                                           responders=nobody),
                metrics=_metrics_showing_a_rise(),
                llm=_a_model_answering(DONT_CARE_IMPACT_WEIGHT)
            )
        ) \
        .then(
            all_of(
                _reports_engineer_minutes(nobody),
                _discloses_no_assumption_about(ENGAGEMENT_UNAVAILABLE_ASSUMPTION)
            )
        )


def _an_evidence_bundle() -> IncidentEvidence:
    return IncidentEvidence(
        incident_id=DONT_CARE_INCIDENT_ID,
        started_at=INCIDENT_START,
        ended_at=INCIDENT_END,
        alert_summary="dont care",
        timeline=["dont care"],
        candidates=["dont care"],
        actions=["dont care"],
        log_lines=["dont care"],
        tokens_spent=DONT_CARE_TOKENS_SPENT
    )


def _a_revenue_source_reporting(amount: float) -> Revenue:
    def revenue_between(window_start: datetime, window_end: datetime) -> Decimal | None:
        return Decimal(amount * (window_end - window_start) / DONT_CARE_REVENUE_WINDOW)

    return revenue_between


def _a_revenue_source_that_cannot_answer() -> Revenue:
    """A source that is reachable in the type and not in fact.

    `None` rather than an exception: an unreadable source is an ordinary
    outcome of writing a postmortem, not an error in writing one, and an
    incident does not go unrecorded because a payment API was down.
    """
    def revenue_between(dont_care_start: datetime, dont_care_end: datetime) -> Decimal | None:
        return None

    return revenue_between


def _an_engagement_source_reporting(minutes: int, responders: int) -> Engagement:
    def engagement_for(dont_care_incident_id: str) -> EngagementAnswer | None:
        return EngagementAnswer(minutes=minutes, responders=responders)

    return engagement_for


def _an_engagement_source_that_cannot_answer() -> Engagement:
    def engagement_for(dont_care_incident_id: str) -> EngagementAnswer | None:
        return None

    return engagement_for


def _metrics_showing_a_rise() -> Metrics:
    def metrics_between(dont_care_start: datetime, dont_care_end: datetime) -> list[MetricBucket]:
        return [
            _a_bucket(at=INCIDENT_START - timedelta(minutes=1), error_rate=0.02),
            _a_bucket(at=INCIDENT_START + timedelta(minutes=5), error_rate=0.30)
        ]

    return metrics_between


def _metrics_that_answer_with_nothing() -> Metrics:
    def metrics_between(dont_care_start: datetime, dont_care_end: datetime) -> list[MetricBucket]:
        return []

    return metrics_between


def _a_bucket(at: datetime, error_rate: float) -> MetricBucket:
    return MetricBucket(
        bucket_id=at.strftime("%Y-%m-%dT%H:%M"),
        error_rate=error_rate,
        p50_ms=20,
        p95_ms=40,
        request_volume=1_000
    )


def _a_model_answering(impact_weight: float) -> LLMClient:
    class OneAnswer:
        def converse(self,
                     transcript: Transcript,
                     tools: list[ToolDefinition],
                     max_tokens: int = 4096) -> Turn:
            return Turn(
                text="",
                tool_calls=[ToolCall(
                    id="call_1",
                    name=tools[0].name,
                    arguments={
                        "root_cause": "dont care",
                        "executive_summary": "dont care",
                        "impact_weight": impact_weight,
                        "impact_weight_reason": "dont care",
                        "assumptions": []
                    }
                )],
                input_tokens=0,
                output_tokens=0
            )

    return OneAnswer()


def _estimates_nothing() -> Assertion[PostmortemDocument]:
    def assertion(document: PostmortemDocument) -> bool:
        if document.customer_loss_estimate_usd is not None:
            raise AssertionError(
                f"expected no estimate where a term of it could not be read, "
                f"got [{document.customer_loss_estimate_usd}]")
        return True

    return assertion


def _reports_no_engineer_minutes() -> Assertion[PostmortemDocument]:
    def assertion(document: PostmortemDocument) -> bool:
        if document.engineer_minutes is not None:
            raise AssertionError(
                f"expected no engineer minutes where nobody could say, "
                f"got [{document.engineer_minutes}]")
        return True

    return assertion


def _reports_engineer_minutes(expected: int) -> Assertion[PostmortemDocument]:
    def assertion(document: PostmortemDocument) -> bool:
        if document.engineer_minutes != expected:
            raise AssertionError(
                f"expected [{expected}] engineer minutes, got [{document.engineer_minutes}]")
        return True

    return assertion


def _discloses_the_assumption(expected: str) -> Assertion[PostmortemDocument]:
    def assertion(document: PostmortemDocument) -> bool:
        if expected not in document.assumptions:
            raise AssertionError(
                f"expected the assumption [{expected}], got {document.assumptions}")
        return True

    return assertion


def _discloses_no_assumption_about(unexpected: str) -> Assertion[PostmortemDocument]:
    def assertion(document: PostmortemDocument) -> bool:
        if unexpected in document.assumptions:
            raise AssertionError(
                f"expected no apology for a question that was answered, "
                f"got [{unexpected}]")
        return True

    return assertion
