from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from agent_postmortem import IncidentEvidence, PostmortemDocument, write_postmortem
from agent_postmortem.measuring import Measurements
from agent_postmortem.prompting import (
    ASSUMPTIONS_FIELD,
    EXECUTIVE_SUMMARY_FIELD,
    ROOT_CAUSE_FIELD,
)
from agent_postmortem.responder_cost import ResponderCost
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
    Sources,
)
from argus_core.llm.client import LLMClient
from argus_core.models.metrics import MetricBucket
from argus_core.models.tool_definition import ToolDefinition
from argus_core.models.transcript import Transcript
from argus_core.models.turn import ToolCall, Turn
from argus_testkit import Kept

"""One incident, the sources that describe it, and what measuring it produced.

Every test that drives the agent needs six sources answering before it reaches
anything it is actually about, and every test downstream of the measuring needs
a `Measurements` before it reaches anything it is about. Spelled out per file,
those arrangements get copied and drift: two files disagree about how long the
incident ran, and a reader cannot tell whether the difference is the point.

So the incident is fixed here, and each builder is written to be asked for the
one thing its test cares about. What a test does not name, it does not care
about - which is what makes the thing it does name visible.
"""

# One incident, dated from its onset. The alert is late by ten minutes, which
# is the ordinary case rather than an edge one: a rule needs a few minutes of
# bad traffic to trip, and those minutes are the ones a baseline must not
# swallow.
ONSET = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)
STARTED_AT = ONSET + timedelta(minutes=10)
ENDED_AT = ONSET + timedelta(minutes=30)

DONT_CARE_INCIDENT_ID = "e1e1e1e1-0000-4000-8000-000000000001"
DONT_CARE_TOKENS_SPENT = 1_000
DONT_CARE_HOURLY_REVENUE = 4_800
DONT_CARE_REVENUE_DURING_THE_INCIDENT = Decimal("100.00")
DONT_CARE_ENGAGED_MINUTES = 25
DONT_CARE_RESPONDERS = 2
DONT_CARE_WORKING_YEAR = 2080.0
DONT_CARE_RATE_DATE = date(2026, 9, 2)
DONT_CARE_BASELINE_ERROR_RATE = 0.02
DONT_CARE_ERROR_RATE_DURING_THE_INCIDENT = 0.30

DONT_CARE_DURATION_IN_HOURS = 0.5
DONT_CARE_BASELINE_REVENUE = Decimal("4800")
DONT_CARE_LOSS = Decimal("500")

AN_HOUR = timedelta(hours=1)

SOME_CURRENCY = "usd"
SOME_OTHER_CURRENCY = "eur"
SOME_UNPRICED_CURRENCY = "kuki"

DONT_CARE_TAKINGS = {SOME_CURRENCY: DONT_CARE_BASELINE_REVENUE}
DONT_CARE_TABLE = RateTable(base=SOME_CURRENCY, on=DONT_CARE_RATE_DATE, per_unit={})

# An incident Argus handled alone, and no bands to price nobody at. Real values
# rather than `None` defaults, so a test passing `None` is saying "nobody could
# read this" and gets exactly that - which a `None`-means-default cannot
# express, and which is the one distinction these tests are about.
NOBODY_RESPONDED = EngagementAnswer(minutes=0, responders=0)
NO_BANDS_NEEDED: Mapping[str, PayBand] = {}


def an_evidence_bundle(started_at: datetime = STARTED_AT,
                       ended_at: datetime = ENDED_AT,
                       onset_at: datetime | None = ONSET,
                       alert_summary: str = "dont care",
                       timeline: list[str] | None = None,
                       candidates: list[str] | None = None,
                       actions: list[str] | None = None,
                       log_lines: list[str] | None = None,
                       tokens_spent: int = DONT_CARE_TOKENS_SPENT) -> IncidentEvidence:
    """The incident as the Orchestrator hands it over.

    An onset by default, because an incident with one is the ordinary case and
    the only one that can be costed. The tests about its absence say so.
    """
    return IncidentEvidence(
        incident_id=DONT_CARE_INCIDENT_ID,
        started_at=started_at,
        ended_at=ended_at,
        onset_at=onset_at,
        alert_summary=alert_summary,
        timeline=timeline if timeline is not None else ["dont care"],
        candidates=candidates if candidates is not None else ["dont care"],
        actions=actions if actions is not None else ["dont care"],
        log_lines=log_lines if log_lines is not None else ["dont care"],
        tokens_spent=tokens_spent
    )


