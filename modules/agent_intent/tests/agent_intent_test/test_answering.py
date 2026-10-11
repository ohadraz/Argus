"""A person's question, answered from the incident's record - asked once, and
once more.

The model is given the question exactly as written and the incident's timeline,
one line per event, as the page and the thread say it: when, who, and what. It
is given nothing else, and is held to it - an answer the record does not
support is worse than none, because the person reading it has no way to tell.

The answer is the one field of a tool the model must call, so a reply is never
parsed out of prose. An answer that cannot be used is asked for once more, and
after that there is none: what the person is then told, and who else is, is
`understanding`'s to say.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import pytest
from agent_intent.answering import ANSWER_FIELD, ANSWER_TOOL_NAME, answer
from argus_core import to_iso
from argus_core.llm import LLMClient, ModelDidNotAnswer
from argus_core.models import Ask, ToolCall, ToolDefinition, Transcript, Turn
from argus_narration import NarrationLine
from argus_testkit import Assertion, Kept, Scenario, all_of

SOME_QUESTION = "why did you revert the checkout flag?"
SOME_ANSWER = "The checkout flag was switched on at 12:01, a minute before errors rose."

# What the model is held to - answering from the timeline alone, and saying so
# when the timeline is silent - in words rather than sentences, so the prose
# around them is free to be improved.
WHAT_THE_MODEL_IS_HELD_TO = "only from"
WHAT_IT_SAYS_OF_A_SILENT_RECORD = "does not say"


@pytest.mark.unit
def test_the_answer_the_model_submits_is_the_answer_given() -> None:
    Scenario() \
        .given(a_model := _a_model_answering(_a_submission({ANSWER_FIELD: SOME_ANSWER}))) \
        .when(lambda: answer(SOME_QUESTION, _a_timeline(), a_model)) \
        .then(_it_was_answered(SOME_ANSWER))


@pytest.mark.unit
def test_the_question_reaches_the_model_exactly_as_written() -> None:
    asked: Kept[Transcript] = Kept()

    Scenario() \
        .given(a_model := _a_model_answering(_a_submission({ANSWER_FIELD: SOME_ANSWER}),
                                             recording_into=asked)) \
        .when(lambda: answer(SOME_QUESTION, _a_timeline(), a_model)) \
        .then(_the_model_was_shown(asked, SOME_QUESTION))


@pytest.mark.unit
def test_the_model_is_shown_every_line_of_the_timeline_with_when_and_who() -> None:
    # The account a person could read for themselves, line for line - so an
    # answer is about what Argus recorded, in the words it recorded it in.
    asked: Kept[Transcript] = Kept()
    some_timeline = _a_timeline()

    Scenario() \
        .given(a_model := _a_model_answering(_a_submission({ANSWER_FIELD: SOME_ANSWER}),
                                             recording_into=asked)) \
        .when(lambda: answer(SOME_QUESTION, some_timeline, a_model)) \
        .then(all_of(*(
            _the_model_was_shown(asked, said)
            for line in some_timeline
            for said in (to_iso(line.at), line.who, line.text)
        )))


@pytest.mark.unit
def test_the_model_is_held_to_the_timeline() -> None:
    asked: Kept[Transcript] = Kept()

    Scenario() \
        .given(a_model := _a_model_answering(_a_submission({ANSWER_FIELD: SOME_ANSWER}),
                                             recording_into=asked)) \
        .when(lambda: answer(SOME_QUESTION, _a_timeline(), a_model)) \
        .then(all_of(_the_model_was_shown(asked, WHAT_THE_MODEL_IS_HELD_TO),
                     _the_model_was_shown(asked, WHAT_IT_SAYS_OF_A_SILENT_RECORD)))


@pytest.mark.unit
def test_the_model_is_offered_the_one_tool_to_answer_with() -> None:
    offered: Kept[list[ToolDefinition]] = Kept()

    Scenario() \
        .given(a_model := _a_model_answering(_a_submission({ANSWER_FIELD: SOME_ANSWER}),
                                             offered=offered)) \
        .when(lambda: answer(SOME_QUESTION, _a_timeline(), a_model)) \
        .then(_the_tools_offered_were(offered, [ANSWER_TOOL_NAME]))


@pytest.mark.unit
@pytest.mark.parametrize("unusable", [
    lambda: _prose("The flag was reverted because errors rose."),
    lambda: _a_submission({ANSWER_FIELD: "   "}),
    lambda: _a_submission({}),
    lambda: ModelDidNotAnswer("refused")
], ids=["prose", "blank-answer", "no-answer-field", "no-answer"])
def test_an_unusable_answer_is_asked_for_once_more_and_the_second_is_taken(
        unusable: Callable[[], Turn | Exception]) -> None:
    Scenario() \
        .given(a_model := _a_model_answering(unusable(),
                                             _a_submission({ANSWER_FIELD: SOME_ANSWER}))) \
        .when(lambda: answer(SOME_QUESTION, _a_timeline(), a_model)) \
        .then(_it_was_answered(SOME_ANSWER))


@pytest.mark.unit
def test_two_unusable_answers_leave_the_question_unanswered() -> None:
    # And no third ask - the model that ran out of answers says so if there is.
    Scenario() \
        .given(a_model := _a_model_answering(_prose("Hard to say."),
                                             ModelDidNotAnswer("refused"))) \
        .when(lambda: answer(SOME_QUESTION, _a_timeline(), a_model)) \
        .then(_it_was_answered(None))


def _a_timeline() -> list[NarrationLine]:
    """Two lines of an incident, as narration says them."""
    return [
        NarrationLine(at=datetime(2026, 10, 11, 12, 2, tzinfo=UTC),
                      kind="hypothesis-formed",
                      who="Investigator",
                      text="The checkout flag was switched on a minute before errors rose"),
        NarrationLine(at=datetime(2026, 10, 11, 12, 5, tzinfo=UTC),
                      kind="action-taken",
                      who="Mitigation Agent",
                      text="Reverted the checkout flag")
    ]


def _a_model_answering(*answers: Turn | Exception,
                       recording_into: Kept[Transcript] | None = None,
                       offered: Kept[list[ToolDefinition]] | None = None) -> LLMClient:
    """Answers each call from the list in turn - raising where the answer is an
    error - and keeps what it was asked.

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
            if recording_into is not None:
                recording_into.take(transcript)
            if offered is not None:
                offered.take(tools)

            if not self._remaining:
                raise AssertionError("The model was called more times than the test expected.")

            answered = self._remaining.pop(0)

            if isinstance(answered, Exception):
                raise answered

            return answered

    return InTurn()


