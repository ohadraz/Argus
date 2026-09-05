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
from agent_postmortem.document import (
    PAY_BAND_ASSUMPTION_LABEL,
    PAY_BANDS_UNAVAILABLE_ASSUMPTION,
    UNPRICED_TITLE_ASSUMPTION_LABEL,
    WORKING_YEAR_ASSUMPTION_LABEL,
)
from agent_postmortem.sources import (
    EngagedResponder,
    Engagement,
    EngagementAnswer,
    Metrics,
    PayBand,
    PayBands,
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

"""What the document says the response cost.

The arithmetic is settled elsewhere, in `test_responder_cost.py`. What is at
stake here is whether the finished document carries that figure, its range, and
the two disclosures that make it checkable: the working year the bands were
divided by, and which band each title was priced at. A figure resting on a
divisor nobody published is a figure nobody can reproduce.

The other half is the absence. A title no band covers, or an HR source that
could not be read, leaves the cost off the document while the minutes stay on
it - and the reason has to be on the page, or the gap reads as a bug in Argus
rather than as a band nobody configured.
"""

INCIDENT_START = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)
INCIDENT_END = INCIDENT_START + timedelta(minutes=30)
SOME_ONSET = INCIDENT_START - timedelta(minutes=10)

DONT_CARE_INCIDENT_ID = "e2e2e2e2-0000-4000-8000-000000000003"
DONT_CARE_TOKENS_SPENT = 1_000
DONT_CARE_HOURLY_REVENUE = 4_800
DONT_CARE_REVENUE_WINDOW = timedelta(hours=1)
DONT_CARE_RATE_DATE = date(2026, 9, 2)

SOME_CURRENCY = "usd"

SOME_TITLE = "Senior Kuki"
SOME_TITLE_NO_BAND_COVERS = "Principal Buki"

# A 2000-hour year is 120,000 minutes, so a midpoint of 120,000 is worth one
# unit a minute and an arithmetic slip shows as a different figure rather than
# as a rounding argument.
SOME_WORKING_YEAR_IN_HOURS = 2000.0
SOME_WORKING_YEAR_IN_MINUTES = Decimal(120_000)

SOME_BAND = PayBand(
    minimum=Decimal(60_000),
    midpoint=Decimal(120_000),
    maximum=Decimal(240_000),
    currency=SOME_CURRENCY
)

SOME_ENGAGED_MINUTES = 30


@pytest.mark.unit
def test_the_document_prices_the_minutes_it_reports() -> None:
    # The figure and the minutes have to describe the same response. A document
    # reporting thirty minutes and pricing forty-five is one nobody can check,
    # and the two numbers sit inches apart on the page.
    cost_at_midpoint = SOME_BAND.midpoint * SOME_ENGAGED_MINUTES / SOME_WORKING_YEAR_IN_MINUTES
    cost_at_minimum = SOME_BAND.minimum * SOME_ENGAGED_MINUTES / SOME_WORKING_YEAR_IN_MINUTES
    cost_at_maximum = SOME_BAND.maximum * SOME_ENGAGED_MINUTES / SOME_WORKING_YEAR_IN_MINUTES
    an_engagement = _an_engagement_source_reporting(
        [EngagedResponder(minutes=SOME_ENGAGED_MINUTES, job_title=SOME_TITLE)])
    the_bands = _a_band_source_pricing({SOME_TITLE: SOME_BAND})

    Scenario() \
        .given(
            an_evidence_bundle := _an_evidence_bundle()
        ) \
        .when(
            lambda: write_postmortem(
                an_evidence_bundle,
                revenue=_a_revenue_source_reporting(DONT_CARE_HOURLY_REVENUE),
                rates=_rates_in(SOME_CURRENCY),
                engagement=an_engagement,
                bands=the_bands,
                metrics=_metrics_showing_a_rise(),
                working_hours_a_year=SOME_WORKING_YEAR_IN_HOURS,
                llm=_a_model_answering()
            )
        ) \
        .then(all_of(
            _reports_engineer_minutes(SOME_ENGAGED_MINUTES),
            _reports_a_responder_cost_of(cost_at_midpoint),
            _reports_a_cost_ranging_from(cost_at_minimum, cost_at_maximum),
            _reports_the_cost_in(SOME_CURRENCY)
        ))


