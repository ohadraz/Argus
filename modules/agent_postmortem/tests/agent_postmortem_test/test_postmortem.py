from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from agent_postmortem import (
    IMPACT_WEIGHT_ASSUMPTION_LABEL,
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
from argus_testkit.collecting import Kept

"""The whole postmortem, end to end, with every source faked.

One test, deliberately: it fixes the shape of the thing before any of its
parts are worth arguing about - what the agent is handed, what it asks the
model for, and what comes back. Everything after this narrows one figure at a
time.

The numbers are chosen so each computed figure can only come out right one
way. The incident ran half an hour, the service takes 4800 an hour when it is
well, and 28% of its traffic failed - so a model calling half of the affected
path revenue-bearing means 4800 x 0.5 x 0.28 x 0.5, and no other arithmetic
lands on 336.

The model answers by calling a tool rather than by writing a document. Prose
that has to be parsed back into fields is prose that can be parsed wrongly,
and the one number it does supply - how much of the affected path carried
revenue - would then arrive as a sentence.
"""

INCIDENT_START = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)
INCIDENT_END = INCIDENT_START + timedelta(minutes=30)

DONT_CARE_INCIDENT_ID = "e1e1e1e1-0000-4000-8000-000000000001"


@pytest.mark.unit
def test_a_postmortem_reports_the_model_s_prose_and_its_own_arithmetic() -> None:
    some_root_cause = "the checkout fallback was disabled by a flag toggle at 12:04"
    some_summary = "Checkout failed for half an hour after a flag change; reverted."
    some_incident_start = INCIDENT_START
    some_incident_end = INCIDENT_END
    some_tokens_spent = 48_120
    some_hourly_revenue = 4800
    one_hour = timedelta(hours=1)
    some_baseline_error_rate = 0.02
    some_error_rate_during_the_incident = 0.30
    some_impact_weight = 0.5
    some_engaged_minutes = 25
    some_responders = 2
    expected_total_engaged_minutes = some_engaged_minutes * some_responders
    expected_loss_estimate = (
        some_hourly_revenue * 
            _duration_in_hours(some_incident_start, some_incident_end) * 
            (some_error_rate_during_the_incident - some_baseline_error_rate) * 
            some_impact_weight
    )

    Scenario() \
        .given(
            an_evidence_bundle := _an_evidence_bundle(started_at=some_incident_start, 
                                                      ended_at=some_incident_end, 
                                                      tokens_spent=some_tokens_spent)
        ) \
        .when(
            lambda: write_postmortem(
                an_evidence_bundle,
                revenue=_a_revenue_source_reporting(some_hourly_revenue, per=one_hour),
                engagement=_an_engagement_source_reporting(
                    minutes=some_engaged_minutes, responders=some_responders),
                metrics=_metrics_showing_error_rates(
                    baseline=some_baseline_error_rate,
                    during=some_error_rate_during_the_incident),
                llm=_a_model_answering(
                    root_cause=some_root_cause,
                    executive_summary=some_summary,
                    impact_weight=some_impact_weight
                )
            )
        ) \
        .then(
            all_of(
                _reports_root_cause(some_root_cause),
                _reports_executive_summary(some_summary),
                _estimates_a_loss_of(Decimal(expected_loss_estimate)),
                _reports_engineer_minutes(expected_total_engaged_minutes),
                _reports_tokens_spent(some_tokens_spent),
                _discloses_an_assumption_naming(IMPACT_WEIGHT_ASSUMPTION_LABEL),
                _is_marked_complete()
            )
        )