def a_measured_incident(duration_in_hours: float = DONT_CARE_DURATION_IN_HOURS,
                        error_rate_delta: float | None = None,
                        loss: Decimal | None = DONT_CARE_LOSS,
                        baseline_revenue: Decimal | None = DONT_CARE_BASELINE_REVENUE,
                        takings: Mapping[str, Decimal] | None = None,
                        rates: RateTable | None = DONT_CARE_TABLE,
                        left_out: list[str] | None = None,
                        onset_at: datetime | None = ONSET,
                        engaged: EngagementAnswer | None = NOBODY_RESPONDED,
                        cost: ResponderCost | None = None,
                        bands: Mapping[str, PayBand] | None = NO_BANDS_NEEDED) -> Measurements:
    """An incident every figure could be read for, unless a test says otherwise.

    Each default is a question that *was* answered, because every absence has a
    consequence of its own - a default that left one unanswered would put that
    consequence in every result in the file using this.

    An incident Argus handled alone by default: a response nobody gave is
    measured, costs nothing, and apologises for nothing, so a test not about
    people never has to say anything about them.

    `currency` is not settable: it is the table's base, and a measured incident
    whose figure is in a currency its own rate table does not name is not a
    state anything can produce.
    """
    return Measurements(
        duration_in_hours=duration_in_hours,
        error_rate_delta=error_rate_delta,
        loss=loss if baseline_revenue is not None else None,
        currency=rates.base if rates is not None else None,
        baseline_revenue=baseline_revenue,
        baseline_takings=takings if takings is not None else DONT_CARE_TAKINGS,
        rates=rates,
        currencies_left_out=left_out if left_out is not None else [],
        onset_at=onset_at,
        engaged=engaged,
        cost=cost,
        bands=bands
    )


def some_sources(revenue: Revenue | None = None,
                 rates: Rates | None = None,
                 engagement: Engagement | None = None,
                 bands: PayBands | None = None,
                 metrics: Metrics | None = None,
                 working_hours_a_year: float = DONT_CARE_WORKING_YEAR) -> Sources:
    """Everything the postmortem reads, with each source answering plainly.

    A test names only the source it is about and leaves the other five alone,
    which is what makes the failure it describes attributable to the source it
    named.
    """
    return Sources(
        revenue=revenue if revenue is not None
                else revenue_that_was(
                    per_hour={SOME_CURRENCY: DONT_CARE_HOURLY_REVENUE},
                    until=ONSET,
                    and_then={SOME_CURRENCY: DONT_CARE_REVENUE_DURING_THE_INCIDENT}),
        rates=rates if rates is not None else rates_in(SOME_CURRENCY),
        engagement=engagement if engagement is not None
                   else an_engagement_source_reporting(
                       minutes=DONT_CARE_ENGAGED_MINUTES,
                       responders=DONT_CARE_RESPONDERS),
        bands=bands if bands is not None else a_band_source_pricing_nobody(),
        metrics=metrics if metrics is not None else metrics_showing_a_rise(),
        working_hours_a_year=working_hours_a_year
    )


def a_postmortem_written_with(evidence: IncidentEvidence,
                              llm: LLMClient,
                              sources: Sources | None = None) -> PostmortemDocument:
    """The agent driven through its front door, with nothing faked but its
    sources and the model.

    Every collaborator inside stays real, which is what makes a test using this
    a component test rather than a unit one.
    """
    return write_postmortem(evidence,
                            sources if sources is not None else some_sources(),
                            llm)


def revenue_that_was(per_hour: Mapping[str, float],
                             until: datetime,
                             and_then: Mapping[str, Decimal]) -> Revenue:
    """A service with two different afternoons.

    Before `until` it takes a steady rate, so any window asked for answers in
    proportion to its length - which is what lets the agent choose a baseline
    window no test has to name. From `until` onwards it takes one fixed sum,
    because that window is the incident and the incident happened once.

    Two behaviours in one double because the port is asked twice, and the
    windows are what tell the calls apart.
    """
    def revenue_between(window_start: datetime,
                        window_end: datetime) -> Mapping[str, Decimal] | None:
        if window_start >= until:
            return dict(and_then)

        return {
            currency: Decimal(rate * (window_end - window_start) / AN_HOUR)
            for currency, rate in per_hour.items()
        }

    return revenue_between


def a_revenue_source_reporting(amount: float) -> Revenue:
    """A shop taking the same rate whichever window is asked for.

    For tests that need a readable revenue source and nothing more: both
    windows answer in proportion to their length, and no test asserting on a
    figure should be reading one out of this.
    """
    def revenue_between(window_start: datetime,
                        window_end: datetime) -> Mapping[str, Decimal] | None:
        return {SOME_CURRENCY: Decimal(amount * (window_end - window_start) / AN_HOUR)}

    return revenue_between


