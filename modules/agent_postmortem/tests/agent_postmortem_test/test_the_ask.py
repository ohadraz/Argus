from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from agent_postmortem import IncidentEvidence, PostmortemDocument, write_postmortem
from agent_postmortem.prompting import SUBMIT_TOOL_NAME
from agent_postmortem.sources import (
    Engagement,
    EngagementAnswer,
    Metrics,
    Rates,
    RateTable,
    Revenue,
)
from argus_core.llm.client import LLMClient
from argus_core.models.metrics import MetricBucket
from argus_core.models.tool_definition import ToolDefinition
from argus_core.models.transcript import Ask, Transcript
from argus_core.models.turn import ToolCall, Turn
from argus_testkit import Assertion, Kept, Scenario, all_of

"""What the model is asked, and what it is not trusted to answer.

Two halves of one rule. The model is handed everything Argus knows about the
incident, because prose written about half an incident is prose that invents
the other half - and it is asked for no number at all, because every figure in
the document is measured and a model's arithmetic about a measurement is not a
second opinion, it is a second answer nobody can tell apart from the first.

The last test is the one that matters most and looks least like it: a summary
that names a figure Argus never computed must leave the stored figure alone.
It is the failure that would never be noticed, because the document would read
perfectly.
"""

INCIDENT_START = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)
INCIDENT_END = INCIDENT_START + timedelta(minutes=30)

DONT_CARE_INCIDENT_ID = "e3e3e3e3-0000-4000-8000-000000000003"
DONT_CARE_TOKENS_SPENT = 1_000
DONT_CARE_HOURLY_REVENUE = 4_800
DONT_CARE_REVENUE_WINDOW = timedelta(hours=1)
DONT_CARE_ENGAGED_MINUTES = 25
DONT_CARE_RESPONDERS = 2
DONT_CARE_RATE_DATE = date(2026, 9, 2)

SOME_CURRENCY = "usd"


@pytest.mark.unit
def test_the_model_is_told_what_the_incident_did() -> None:
    # Everything the walk produced, in the one message. A model asked to
    # explain an incident it was shown half of will explain the half it was
    # shown, confidently.
    some_alert = "checkout error rate above threshold"
    some_timeline_line = "mitigating at 12:12"
    some_candidate = "flag toggle on checkout-fallback - confirmed"
    some_action = "disabled checkout-fallback restored - confirmed"
    some_log_line = "12:04 ERROR checkout: fallback unavailable"
    asks: Kept[Transcript] = Kept()

    Scenario() \
        .given(
            an_evidence_bundle := _an_evidence_bundle(
                alert_summary=some_alert,
                timeline=[some_timeline_line],
                candidates=[some_candidate],
                actions=[some_action],
                log_lines=[some_log_line])
        ) \
        .when(
            lambda: _a_postmortem_written_with(an_evidence_bundle,
                                               llm=_a_model_recording_into(asks))
        ) \
        .then(
            _the_model_was_told(asks,
                                some_alert,
                                some_timeline_line,
                                some_candidate,
                                some_action,
                                some_log_line)
        )


@pytest.mark.unit
def test_the_model_is_offered_one_way_to_answer() -> None:
    # A model that may answer in prose sometimes will, and a document parsed
    # out of paragraphs fails silently: the fields are all present, and one of
    # them is a sentence that mentioned a number.
    asks: Kept[Transcript] = Kept()
    tools: Kept[list[ToolDefinition]] = Kept()

    Scenario() \
        .given(
            an_evidence_bundle := _an_evidence_bundle()
        ) \
        .when(
            lambda: _a_postmortem_written_with(
                an_evidence_bundle,
                llm=_a_model_recording_into(asks, offered_tools=tools))
        ) \
        .then(
            _was_offered_only(tools, SUBMIT_TOOL_NAME)
        )


@pytest.mark.unit
def test_a_model_that_answers_completely_is_asked_once() -> None:
    # The second call belongs to the checklist and to nothing else. An agent
    # that asked twice as a matter of course would double the cost of every
    # postmortem to improve none of them.
    asks: Kept[Transcript] = Kept()

    Scenario() \
        .given(
            an_evidence_bundle := _an_evidence_bundle()
        ) \
        .when(
            lambda: _a_postmortem_written_with(an_evidence_bundle,
                                               llm=_a_model_recording_into(asks))
        ) \
        .then(
            _was_asked_exactly_once(asks)
        )