@pytest.mark.unit
def test_the_metrics_window_reaches_the_end_of_the_incident() -> None:
    # The Investigator stops reading the moment it has a cause, so what it
    # stored ends somewhere in the middle: the recovery between the mitigation
    # landing and the incident ending was never fetched, and that recovery is
    # most of what the duration covers. A postmortem reusing that window would
    # report an incident that never got better.
    dont_care_hourly_revenue = 1_000
    dont_care_revenue_window = 1
    dont_care_responders = 1
    dont_care_engaged_minutes = 1
    dont_care_cause = "kuki"
    dont_care_summary = "buki"
    dont_care_impact_weight = 0.3
    windows_asked_for: Kept[tuple[datetime, datetime]] = Kept()

    Scenario() \
        .given(
            an_evidence_bundle := _an_evidence_bundle()
        ) \
        .when(
            lambda: write_postmortem(
                an_evidence_bundle,
                revenue=_a_revenue_source_reporting(dont_care_hourly_revenue,
                                                    per=timedelta(hours=dont_care_revenue_window)),
                engagement=_an_engagement_source_reporting(
                    minutes=dont_care_engaged_minutes, responders=dont_care_responders),
                metrics=_metrics_recording_the_window_into(windows_asked_for),
                llm=_a_model_answering(
                    root_cause=dont_care_cause,
                    executive_summary=dont_care_summary,
                    impact_weight=dont_care_impact_weight
                )
            )
        ) \
        .then(
            _asked_for_a_window_spanning(an_evidence_bundle, windows_asked_for)
        )


def _an_evidence_bundle(started_at: datetime = INCIDENT_START, 
                        ended_at: datetime = INCIDENT_END, 
                        tokens_spent: int = 0) -> IncidentEvidence:
    return IncidentEvidence(
        incident_id=DONT_CARE_INCIDENT_ID,
        started_at=started_at,
        ended_at=ended_at,
        alert_summary="checkout error rate above threshold",
        timeline=["investigating at 12:01", "mitigating at 12:12", "resolved at 12:30"],
        candidates=["flag toggle on checkout-fallback - confirmed"],
        actions=["disabled checkout-fallback restored - confirmed"],
        log_lines=["12:04 ERROR checkout: fallback unavailable"],
        tokens_spent=tokens_spent
    )


def _a_revenue_source_reporting(amount: float, per: timedelta) -> Revenue:
    """A service earning `amount` in every window of length `per`.

    Answering from the window it is asked for, rather than returning a fixed
    number, is what lets the agent choose a baseline window this test never
    has to name.
    """
    def revenue_between(window_start: datetime, window_end: datetime) -> Decimal | None:
        return  Decimal(amount * (window_end - window_start) / per)

    return revenue_between


def _an_engagement_source_reporting(minutes: int, responders: int) -> Engagement:
    def engagement_for(dont_care_incident_id: str) -> EngagementAnswer | None:
        return EngagementAnswer(minutes=minutes, responders=responders)

    return engagement_for


def _metrics_showing_error_rates(baseline: float, during: float) -> Metrics:
    """Calm minutes before the incident, departed minutes inside it.

    The window the agent asks for is its own business - what this fixes is
    what it finds there, which is a rise of exactly `during - baseline`.
    """
    def metrics_between(window_start: datetime, window_end: datetime) -> list[MetricBucket]:
        return [
            _a_bucket(at=INCIDENT_START - timedelta(minutes=1), error_rate=baseline),
            _a_bucket(at=INCIDENT_START + timedelta(minutes=5), error_rate=during),
            _a_bucket(at=INCIDENT_END - timedelta(minutes=1), error_rate=during)
        ]

    return metrics_between


def _a_bucket(at: datetime, error_rate: float) -> MetricBucket:
    return MetricBucket(
        bucket_id=at.strftime("%Y-%m-%dT%H:%M"),
        error_rate=error_rate,
        p50_ms=20,
        p95_ms=40,
        request_volume=1_000
    )


