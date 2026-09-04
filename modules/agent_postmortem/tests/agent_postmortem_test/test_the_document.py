from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from agent_postmortem import (
    IncidentEvidence,
    PostmortemDocument,
    write_postmortem,
)
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
from argus_core.models.transcript import Transcript
from argus_core.models.turn import ToolCall, Turn
from argus_testkit import Assertion, Scenario, all_of

"""What the finished document carries, beside its figures.

The numbers have their own file. This is about everything a reader needs in
order to know what the numbers are worth: what the model says it assumed, how
many people the incident took - and, when the model answered in a shape Argus
cannot read, that the document says so rather than quietly reading as a
complete one.
"""

INCIDENT_START = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)
INCIDENT_END = INCIDENT_START + timedelta(minutes=30)

DONT_CARE_INCIDENT_ID = "e4e4e4e4-0000-4000-8000-000000000004"
DONT_CARE_TOKENS_SPENT = 1_000
DONT_CARE_HOURLY_REVENUE = 4_800
DONT_CARE_REVENUE_WINDOW = timedelta(hours=1)
DONT_CARE_ENGAGED_MINUTES = 25

SOME_CURRENCY = "usd"

DONT_CARE_RATE_DATE = date(2026, 9, 2)


@pytest.mark.unit
def test_what_the_model_says_it_assumed_is_carried_into_the_document() -> None:
    # The model is asked for anything else it took rather than measured, and
    # what it answers has to reach the page. Dropped, it would leave a
    # document claiming more certainty than the thing that wrote it had.
    some_assumption = "the log lines shown were the whole of the failing traffic"

    Scenario() \
        .given(
            an_evidence_bundle := _an_evidence_bundle()
        ) \
        .when(
            lambda: _a_postmortem_written_with(
                an_evidence_bundle,
                llm=_a_model_answering(assumptions=[some_assumption]))
        ) \
        .then(
            _discloses_an_assumption_naming(some_assumption)
        )


@pytest.mark.unit
def test_the_document_reports_how_many_people_the_incident_took() -> None:
    # Minutes alone cannot be read: twenty-five minutes is one person for
    # half an hour or five people for five, and an exec summary saying
    # "three engineers, two hours" needs the count to say it.
    some_responders = 3

    Scenario() \
        .given(
            an_evidence_bundle := _an_evidence_bundle()
        ) \
        .when(
            lambda: _a_postmortem_written_with(
                an_evidence_bundle,
                llm=_a_model_answering(),
                responders=some_responders)
        ) \
        .then(
            _reports_responders(some_responders)
        )


@pytest.mark.unit
def test_an_answer_in_a_shape_argus_cannot_read_is_written_down_as_incomplete() -> None:
    # A model that replies in prose has answered, and answered uselessly: no
    # field can be taken from it. The incident still gets a document - one
    # that says on its face that it is partial, which is what
    # `checklist_complete` is for.
    Scenario() \
        .given(
            an_evidence_bundle := _an_evidence_bundle()
        ) \
        .when(
            lambda: _a_postmortem_written_with(an_evidence_bundle,
                                               llm=_a_model_answering_in_prose())
        ) \
        .then(
            all_of(
                _is_marked_incomplete(),
                _reports_no_root_cause()
            )
        )


@pytest.mark.unit
def test_an_answer_calling_some_other_tool_is_written_down_as_incomplete() -> None:
    # Not the same failure as answering in prose, though it lands in the same
    # place: this model did reach for a tool, and reached for the wrong one.
    # Reading its arguments anyway would fill the document from a call that
    # was never the postmortem - fields with the right names, about something
    # else entirely.
    some_other_tool = "get_log_lines"

    Scenario() \
        .given(
            an_evidence_bundle := _an_evidence_bundle()
        ) \
        .when(
            lambda: _a_postmortem_written_with(
                an_evidence_bundle,
                llm=_a_model_calling(some_other_tool))
        ) \
        .then(
            all_of(
                _is_marked_incomplete(),
                _reports_no_root_cause()
            )
        )


@pytest.mark.unit
def test_the_document_reports_who_responded_by_title_and_never_by_name() -> None:
    # The titles are the half of the answer a reader can act on: "a senior
    # engineer and an SRE, two hours" is a sentence about an incident, where
    # two hours alone is a sentence about a clock. Names would make it a
    # document about people - and this one gets emailed.
    some_title = "Senior Software Engineer"
    some_other_title = "Site Reliability Engineer"

    Scenario() \
        .given(
            evidence := _an_evidence_bundle()
        ) \
        .when(
            lambda: _a_postmortem_written_with(
                evidence,
                llm=_a_model_answering(),
                responders=2,
                titles=[some_title, some_other_title])
        ) \
        .then(
            all_of(
                _reports_responders(2),
                _reports_the_titles(some_title, some_other_title)
            )
        )