@pytest.mark.unit
def test_the_document_discloses_the_working_year_and_the_bands_it_used() -> None:
    # Both halves of the arithmetic, because neither is measured. The working
    # year is a convention somebody configured, and the band is a range this
    # document collapsed to a point - a reader who cannot see either is being
    # asked to take the figure on trust.
    an_engagement = _an_engagement_source_reporting(
        [EngagedResponder(minutes=SOME_ENGAGED_MINUTES, job_title=SOME_TITLE)])
    the_bands = _a_band_source_pricing({SOME_TITLE: SOME_BAND})

    Scenario() \
        .given(
            an_evidence_bundle := _an_evidence_bundle()
        ) \
        .when(
            lambda: write_postmortem(
                an_evidence_bundle,
                revenue=_a_revenue_source_reporting(DONT_CARE_HOURLY_REVENUE),
                rates=_rates_in(SOME_CURRENCY),
                engagement=an_engagement,
                bands=the_bands,
                metrics=_metrics_showing_a_rise(),
                working_hours_a_year=SOME_WORKING_YEAR_IN_HOURS,
                llm=_a_model_answering()
            )
        ) \
        .then(all_of(
            _discloses_an_assumption_mentioning(WORKING_YEAR_ASSUMPTION_LABEL,
                                                str(int(SOME_WORKING_YEAR_IN_HOURS))),
            _discloses_an_assumption_mentioning(PAY_BAND_ASSUMPTION_LABEL, SOME_TITLE)
        ))


@pytest.mark.unit
def test_a_title_no_band_covers_leaves_the_minutes_and_takes_the_cost() -> None:
    # The minutes were measured and the cost was not, so only one of them goes.
    # Suppressing both would throw away an answer Argus has; publishing the
    # priced responder's share alone would charge the incident for one person
    # and quietly not for the other.
    an_engagement = _an_engagement_source_reporting([
        EngagedResponder(minutes=SOME_ENGAGED_MINUTES, job_title=SOME_TITLE),
        EngagedResponder(minutes=SOME_ENGAGED_MINUTES,
                         job_title=SOME_TITLE_NO_BAND_COVERS)
    ])
    the_bands = _a_band_source_pricing({SOME_TITLE: SOME_BAND})

    Scenario() \
        .given(
            an_evidence_bundle := _an_evidence_bundle()
        ) \
        .when(
            lambda: write_postmortem(
                an_evidence_bundle,
                revenue=_a_revenue_source_reporting(DONT_CARE_HOURLY_REVENUE),
                rates=_rates_in(SOME_CURRENCY),
                engagement=an_engagement,
                bands=the_bands,
                metrics=_metrics_showing_a_rise(),
                working_hours_a_year=SOME_WORKING_YEAR_IN_HOURS,
                llm=_a_model_answering()
            )
        ) \
        .then(all_of(
            _reports_engineer_minutes(SOME_ENGAGED_MINUTES * 2),
            _reports_no_responder_cost(),
            _discloses_an_assumption_mentioning(UNPRICED_TITLE_ASSUMPTION_LABEL,
                                                SOME_TITLE_NO_BAND_COVERS)
        ))


@pytest.mark.unit
def test_a_band_source_that_cannot_be_read_costs_nothing_but_the_figure() -> None:
    # An HR system Argus could not reach is not evidence that the response was
    # free. The same distinction the revenue source already makes, and the
    # incident is over by the time this runs - so the document is written
    # without the figure rather than not written.
    an_engagement = _an_engagement_source_reporting(
        [EngagedResponder(minutes=SOME_ENGAGED_MINUTES, job_title=SOME_TITLE)])
    the_bands = _a_band_source_that_cannot_answer()

    Scenario() \
        .given(
            an_evidence_bundle := _an_evidence_bundle()
        ) \
        .when(
            lambda: write_postmortem(
                an_evidence_bundle,
                revenue=_a_revenue_source_reporting(DONT_CARE_HOURLY_REVENUE),
                rates=_rates_in(SOME_CURRENCY),
                engagement=an_engagement,
                bands=the_bands,
                metrics=_metrics_showing_a_rise(),
                working_hours_a_year=SOME_WORKING_YEAR_IN_HOURS,
                llm=_a_model_answering()
            )
        ) \
        .then(all_of(
            _reports_engineer_minutes(SOME_ENGAGED_MINUTES),
            _reports_no_responder_cost(),
            _discloses_the_assumption(PAY_BANDS_UNAVAILABLE_ASSUMPTION)
        ))


def _an_evidence_bundle() -> IncidentEvidence:
    return IncidentEvidence(
        incident_id=DONT_CARE_INCIDENT_ID,
        started_at=INCIDENT_START,
        ended_at=INCIDENT_END,
        onset_at=SOME_ONSET,
        alert_summary="dont care",
        timeline=["dont care"],
        candidates=["dont care"],
        actions=["dont care"],
        log_lines=["dont care"],
        tokens_spent=DONT_CARE_TOKENS_SPENT
    )