@pytest.mark.unit
def test_the_prose_the_model_writes_never_moves_the_figures_beside_it() -> None:
    # Two runs differing only in wording. Neither summary names a figure -
    # a summary that named one Argus did not compute is a fault, and that is
    # the checklist's business, not this test's. What is under test here is
    # narrower and easier to get wrong: that prose and columns are written
    # from different sources, so no wording can reach the arithmetic.
    a_dramatic_summary = "the outage was severe and affected many customers"
    a_flat_summary = "checkout failed for half an hour and then recovered"

    Scenario() \
        .given(
            # The first run - the reference figure
            written_flatly := _a_postmortem_written_with(
                _an_evidence_bundle(),
                llm=_a_model_answering(executive_summary=a_flat_summary))
        ) \
        .when(
            # the second run - the dramatic prose
            lambda: _a_postmortem_written_with(
                _an_evidence_bundle(),
                llm=_a_model_answering(executive_summary=a_dramatic_summary))
        ) \
        .then(
            all_of(
                # uses the dramatic summary
                _reports_executive_summary(a_dramatic_summary),
                # but the estimate is the same as the first run's
                _estimates_a_loss_of(written_flatly.customer_loss_estimate)
            )
        )


@pytest.mark.unit
def test_a_model_given_no_metrics_is_told_they_are_unknown_rather_than_flat() -> None:
    # The prompt has to say which of the two happened. An incident whose
    # metrics could not be read, described to the model as one where nothing
    # rose, gets prose explaining why a service that was fine had an outage -
    # and the prose will be fluent, because it always is.
    asks: Kept[Transcript] = Kept()

    Scenario() \
        .given(
            an_evidence_bundle := _an_evidence_bundle()
        ) \
        .when(
            lambda: write_postmortem(
                an_evidence_bundle,
                revenue=_a_revenue_source_reporting(DONT_CARE_HOURLY_REVENUE),
                rates=_rates_in(SOME_CURRENCY),
                engagement=_an_engagement_source_reporting(
                    minutes=DONT_CARE_ENGAGED_MINUTES,
                    responders=DONT_CARE_RESPONDERS),
                metrics=_metrics_that_answer_with_nothing(),
                llm=_a_model_recording_into(asks)
            )
        ) \
        .then(
            _the_model_was_not_told_of_a_rise(asks)
        )


def _a_postmortem_written_with(evidence: IncidentEvidence,
                               llm: LLMClient) -> PostmortemDocument:
    return write_postmortem(
        evidence,
        revenue=_a_revenue_source_reporting(DONT_CARE_HOURLY_REVENUE),
        rates=_rates_in(SOME_CURRENCY),
        engagement=_an_engagement_source_reporting(minutes=DONT_CARE_ENGAGED_MINUTES,
                                                   responders=DONT_CARE_RESPONDERS),
        metrics=_metrics_showing_a_rise(),
        llm=llm
    )


def _an_evidence_bundle(alert_summary: str = "dont care",
                        timeline: list[str] | None = None,
                        candidates: list[str] | None = None,
                        actions: list[str] | None = None,
                        log_lines: list[str] | None = None) -> IncidentEvidence:
    return IncidentEvidence(
        incident_id=DONT_CARE_INCIDENT_ID,
        started_at=INCIDENT_START,
        ended_at=INCIDENT_END,
        alert_summary=alert_summary,
        timeline=timeline if timeline is not None else ["dont care"],
        candidates=candidates if candidates is not None else ["dont care"],
        actions=actions if actions is not None else ["dont care"],
        log_lines=log_lines if log_lines is not None else ["dont care"],
        tokens_spent=DONT_CARE_TOKENS_SPENT
    )


def _a_revenue_source_reporting(amount: float) -> Revenue:
    def revenue_between(window_start: datetime,
                        window_end: datetime) -> Mapping[str, Decimal] | None:
        return {SOME_CURRENCY: Decimal(
            amount * (window_end - window_start) / DONT_CARE_REVENUE_WINDOW)}

    return revenue_between


def _an_engagement_source_reporting(minutes: int, responders: int) -> Engagement:
    def engagement_for(dont_care_incident_id: str) -> EngagementAnswer | None:
        return EngagementAnswer(minutes=minutes, responders=responders)

    return engagement_for