def a_revenue_source_that_cannot_answer() -> Revenue:
    """A source that is reachable in the type and not in fact.

    `None` rather than an exception: an unreadable source is an ordinary
    outcome of writing a postmortem, not an error in writing one, and an
    incident does not go unrecorded because a payment API was down.
    """
    def revenue_between(dont_care_start: datetime,
                        dont_care_end: datetime) -> Mapping[str, Decimal] | None:
        return None

    return revenue_between


def rates_in(base: str) -> Rates:
    """A rate table in the currency the revenue is already in.

    No rate for anything else: a test that never takes money abroad has no
    conversion to make, and the table is here only to say which currency the
    document reports in.
    """
    return rates_published(on=DONT_CARE_RATE_DATE, per_unit={}, base=base)


def rates_published(on: date, per_unit: Mapping[str, Decimal], base: str) -> Rates:
    """A rate table as the source would hand one over.

    The base is the currency the document reports in: under this design the
    table is where that is decided, so a test that wants a figure in dollars
    says so here and nowhere else.
    """
    def rates() -> RateTable | None:
        return RateTable(base=base, on=on, per_unit=per_unit)

    return rates


def rates_that_cannot_be_read() -> Rates:
    """No table at all, which is not the same as a table with no rates in it.

    Without one there is no currency to publish a figure in, and naming one
    would be a guess about which money this is.
    """
    def rates() -> RateTable | None:
        return None

    return rates


def an_engagement_source_reporting(minutes: int,
                                   responders: int,
                                   titles: list[str] | None = None) -> Engagement:
    """A source answering how much human attention the incident took."""
    def engagement_for(dont_care_incident_id: str) -> EngagementAnswer | None:
        return EngagementAnswer(minutes=minutes,
                                responders=responders,
                                titles=titles or [])

    return engagement_for


def an_engagement_source_reporting_each(engaged: list[EngagedResponder]) -> Engagement:
    """A source answering the response per person, and the total beside it.

    The total is summed here rather than stated independently, because a source
    whose two answers disagree is a case about that source and not about this
    document.
    """
    def engagement_for(dont_care_incident_id: str) -> EngagementAnswer | None:
        return an_engagement_of(engaged)

    return engagement_for


def an_engagement_source_that_cannot_answer() -> Engagement:
    def engagement_for(dont_care_incident_id: str) -> EngagementAnswer | None:
        return None

    return engagement_for


def an_engagement_of(engaged: list[EngagedResponder]) -> EngagementAnswer:
    """One incident's response, summed from the people who gave it."""
    return EngagementAnswer(
        minutes=sum(responder.minutes for responder in engaged),
        responders=len(engaged),
        titles=[responder.job_title for responder in engaged
                if responder.job_title is not None],
        engaged=engaged
    )


def a_band_source_pricing(bands: Mapping[str, PayBand]) -> PayBands:
    def pay_bands() -> Mapping[str, PayBand] | None:
        return bands

    return pay_bands


def a_band_source_pricing_nobody() -> PayBands:
    """An empty band table, for a test whose responders are never priced.

    Empty rather than unreadable: where nothing engages a responder holding a
    title there is nothing to price and no absence to apologise for, and the
    document says nothing about pay in either direction.
    """
    return a_band_source_pricing({})


def a_band_source_that_cannot_answer() -> PayBands:
    def pay_bands() -> Mapping[str, PayBand] | None:
        return None

    return pay_bands


def metrics_showing_a_rise() -> Metrics:
    """Calm minutes before the incident, departed minutes inside it."""
    return metrics_showing_error_rates(
        baseline=DONT_CARE_BASELINE_ERROR_RATE,
        during=DONT_CARE_ERROR_RATE_DURING_THE_INCIDENT)


def metrics_showing_error_rates(baseline: float, during: float) -> Metrics:
    """A window whose rise is exactly `during - baseline`.

    The window the agent asks for is its own business - what this fixes is what
    it finds there.
    """
    def metrics_between(dont_care_start: datetime,
                        dont_care_end: datetime) -> list[MetricBucket]:
        return [
            a_bucket(at=ONSET - timedelta(minutes=1), error_rate=baseline),
            a_bucket(at=ONSET + timedelta(minutes=5), error_rate=during),
            a_bucket(at=ENDED_AT - timedelta(minutes=1), error_rate=during)
        ]

    return metrics_between


def metrics_that_answer_with_nothing() -> Metrics:
    def metrics_between(dont_care_start: datetime,
                        dont_care_end: datetime) -> list[MetricBucket]:
        return []

    return metrics_between


def metrics_recording_the_window_into(
        windows: Kept[tuple[datetime, datetime]]) -> Metrics:
    def metrics_between(window_start: datetime,
                        window_end: datetime) -> list[MetricBucket]:
        windows.take((window_start, window_end))

        return []

    return metrics_between