def _a_submission(arguments: dict[str, Any]) -> Turn:
    return Turn(text="",
                tool_calls=[ToolCall(id="call_1", name=ANSWER_TOOL_NAME, arguments=arguments)],
                input_tokens=0,
                output_tokens=0)


def _prose(text: str) -> Turn:
    return Turn(text=text, tool_calls=[], input_tokens=0, output_tokens=0)


def _it_was_answered(expected: str | None) -> Assertion[str | None]:
    def assertion(answered: str | None) -> bool:
        if answered != expected:
            raise AssertionError(
                f"Expected the question answered [{expected}], got [{answered}]."
            )

        return True

    return assertion


def _the_model_was_shown(asked: Kept[Transcript], words: str) -> Assertion[object]:
    def assertion(_: object) -> bool:
        shown = "\n".join(entry.text for entry in asked.only() if isinstance(entry, Ask))

        if words not in shown:
            raise AssertionError(
                f"Expected the model to be shown [{words}], and it was shown [{shown}]."
            )

        return True

    return assertion


def _the_tools_offered_were(offered: Kept[list[ToolDefinition]],
                            expected: list[str]) -> Assertion[object]:
    def assertion(_: object) -> bool:
        names = [tool.name for tool in offered.only()]

        if names != expected:
            raise AssertionError(f"Expected the model offered {expected}, got {names}.")

        return True

    return assertion