def _a_postmortem_written_with(evidence: IncidentEvidence,
                               llm: LLMClient,
                               responders: int = 1,
                               titles: list[str] | None = None) -> PostmortemDocument:
    return write_postmortem(
        evidence,
        revenue=_a_revenue_source_reporting(DONT_CARE_HOURLY_REVENUE),
        rates=_rates_in(SOME_CURRENCY),
        engagement=_an_engagement_source_reporting(minutes=DONT_CARE_ENGAGED_MINUTES,
                                                   responders=responders,
                                                   titles=titles or []),
        metrics=_metrics_showing_a_rise(),
        llm=llm
    )


def _an_engagement_source_reporting(minutes: int,
                                    responders: int,
                                    titles: list[str] | None = None) -> Engagement:
    def engagement_for(dont_care_incident_id: str) -> EngagementAnswer | None:
        return EngagementAnswer(minutes=minutes,
                                responders=responders,
                                titles=titles or [])

    return engagement_for


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
    def revenue_between(window_start: datetime,
                        window_end: datetime) -> Mapping[str, Decimal] | None:
        return {SOME_CURRENCY: Decimal(
            amount * (window_end - window_start) / DONT_CARE_REVENUE_WINDOW)}

    return revenue_between


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


def _a_model_answering(assumptions: list[str] | None = None) -> LLMClient:
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
                        "assumptions": assumptions if assumptions is not None else []
                    }
                )],
                input_tokens=0,
                output_tokens=0
            )

    return OneAnswer()


def _a_model_answering_in_prose() -> LLMClient:
    """A model that ignored the tool it was offered and wrote a paragraph."""
    class ProseOnly:
        def converse(self,
                     transcript: Transcript,
                     tools: list[ToolDefinition],
                     max_tokens: int = 4096) -> Turn:
            return Turn(
                text="The incident was caused by a feature flag.",
                tool_calls=[],
                input_tokens=0,
                output_tokens=0
            )

    return ProseOnly()


def _discloses_an_assumption_naming(subject: str) -> Assertion[PostmortemDocument]:
    def assertion(document: PostmortemDocument) -> bool:
        if not any(subject in assumption for assumption in document.assumptions):
            raise AssertionError(
                f"expected an assumption mentioning [{subject}], got {document.assumptions}")

        return True

    return assertion


def _reports_responders(expected: int) -> Assertion[PostmortemDocument]:
    def assertion(document: PostmortemDocument) -> bool:
        if document.responders != expected:
            raise AssertionError(
                f"expected [{expected}] responders, got [{document.responders}]")

        return True

    return assertion


def _is_marked_incomplete() -> Assertion[PostmortemDocument]:
    def assertion(document: PostmortemDocument) -> bool:
        if document.checklist_complete:
            raise AssertionError(
                "expected a document nothing could be read into to be marked incomplete")

        return True

    return assertion


def _reports_no_root_cause() -> Assertion[PostmortemDocument]:
    def assertion(document: PostmortemDocument) -> bool:
        if document.root_cause is not None:
            raise AssertionError(
                f"expected no root cause where the model named none, "
                f"got [{document.root_cause}]")

        return True

    return assertion


def _a_model_calling(tool_name: str) -> LLMClient:
    """A model that called a tool, and not the one it was offered.

    Its arguments are shaped exactly like a postmortem's on purpose: if the
    call's name were ever ignored, this answer would sail into the document
    and read as a real one.
    """
    class WrongTool:
        def converse(self,
                     transcript: Transcript,
                     tools: list[ToolDefinition],
                     max_tokens: int = 4096) -> Turn:
            return Turn(
                text="",
                tool_calls=[ToolCall(
                    id="call_1",
                    name=tool_name,
                    arguments={
                        "root_cause": "a root cause from the wrong call",
                        "executive_summary": "a summary from the wrong call",
                        "assumptions": []
                    }
                )],
                input_tokens=0,
                output_tokens=0
            )

    return WrongTool()


def _rates_in(base: str) -> Rates:
    """A rate table in the currency this file's revenue are already in.

    No rate for anything else: a test that never takes money abroad has no
    conversion to make, and the table is here only to say which currency the
    document reports in.
    """
    def rates() -> RateTable | None:
        return RateTable(base=base, on=DONT_CARE_RATE_DATE, per_unit={})

    return rates


def _reports_the_titles(*expected: str) -> Assertion[PostmortemDocument]:
    """Exactly these, and nothing that could identify a person.

    Sorted rather than ordered: who was on it is the fact, and the order two
    people acknowledged in is not something a document should imply.
    """
    def assertion(document: PostmortemDocument) -> bool:
        if sorted(document.responder_titles) != sorted(expected):
            raise AssertionError(
                f"expected the titles {sorted(expected)}, got "
                f"{sorted(document.responder_titles)}")

        return True

    return assertion