def _a_model_answering(root_cause: str,
                       executive_summary: str,
                       impact_weight: float) -> LLMClient:
    """A model that answers by calling the tool it was offered.

    It asserts nothing about the prompt - that is another test's subject - but
    it does insist on being given a tool to call, because an agent that asked
    for a document in prose would pass a test written against a double that
    happily answered in either shape.
    """
    class OneAnswer:
        def converse(self,
                     transcript: Transcript,
                     tools: list[ToolDefinition],
                     max_tokens: int = 4096) -> Turn:
            assert tools, "the postmortem must ask for a structured answer"
            return Turn(
                text="",
                tool_calls=[ToolCall(
                    id="call_1",
                    name=tools[0].name,
                    arguments={
                        "root_cause": root_cause,
                        "executive_summary": executive_summary,
                        "impact_weight": impact_weight,
                        "impact_weight_reason": "checkout is half of what the service sells",
                        "assumptions": []
                    }
                )],
                input_tokens=0,
                output_tokens=0
            )

    return OneAnswer()


def _reports_root_cause(expected: str) -> Assertion[PostmortemDocument]:
    def assertion(document: PostmortemDocument) -> bool:
        if document.root_cause != expected:
            raise AssertionError(
                f"expected the root cause [{expected}], got [{document.root_cause}]")
        return True

    return assertion


def _reports_executive_summary(expected: str) -> Assertion[PostmortemDocument]:
    def assertion(document: PostmortemDocument) -> bool:
        if document.executive_summary != expected:
            raise AssertionError(
                f"expected the summary [{expected}], "
                f"got [{document.executive_summary}]")
        return True

    return assertion


def _estimates_a_loss_of(expected: Decimal) -> Assertion[PostmortemDocument]:
    def assertion(document: PostmortemDocument) -> bool:
        if document.customer_loss_estimate_usd != expected:
            raise AssertionError(
                f"expected an estimate of [{expected}], "
                f"got [{document.customer_loss_estimate_usd}]")
        return True

    return assertion


def _reports_engineer_minutes(expected: int) -> Assertion[PostmortemDocument]:
    def assertion(document: PostmortemDocument) -> bool:
        if document.engineer_minutes != expected:
            raise AssertionError(
                f"expected [{expected}] engineer minutes, "
                f"got [{document.engineer_minutes}]")
        return True

    return assertion


def _reports_tokens_spent(expected: int) -> Assertion[PostmortemDocument]:
    def assertion(document: PostmortemDocument) -> bool:
        if document.tokens_spent != expected:
            raise AssertionError(
                f"expected [{expected}] tokens spent, got [{document.tokens_spent}]")
        return True

    return assertion


def _discloses_an_assumption_naming(subject: str) -> Assertion[PostmortemDocument]:
    def assertion(document: PostmortemDocument) -> bool:
        assumptions = document.assumptions or []
        if not any(subject in assumption for assumption in assumptions):
            raise AssertionError(
                f"expected an assumption mentioning [{subject}], got {assumptions}")
        return True

    return assertion


def _is_marked_complete() -> Assertion[PostmortemDocument]:
    def assertion(document: PostmortemDocument) -> bool:
        if not document.checklist_complete:
            raise AssertionError(
                "expected a document with every field filled to be marked complete")
        return True

    return assertion


def _duration_in_hours(start: datetime, end: datetime) -> float:
    return (end - start).total_seconds() / 3600


def _metrics_recording_the_window_into(
        windows: Kept[tuple[datetime, datetime]]) -> Metrics:
    def metrics_between(window_start: datetime, window_end: datetime) -> list[MetricBucket]:
        windows.take((window_start, window_end))

        return []

    return metrics_between


def _asked_for_a_window_spanning(
        evidence: IncidentEvidence,
        windows: Kept[tuple[datetime, datetime]]) -> Assertion[PostmortemDocument]:
    def assertion(dont_care_document: PostmortemDocument) -> bool:
        window_start, window_end = windows.only()

        if window_start > evidence.started_at:
            raise AssertionError(
                f"expected a window starting at or before the incident "
                f"[{evidence.started_at}], got [{window_start}]")

        if window_end < evidence.ended_at:
            raise AssertionError(
                f"expected a window reaching the end of the incident "
                f"[{evidence.ended_at}], got [{window_end}]")

        return True

    return assertion