def _an_engagement_source_reporting(engaged: list[EngagedResponder]) -> Engagement:
    """A source answering the response per person, and the total beside it.

    The total is summed here rather than stated independently, because a source
    whose two answers disagree is a case about that source and not about this
    document.
    """
    def engagement_for(dont_care_incident_id: str) -> EngagementAnswer | None:
        return EngagementAnswer(
            minutes=sum(responder.minutes for responder in engaged),
            responders=len(engaged),
            titles=[responder.job_title for responder in engaged
                    if responder.job_title is not None],
            engaged=engaged
        )

    return engagement_for


def _a_band_source_pricing(bands: Mapping[str, PayBand]) -> PayBands:
    def pay_bands() -> Mapping[str, PayBand] | None:
        return bands

    return pay_bands


def _a_band_source_that_cannot_answer() -> PayBands:
    def pay_bands() -> Mapping[str, PayBand] | None:
        return None

    return pay_bands


def _a_revenue_source_reporting(amount: float) -> Revenue:
    def revenue_between(window_start: datetime,
                        window_end: datetime) -> Mapping[str, Decimal] | None:
        return {SOME_CURRENCY: Decimal(
            amount * (window_end - window_start) / DONT_CARE_REVENUE_WINDOW)}

    return revenue_between


def _rates_in(base: str) -> Rates:
    def rates() -> RateTable | None:
        return RateTable(base=base, on=DONT_CARE_RATE_DATE, per_unit={})

    return rates


def _metrics_showing_a_rise() -> Metrics:
    def metrics_between(dont_care_start: datetime,
                        dont_care_end: datetime) -> list[MetricBucket]:
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


def _a_model_answering() -> LLMClient:
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
                        "assumptions": []
                    }
                )],
                input_tokens=0,
                output_tokens=0
            )

    return OneAnswer()


def _reports_engineer_minutes(expected: int) -> Assertion[PostmortemDocument]:
    def assertion(document: PostmortemDocument) -> bool:
        if document.engineer_minutes != expected:
            raise AssertionError(
                f"expected [{expected}] engineer minutes, got "
                f"[{document.engineer_minutes}]")

        return True

    return assertion


def _reports_a_responder_cost_of(expected: Decimal) -> Assertion[PostmortemDocument]:
    def assertion(document: PostmortemDocument) -> bool:
        if document.responder_cost_estimate != expected:
            raise AssertionError(
                f"expected a responder cost of [{expected}], got "
                f"[{document.responder_cost_estimate}]")

        return True

    return assertion


def _reports_a_cost_ranging_from(minimum: Decimal,
                                 maximum: Decimal) -> Assertion[PostmortemDocument]:
    def assertion(document: PostmortemDocument) -> bool:
        got = (document.responder_cost_minimum, document.responder_cost_maximum)
        if got != (minimum, maximum):
            raise AssertionError(
                f"expected the responder cost to range from [{minimum}] to "
                f"[{maximum}], got {got}")

        return True

    return assertion


def _reports_the_cost_in(expected: str) -> Assertion[PostmortemDocument]:
    def assertion(document: PostmortemDocument) -> bool:
        if document.responder_cost_currency != expected:
            raise AssertionError(
                f"expected the responder cost in [{expected}], got "
                f"[{document.responder_cost_currency}]")

        return True

    return assertion


def _reports_no_responder_cost() -> Assertion[PostmortemDocument]:
    def assertion(document: PostmortemDocument) -> bool:
        if document.responder_cost_estimate is not None:
            raise AssertionError(
                f"expected no responder cost where a responder could not be "
                f"priced, got [{document.responder_cost_estimate}]")

        return True

    return assertion


def _discloses_the_assumption(expected: str) -> Assertion[PostmortemDocument]:
    def assertion(document: PostmortemDocument) -> bool:
        if expected not in document.assumptions:
            raise AssertionError(
                f"expected the assumption [{expected}], got {document.assumptions}")

        return True

    return assertion


def _discloses_an_assumption_mentioning(label: str,
                                        detail: str) -> Assertion[PostmortemDocument]:
    """One assumption carrying both the label and what it is about.

    The wording is the document's own, so this asserts the parts a reader has
    to be able to find rather than the sentence around them - a test spelling
    out the whole line would fail on a comma.
    """
    def assertion(document: PostmortemDocument) -> bool:
        if not any(label in stated and detail in stated
                   for stated in document.assumptions):
            raise AssertionError(
                f"expected an assumption mentioning [{label}] and [{detail}], "
                f"got {document.assumptions}")

        return True

    return assertion
