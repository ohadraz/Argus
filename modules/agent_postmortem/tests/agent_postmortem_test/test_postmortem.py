from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from agent_postmortem import (
    EXCHANGE_RATE_ASSUMPTION_LABEL,
    EXCLUDED_CURRENCY_ASSUMPTION_LABEL,
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

# Five minutes before Argus was told, which is the ordinary case: an alert fires
# on a rule that needs a few minutes of bad traffic to trip.
SOME_ONSET = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)
SOME_INCIDENT_START = SOME_ONSET + timedelta(minutes=10)
SOME_INCIDENT_END = SOME_ONSET + timedelta(minutes=30)

DONT_CARE_INCIDENT_ID = "e1e1e1e1-0000-4000-8000-000000000001"

SOME_CURRENCY = "usd"
SOME_OTHER_CURRENCY = "eur"
SOME_UNPRICED_CURRENCY = "kuki"

DONT_CARE_RATE_DATE = date(2026, 9, 2)
DONT_CARE_BASELINE_ERROR_RATE = 0.02
DONT_CARE_ERROR_RATE_DURING_THE_INCIDENT = 0.30


@pytest.mark.unit
def test_a_postmortem_reports_the_model_s_prose_and_its_own_arithmetic() -> None:
    # Person-minutes, as the source answers them: two people, and their own
    # spans already added together. A document that multiplied by the count
    # again would charge every minute to everybody.
    some_engaged_person_minutes = 25
    some_responders = 2
    some_root_cause = "the checkout fallback was disabled by a flag toggle at 12:04"
    some_summary = "Checkout failed for half an hour after a flag change; reverted."
    some_tokens_spent = 48_120
    some_calm_hourly_revenue = 1_200
    some_revenue_during_the_incident = Decimal("100.00")
    some_incident_duration_in_hours = _duration_in_hours(SOME_ONSET, SOME_INCIDENT_END)
    some_revenue_that_should_have_come_in_unless_the_incident = (
        Decimal(some_calm_hourly_revenue) * Decimal(str(some_incident_duration_in_hours))
    )
    expected_loss_estimate = (
        some_revenue_that_should_have_come_in_unless_the_incident - 
        some_revenue_during_the_incident
    )

    Scenario() \
        .given(
            an_evidence_bundle := _an_evidence_bundle(
                started_at=SOME_INCIDENT_START, 
                ended_at=SOME_INCIDENT_END,
                onset_at=SOME_ONSET,
                tokens_spent=some_tokens_spent)
        ) \
        .when(
            lambda: write_postmortem(
                an_evidence_bundle,
                revenue=_a_shop_whose_revenue_was(
                    per_hour={SOME_CURRENCY: some_calm_hourly_revenue},
                    until=SOME_ONSET,
                    and_then={SOME_CURRENCY: some_revenue_during_the_incident}),
                rates=_rates_in(SOME_CURRENCY),
                engagement=_an_engagement_source_reporting(
                    minutes=some_engaged_person_minutes, responders=some_responders),
                metrics=_metrics_showing_error_rates(
                    baseline=DONT_CARE_BASELINE_ERROR_RATE, 
                    during=DONT_CARE_ERROR_RATE_DURING_THE_INCIDENT),
                llm=_a_model_answering(
                    root_cause=some_root_cause,
                    executive_summary=some_summary
                )
            )
        ) \
        .then(
            all_of(
                _reports_root_cause(some_root_cause),
                _reports_executive_summary(some_summary),
                _estimates_a_loss_of(Decimal(expected_loss_estimate)),
                _reports_engineer_minutes(minutes=some_engaged_person_minutes, 
                                          responders=some_responders),
                _reports_tokens_spent(some_tokens_spent),
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
    some_revenue_during_the_incident = Decimal("100.00")
    dont_care_responders = 1
    dont_care_engaged_minutes = 1
    dont_care_cause = "kuki"
    dont_care_summary = "buki"
    windows_asked_for: Kept[tuple[datetime, datetime]] = Kept()

    Scenario() \
        .given(
            an_evidence_bundle := _an_evidence_bundle()
        ) \
        .when(
            lambda: write_postmortem(
                an_evidence_bundle,
                revenue=_a_shop_whose_revenue_was(
                    per_hour={SOME_CURRENCY: dont_care_hourly_revenue},
                    until=SOME_ONSET,
                    and_then={SOME_CURRENCY: some_revenue_during_the_incident}),
                rates=_rates_in(SOME_CURRENCY),
                engagement=_an_engagement_source_reporting(
                    minutes=dont_care_engaged_minutes, responders=dont_care_responders),
                metrics=_metrics_recording_the_window_into(windows_asked_for),
                llm=_a_model_answering(
                    root_cause=dont_care_cause,
                    executive_summary=dont_care_summary
                )
            )
        ) \
        .then(
            _asked_for_a_window_spanning(an_evidence_bundle, windows_asked_for)
        )


@pytest.mark.unit
def test_revenue_in_another_currency_is_converted_at_a_rate_the_document_states() -> None:
    # The shop sells abroad, so the baseline hour is partly money that is not
    # in the currency the estimate is reported in. Converting it is the only
    # way the figure means anything - and the rate is a fact about a day rather
    # than a measurement of this incident, so it is published as an assumption
    # carrying the date it was published on. A figure converted at a rate
    # nobody can see is a figure nobody can check.
    dont_care_root_cause = "kuki"
    dont_care_summary = "buki"
    some_calm_hourly_revenue_in_foreign_currency = 800
    some_revenue_in_foreign_currency_during_the_incident = Decimal("200.00")
    some_rate = Decimal("0.80")
    some_rate_date = date(2026, 9, 2)
    dont_care_engaged_minutes = 1
    dont_care_responders = 1
    some_incident_duration_in_hours = _duration_in_hours(SOME_ONSET, SOME_INCIDENT_END)
    some_revenue_that_should_have_come_in_unless_the_incident = (
        Decimal(some_calm_hourly_revenue_in_foreign_currency) / some_rate
        * Decimal(str(some_incident_duration_in_hours))
    )

    expected_loss_estimate = (
        some_revenue_that_should_have_come_in_unless_the_incident
        - some_revenue_in_foreign_currency_during_the_incident / some_rate
    )

    Scenario() \
        .given(
            an_evidence_bundle := _an_evidence_bundle(started_at=SOME_INCIDENT_START, 
                                                      ended_at=SOME_INCIDENT_END,
                                                      onset_at=SOME_ONSET)
        ) \
        .when(
            lambda: write_postmortem(
                an_evidence_bundle,
                revenue=_a_shop_whose_revenue_was(
                    per_hour={
                        SOME_OTHER_CURRENCY: some_calm_hourly_revenue_in_foreign_currency
                        },
                    until=SOME_ONSET,
                    and_then={
                        SOME_OTHER_CURRENCY: some_revenue_in_foreign_currency_during_the_incident
                        }
                    ),
                rates=_rates_published(on=some_rate_date,
                                       per_unit={SOME_OTHER_CURRENCY: some_rate},
                                       base=SOME_CURRENCY),
                engagement=_an_engagement_source_reporting(
                    minutes=dont_care_engaged_minutes,
                    responders=dont_care_responders),
                metrics=_metrics_showing_error_rates(
                    baseline=DONT_CARE_BASELINE_ERROR_RATE,
                    during=DONT_CARE_ERROR_RATE_DURING_THE_INCIDENT),
                llm=_a_model_answering(
                    root_cause=dont_care_root_cause,
                    executive_summary=dont_care_summary
                )
            )
        ) \
        .then(
            all_of(
                _estimates_a_loss_of(Decimal(expected_loss_estimate)),
                _discloses_an_assumption_naming(EXCHANGE_RATE_ASSUMPTION_LABEL),
                _discloses_an_assumption_naming(str(some_rate)),
                _discloses_an_assumption_naming(some_rate_date.isoformat())
            )
        )


@pytest.mark.unit
def test_revenue_in_a_currency_with_no_rate_is_left_out_and_said_so() -> None:
    # The rate provider publishes thirty-odd currencies and a shop may take
    # one it does not cover. Losing the whole estimate over the part that
    # cannot be converted would throw away the part that can - and silently
    # dropping it would publish a figure that looks like all the money and is
    # not. So the figure covers what could be converted, and the document says
    # what it does not cover.
    dont_care_root_cause = "kuki"
    dont_care_summary = "buki"
    some_calm_hourly_revenue_in_local_currency = 1_000
    some_revenue_during_the_incident_in_local_currency = Decimal("100.00")
    dont_care_hourly_revenue_that_cannot_be_priced = 400
    dont_care_revenue_during_the_incident_that_cannot_be_priced = Decimal("50.00")
    dont_care_engaged_minutes = 1
    dont_care_responders = 1

    expected_loss_estimate = (
        Decimal(some_calm_hourly_revenue_in_local_currency) 
        * Decimal(str(_duration_in_hours(SOME_ONSET, SOME_INCIDENT_END)))
        - some_revenue_during_the_incident_in_local_currency
    )

    Scenario() \
        .given(
            an_evidence_bundle := _an_evidence_bundle(started_at=SOME_INCIDENT_START,
                                                      ended_at=SOME_INCIDENT_END,
                                                      onset_at=SOME_ONSET)
        ) \
        .when(
            lambda: write_postmortem(
                an_evidence_bundle,
                revenue=_a_shop_whose_revenue_was(
                    per_hour={
                        SOME_CURRENCY: some_calm_hourly_revenue_in_local_currency,
                        SOME_UNPRICED_CURRENCY: dont_care_hourly_revenue_that_cannot_be_priced},
                    until=SOME_ONSET,
                    and_then={
                        SOME_CURRENCY: some_revenue_during_the_incident_in_local_currency,
                        SOME_UNPRICED_CURRENCY: 
                            dont_care_revenue_during_the_incident_that_cannot_be_priced}),
                rates=_rates_published(on=DONT_CARE_RATE_DATE,
                                       per_unit={},
                                       base=SOME_CURRENCY),
                engagement=_an_engagement_source_reporting(
                    minutes=dont_care_engaged_minutes,
                    responders=dont_care_responders),
                metrics=_metrics_showing_error_rates(
                    baseline=DONT_CARE_BASELINE_ERROR_RATE,
                    during=DONT_CARE_ERROR_RATE_DURING_THE_INCIDENT),
                llm=_a_model_answering(
                    root_cause=dont_care_root_cause,
                    executive_summary=dont_care_summary
                )
            )
        ) \
        .then(
            all_of(
                _estimates_a_loss_of(Decimal(expected_loss_estimate)),
                _discloses_an_assumption_naming(EXCLUDED_CURRENCY_ASSUMPTION_LABEL),
                _discloses_an_assumption_naming(SOME_UNPRICED_CURRENCY)
            )
        )


@pytest.mark.unit
def test_the_document_names_the_currency_its_estimate_is_in() -> None:
    # A bare number is not an amount of money. The reporting currency is
    # configured, so a figure published without it is one a reader has to
    # guess at - and a guess that is right today is wrong the day the setting
    # changes. It travels with the document rather than being read back from
    # configuration, because what was reported cannot be allowed to change
    # afterwards.
    dont_care_root_cause = "kuki"
    dont_care_summary = "buki"
    dont_care_hourly_revenue = 1_200
    dont_care_revenue_during_the_incident = Decimal("100.00")
    dont_care_engaged_minutes = 1
    dont_care_responders = 1
    dont_care_metrics_baseline = 0.02
    dont_care_metrics_during = 0.30

    Scenario() \
        .given(
            an_evidence_bundle := _an_evidence_bundle(
                started_at=SOME_INCIDENT_START,
                ended_at=SOME_INCIDENT_END,
                onset_at=SOME_ONSET)
        ) \
        .when(
            lambda: write_postmortem(
                an_evidence_bundle,
                revenue=_a_shop_whose_revenue_was(
                    per_hour={SOME_CURRENCY: dont_care_hourly_revenue},
                    until=SOME_ONSET,
                    and_then={SOME_CURRENCY: dont_care_revenue_during_the_incident}),
                rates=_rates_in(SOME_CURRENCY),
                engagement=_an_engagement_source_reporting(
                    minutes=dont_care_engaged_minutes, responders=dont_care_responders),
                metrics=_metrics_showing_error_rates(
                    baseline=dont_care_metrics_baseline, during=dont_care_metrics_during),
                llm=_a_model_answering(root_cause=dont_care_root_cause,
                                       executive_summary=dont_care_summary)
            )
        ) \
        .then(
            _states_the_estimate_is_in(SOME_CURRENCY)
        )


def _states_the_estimate_is_in(expected: str) -> Assertion[PostmortemDocument]:
    def assertion(document: PostmortemDocument) -> bool:
        if document.estimate_currency != expected:
            raise AssertionError(
                f"expected the estimate to be reported in [{expected}], got "
                f"[{document.estimate_currency}]")

        return True

    return assertion


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
            _a_bucket(at=SOME_INCIDENT_START - timedelta(minutes=1), error_rate=baseline),
            _a_bucket(at=SOME_INCIDENT_START + timedelta(minutes=5), error_rate=during),
            _a_bucket(at=SOME_INCIDENT_END - timedelta(minutes=1), error_rate=during)
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
                       executive_summary: str) -> LLMClient:
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
        if document.customer_loss_estimate != expected:
            raise AssertionError(
                f"expected an estimate of [{expected}], "
                f"got [{document.customer_loss_estimate}]")
        return True

    return assertion


def _reports_engineer_minutes(minutes: int,
                              responders: int) -> Assertion[PostmortemDocument]:
    """The person-minutes, and how many people they were spread across.

    Both together, because either alone would pass on a document that
    multiplied them: 25 minutes across 2 responders and 50 across 1 differ in
    what they say about the night, and only checking the pair tells them apart.
    """
    def assertion(document: PostmortemDocument) -> bool:
        if document.engineer_minutes != minutes:
            raise AssertionError(
                f"expected [{minutes}] engineer minutes, "
                f"got [{document.engineer_minutes}]")

        if document.responders != responders:
            raise AssertionError(
                f"expected [{minutes}] engineer minutes across [{responders}] "
                f"responder(s), got [{document.responders}] responder(s)")

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


def _rates_published(on: date, per_unit: Mapping[str, Decimal], base: str) -> Rates:
    """A rate table as the source would hand one over.

    The base is the currency the document reports in: under this design the
    table is where that is decided, so a test that wants a figure in dollars
    says so here and nowhere else.
    """
    def rates() -> RateTable | None:
        return RateTable(base=base, on=on, per_unit=per_unit)

    return rates


def _rates_in(base: str) -> Rates:
    """A rate table in the currency this file's revenue are already in.

    No rate for anything else: a test that never takes money abroad has no
    conversion to make, and the table is here only to say which currency the
    document reports in.
    """
    def rates() -> RateTable | None:
        return RateTable(base=base, on=DONT_CARE_RATE_DATE, per_unit={})

    return rates


def _an_evidence_bundle(started_at: datetime = SOME_INCIDENT_START,
                        ended_at: datetime = SOME_INCIDENT_END,
                        onset_at: datetime | None = None,
                        tokens_spent: int = 0) -> IncidentEvidence:
    return IncidentEvidence(
        incident_id=DONT_CARE_INCIDENT_ID,
        started_at=started_at,
        ended_at=ended_at,
        onset_at=onset_at,
        alert_summary="checkout error rate above threshold",
        timeline=["investigating at 12:01", "mitigating at 12:12", "resolved at 12:30"],
        candidates=["flag toggle on checkout-fallback - confirmed"],
        actions=["disabled checkout-fallback restored - confirmed"],
        log_lines=["12:04 ERROR checkout: fallback unavailable"],
        tokens_spent=tokens_spent
    )


def _a_shop_whose_revenue_was(per_hour: Mapping[str, float],
                              until: datetime,
                              and_then: Mapping[str, Decimal]) -> Revenue:
    """A shop with two different afternoons.

    Before the onset it takes a steady rate, so any window asked for answers
    in proportion to its length - which is what lets the agent choose a
    baseline window this test never has to name. From the onset onwards it
    takes one fixed sum, because that window is the incident and the incident
    happened once.

    Two behaviours in one double because the port is asked twice and the
    windows are what tell the calls apart, which is itself half of what these
    tests fix.
    """
    def revenue_between(window_start: datetime,
                        window_end: datetime) -> Mapping[str, Decimal] | None:
        if window_start >= until:
            return dict(and_then)

        return {
            currency: Decimal(rate * (window_end - window_start) / timedelta(hours=1))
            for currency, rate in per_hour.items()
        }

    return revenue_between