def a_bucket(at: datetime, error_rate: float) -> MetricBucket:
    return MetricBucket(
        bucket_id=at.strftime("%Y-%m-%dT%H:%M"),
        error_rate=error_rate,
        p50_ms=20,
        p95_ms=40,
        request_volume=1_000
    )


def an_answer(root_cause: str = "dont care",
              executive_summary: str = "dont care",
              assumptions: list[str] | None = None) -> dict[str, Any]:
    """The arguments of a submission that would be accepted as it stands."""
    return {
        ROOT_CAUSE_FIELD: root_cause,
        EXECUTIVE_SUMMARY_FIELD: executive_summary,
        ASSUMPTIONS_FIELD: assumptions if assumptions is not None else []
    }


def an_answer_without(field: str) -> dict[str, Any]:
    answer = an_answer()
    del answer[field]

    return answer


def a_model_answering(root_cause: str = "dont care",
                      executive_summary: str = "dont care",
                      assumptions: list[str] | None = None) -> LLMClient:
    """A model that answers, once, by calling the tool it was offered.

    It asserts nothing about the prompt - that is `test_prompting`'s subject -
    but it does insist on being given a tool to call, because an agent that
    asked for a document in prose would pass against a double that happily
    answered in either shape.
    """
    return a_model_answering_in_turn(
        an_answer(root_cause, executive_summary, assumptions))


def a_model_answering_in_turn(*answers: dict[str, Any],
                              recording_into: Kept[Transcript] | None = None,
                              offered_tools: Kept[list[ToolDefinition]] | None = None
                              ) -> LLMClient:
    """Answers each call from the list in turn, keeping what it was asked.

    A model that ran out of answers has been called more times than the test
    allows for, which is itself a failure - so it says so rather than repeating
    its last one, where an extra call would look like a pass.
    """
    class InTurn:
        def __init__(self) -> None:
            self._remaining = list(answers)

        def converse(self,
                     transcript: Transcript,
                     tools: list[ToolDefinition],
                     max_tokens: int = 4096) -> Turn:
            assert tools, "the postmortem must ask for a structured answer"

            if recording_into is not None:
                recording_into.take(transcript)
            if offered_tools is not None:
                offered_tools.take(tools)

            if not self._remaining:
                raise AssertionError(
                    "the model was called more times than the test expected")

            return a_submission_of(self._remaining.pop(0), tools[0].name)

    return InTurn()


def a_model_answering_in_prose() -> LLMClient:
    """A model that ignored the tool it was offered and wrote a paragraph."""
    return a_model_answering_in_prose_then()


def a_model_answering_in_prose_then(*answers: dict[str, Any],
                                    recording_into: Kept[Transcript] | None = None
                                    ) -> LLMClient:
    """Writes a paragraph first, then whatever it was given - or another one.

    A model that ignored the tool it was offered. It answered, and answered
    uselessly: nothing in a paragraph can be read into a field.
    """
    class ProseFirst:
        def __init__(self) -> None:
            self._still_to_come = list(answers)
            self._has_written_prose = False

        def converse(self,
                     transcript: Transcript,
                     tools: list[ToolDefinition],
                     max_tokens: int = 4096) -> Turn:
            if recording_into is not None:
                recording_into.take(transcript)

            if not self._has_written_prose:
                self._has_written_prose = True

                return _prose("The incident was caused by a feature flag.")

            if not self._still_to_come:
                return _prose("It was definitely a feature flag.")

            return a_submission_of(self._still_to_come.pop(0), tools[0].name)

    return ProseFirst()


def a_model_calling(tool_name: str,
                    recording_into: Kept[Transcript] | None = None) -> LLMClient:
    """A model that called a tool, and not the one it was offered.

    Its arguments are shaped exactly like a postmortem's on purpose: if the
    call's name were ever ignored, this answer would sail into the document and
    read as a real one.
    """
    class WrongTool:
        def converse(self,
                     transcript: Transcript,
                     tools: list[ToolDefinition],
                     max_tokens: int = 4096) -> Turn:
            if recording_into is not None:
                recording_into.take(transcript)

            return a_submission_of(
                an_answer(root_cause="a root cause from the wrong call",
                          executive_summary="a summary from the wrong call"),
                tool_name)

    return WrongTool()


def a_submission_of(arguments: dict[str, Any], tool_name: str) -> Turn:
    return Turn(
        text="",
        tool_calls=[ToolCall(id="call_1", name=tool_name, arguments=arguments)],
        input_tokens=0,
        output_tokens=0
    )


def _prose(text: str) -> Turn:
    return Turn(text=text, tool_calls=[], input_tokens=0, output_tokens=0)
