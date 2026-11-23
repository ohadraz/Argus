"""The model, the judge and the sources a synopsis is written with.

The synopsis reads the stored postmortem and, of the postmortem's sources, only
the response per person, the bands and the working year - so `some_sources`
answers the rest with nothing, and a test names only the source it is about.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from datetime import datetime
from decimal import Decimal
from typing import Any, NamedTuple

from argus_testkit import Kept
from core.anomaly import AnomalyThresholds
from core.llm import LLMClient
from core.models import AlertRuleStanding, MetricBucket, ToolCall, ToolDefinition, Transcript, Turn
from incident_cost import EngagedResponder, MoneySources, PayBand, PayBands, RateTable
from postmortem_writing import Engagement, EngagementAnswer, Flag, Flagging, Sources

# Where these cases draw the algorithm's lines - the same numbers the
# environment carries by default. The synopsis never measures, so nothing here
# turns on them.
SOME_THRESHOLDS = AnomalyThresholds(
    deviations_from_baseline=3.0,
    persistence_minutes=2,
    recovery_fraction_of_the_rise=0.8
)

DONT_CARE_ENGAGED_MINUTES = 25
DONT_CARE_RESPONDERS = 2
DONT_CARE_WORKING_YEAR = 2080.0
DONT_CARE_REPORTING_LAG_MINUTES = 0
SOME_CURRENCY = "usd"


def some_sources(engagement: Engagement | None = None,
                 bands: PayBands | None = None,
                 working_hours_a_year: float = DONT_CARE_WORKING_YEAR) -> Sources:
    """Everything the postmortem reads, with the three the synopsis reads again
    answering plainly and the rest answering nothing.

    A test names only the source it is about and leaves the others alone, which
    is what makes the failure it describes attributable to the source it named.
    """
    def no_revenue(dont_care_start: datetime,
                   dont_care_end: datetime) -> Mapping[str, Decimal] | None:
        return None

    def no_rates() -> RateTable | None:
        return None

    def no_metrics(dont_care_start: datetime,
                   dont_care_end: datetime,
                   dont_care_rule: str | None) -> list[MetricBucket]:
        return []

    def no_rule(dont_care_rule: str) -> AlertRuleStanding | None:
        return None

    return Sources(
        money=MoneySources(
            revenue=no_revenue,
            rates=no_rates,
            bands=bands if bands is not None else a_band_source_pricing({}),
            working_hours_a_year=working_hours_a_year,
            reporting_currency=SOME_CURRENCY
        ),
        engagement=engagement if engagement is not None
                   else an_engagement_source_reporting(
                       minutes=DONT_CARE_ENGAGED_MINUTES,
                       responders=DONT_CARE_RESPONDERS),
        metrics=no_metrics,
        thresholds=SOME_THRESHOLDS,
        metrics_reporting_lag_minutes=DONT_CARE_REPORTING_LAG_MINUTES,
        alert_rule=no_rule
    )


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


def a_model_answering_in_turn(*answers: dict[str, Any] | None,
                              recording_into: Kept[Transcript] | None = None,
                              offered_tools: Kept[list[ToolDefinition]] | None = None
                              ) -> LLMClient:
    """Answers each call from the list in turn, keeping what it was asked -
    `None` being a turn that wrote a paragraph instead of calling the tool.

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
                     max_tokens: int | None = None) -> Turn:
            assert tools, "the overview must ask for a structured answer"

            if recording_into is not None:
                recording_into.take(transcript)
            if offered_tools is not None:
                offered_tools.take(tools)

            if not self._remaining:
                raise AssertionError(
                    "The model was called more times than the test expected.")

            answer = self._remaining.pop(0)
            if answer is None:
                return a_prose_turn("The incident was caused by a feature flag.")

            return a_submission_of(answer, tools[0].name)

    return InTurn()


def a_submission_of(arguments: dict[str, Any], tool_name: str) -> Turn:
    return Turn(
        text="",
        tool_calls=[ToolCall(id="call_1", name=tool_name, arguments=arguments)],
        input_tokens=0,
        output_tokens=0
    )


def a_prose_turn(text: str) -> Turn:
    return Turn(text=text, tool_calls=[], input_tokens=0, output_tokens=0)


class Built(NamedTuple):
    """What a grounding was built with."""

    judge: LLMClient | None
    record: str
    rows: frozenset[str]
    scope: Sequence[str]
    incident_id: str
    logger: str
    logged_as: str


class AGrounding:
    """A grounding that keeps what it was built with, every answer it is asked to
    judge and every answer it is asked to log, and flags each answer it judges
    as the next of `flags` says."""

    def __init__(self, flags: Sequence[list[Flag]]) -> None:
        self._flags = list(flags)
        self.built: Kept[Built] = Kept()
        self.judged: Kept[dict[str, str]] = Kept()
        self.logged_answers: Kept[dict[str, str]] = Kept()

    def __call__(self, judge: LLMClient | None, record: str, rows: frozenset[str],
                 scope: Sequence[str], incident_id: str, *, logger: logging.Logger,
                 logged_as: str) -> Flagging:
        self.built.take(Built(judge, record, rows, scope, incident_id, logger.name, logged_as))
        return self

    def flags_on(self, answer: Mapping[str, str]) -> list[Flag]:
        self.judged.take(dict(answer))
        if not self._flags:
            raise AssertionError("The grounding was asked to judge more times than the test "
                                 "expected.")
        return self._flags.pop(0)

    def logged(self, answer: Mapping[str, str]) -> None:
        self.logged_answers.take(dict(answer))


def a_grounding_flagging(*flags: list[Flag]) -> AGrounding:
    """A grounding flagging the first answer it judges with the first of
    `flags`, the second with the second, and so on."""
    return AGrounding(flags)
