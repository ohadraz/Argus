"""The model, the judge and the money a synopsis is written with.

Of the money, the synopsis reads only the bands and the working year - so
`some_money` answers the rest with nothing, and a test names only the source it
is about.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from datetime import datetime
from decimal import Decimal
from typing import Any, NamedTuple

from argus_testkit import Kept
from core.llm import LLMClient
from core.models import ToolCall, ToolDefinition, Transcript, Turn
from incident_cost import MoneySources, PayBand, PayBands, RateTable
from postmortem_writing import Flag, Flagging

DONT_CARE_WORKING_YEAR = 2080.0
SOME_CURRENCY = "usd"


def some_money(bands: PayBands | None = None,
               working_hours_a_year: float = DONT_CARE_WORKING_YEAR) -> MoneySources:
    """Every source of money, with the bands answering plainly and the takings
    and rates answering nothing.

    A test names only the source it is about and leaves the others alone, which
    is what makes the failure it describes attributable to the source it named.
    """
    def no_revenue(dont_care_start: datetime,
                   dont_care_end: datetime) -> Mapping[str, Decimal] | None:
        return None

    def no_rates() -> RateTable | None:
        return None

    return MoneySources(
        revenue=no_revenue,
        rates=no_rates,
        bands=bands if bands is not None else a_band_source_pricing({}),
        working_hours_a_year=working_hours_a_year,
        reporting_currency=SOME_CURRENCY
    )


def a_band_source_pricing(bands: Mapping[str, PayBand]) -> PayBands:
    def pay_bands() -> Mapping[str, PayBand] | None:
        return bands

    return pay_bands


def a_band_source_that_cannot_answer() -> PayBands:
    def pay_bands() -> Mapping[str, PayBand] | None:
        return None

    return pay_bands


def a_band_source_counting_reads_into(reads: Kept[None]) -> PayBands:
    """A source pricing nothing, noting each time it is read - whether it was
    read is the question."""
    def pay_bands() -> Mapping[str, PayBand] | None:
        reads.take(None)

        return {}

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