def _metrics_showing_a_rise() -> Metrics:
    def metrics_between(dont_care_start: datetime, dont_care_end: datetime) -> list[MetricBucket]:
        return [
            _a_bucket(at=INCIDENT_START - timedelta(minutes=1), error_rate=0.02),
            _a_bucket(at=INCIDENT_START + timedelta(minutes=5), error_rate=0.30)
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


def _a_model_recording_into(asks: Kept[Transcript],
                            offered_tools: Kept[list[ToolDefinition]] | None = None,
                            ) -> LLMClient:
    """Answers completely, and keeps what it was asked and what it was offered.

    Complete on purpose: a double that answered badly would send the agent
    round the checklist a second time, and every count in this file would then
    be counting something else.
    """
    class RecordingModel:
        def converse(self,
                     transcript: Transcript,
                     tools: list[ToolDefinition],
                     max_tokens: int = 4096) -> Turn:
            asks.take(transcript)
            if offered_tools is not None:
                offered_tools.take(tools)

            return _a_complete_answer(tools[0].name, executive_summary="dont care")

    return RecordingModel()


def _a_model_answering(executive_summary: str) -> LLMClient:
    class OneAnswer:
        def converse(self,
                     transcript: Transcript,
                     tools: list[ToolDefinition],
                     max_tokens: int = 4096) -> Turn:
            return _a_complete_answer(tools[0].name, executive_summary)

    return OneAnswer()


def _a_complete_answer(tool_name: str,
                       executive_summary: str) -> Turn:
    return Turn(
        text="",
        tool_calls=[ToolCall(
            id="call_1",
            name=tool_name,
            arguments={
                "root_cause": "dont care",
                "executive_summary": executive_summary,
                "assumptions": []
            }
        )],
        input_tokens=0,
        output_tokens=0
    )


def _the_model_was_told(asks: Kept[Transcript], *expected: str) -> Assertion[PostmortemDocument]:
    def assertion(dont_care_document: PostmortemDocument) -> bool:
        said = _what_was_asked(asks.only())

        missing = [wanted for wanted in expected if wanted not in said]
        if missing:
            raise AssertionError(
                f"expected the model to be told {missing}, and it was not")

        return True

    return assertion


def _was_offered_only(tools: Kept[list[ToolDefinition]],
                      expected: str) -> Assertion[PostmortemDocument]:
    def assertion(dont_care_document: PostmortemDocument) -> bool:
        offered = [tool.name for tool in tools.only()]

        if offered != [expected]:
            raise AssertionError(f"expected only [{expected}] to be offered, got {offered}")

        return True

    return assertion


def _was_asked_exactly_once(asks: Kept[Transcript]) -> Assertion[PostmortemDocument]:
    def assertion(dont_care_document: PostmortemDocument) -> bool:
        if len(asks.taken) != 1:
            raise AssertionError(
                f"expected exactly one model call, got [{len(asks.taken)}]")

        return True

    return assertion


def _reports_executive_summary(expected: str) -> Assertion[PostmortemDocument]:
    def assertion(document: PostmortemDocument) -> bool:
        if document.executive_summary != expected:
            raise AssertionError(
                f"expected the summary [{expected}], got [{document.executive_summary}]")

        return True

    return assertion


def _estimates_a_loss_of(expected: Decimal | None) -> Assertion[PostmortemDocument]:
    def assertion(document: PostmortemDocument) -> bool:
        if document.customer_loss_estimate != expected:
            raise AssertionError(
                f"expected the computed estimate [{expected}], "
                f"got [{document.customer_loss_estimate}]")

        return True

    return assertion


def _what_was_asked(transcript: Transcript) -> str:
    return "\n".join(entry.text for entry in transcript if isinstance(entry, Ask))




def _metrics_that_answer_with_nothing() -> Metrics:
    def metrics_between(dont_care_start: datetime, dont_care_end: datetime) -> list[MetricBucket]:
        return []

    return metrics_between


def _the_model_was_not_told_of_a_rise(asks: Kept[Transcript]) -> Assertion[PostmortemDocument]:
    def assertion(dont_care_document: PostmortemDocument) -> bool:
        said = _what_was_asked(asks.only())

        if "not known" not in said:
            raise AssertionError(
                "expected the model to be told the error rate was not known, "
                f"and it was not: {said}")

        return True

    return assertion


def _rates_in(base: str) -> Rates:
    """A rate table in the currency this file's revenue are already in.

    No rate for anything else: a test that never takes money abroad has no
    conversion to make, and the table is here only to say which currency the
    document reports in.
    """
    def rates() -> RateTable | None:
        return RateTable(base=base, on=DONT_CARE_RATE_DATE, per_unit={})

    return rates
