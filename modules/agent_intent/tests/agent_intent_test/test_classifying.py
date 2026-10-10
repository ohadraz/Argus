"""What a person meant, as the model classifies it - asked once, and once more.

One question with five answers, put to the model as a tool it must call. The
person's words go to it exactly as written: a paraphrase on the way in would be
Argus deciding what they meant before asking.

An answer that cannot be used - prose instead of a call, a call naming
something other than the five, or no answer at all - is asked for once more,
and after that the message is left unclassified. Never more than twice,
because the intent agent takes every message in order and a message that is
never classified holds up every message behind it. What an unclassified
message counts as, and who is told, is `understanding`'s to say: only it knows
which incident and which message it was.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from agent_intent.classifying import classify
from agent_intent.prompting import MEANING_FIELD, SUBMIT_TOOL_NAME
from argus_core.llm import LLMClient, ModelDidNotAnswer
from argus_core.models import Ask, Meaning, ToolCall, ToolDefinition, Transcript, Turn
from argus_testkit import Assertion, Kept, Scenario

SOME_WORDS = "rolled the flag back by hand, we're fine now"


@pytest.mark.unit
@pytest.mark.parametrize("meaning", list(Meaning))
def test_the_meaning_the_model_submits_is_the_meaning_classified(meaning: Meaning) -> None:
    Scenario() \
        .given(a_model := _a_model_answering(_a_submission({MEANING_FIELD: str(meaning)}))) \
        .when(lambda: classify(SOME_WORDS, a_model)) \
        .then(_it_was_classified_as(meaning))


@pytest.mark.unit
def test_the_persons_words_reach_the_model_exactly_as_written() -> None:
    asked: Kept[Transcript] = Kept()

    Scenario() \
        .given(a_model := _a_model_answering(_a_submission({MEANING_FIELD: "resolve"}),
                                             recording_into=asked)) \
        .when(lambda: classify(SOME_WORDS, a_model)) \
        .then(_the_model_was_shown(asked, SOME_WORDS))


@pytest.mark.unit
def test_the_model_is_offered_the_one_tool_to_answer_with() -> None:
    offered: Kept[list[ToolDefinition]] = Kept()

    Scenario() \
        .given(a_model := _a_model_answering(_a_submission({MEANING_FIELD: "resolve"}),
                                             offered=offered)) \
        .when(lambda: classify(SOME_WORDS, a_model)) \
        .then(_the_tools_offered_were(offered, [SUBMIT_TOOL_NAME]))


@pytest.mark.unit
@pytest.mark.parametrize("unusable", [
    lambda: _prose("They seem to say it is resolved."),
    lambda: _a_submission({MEANING_FIELD: "a-meaning-nobody-offered"}),
    lambda: _a_submission({}),
    lambda: ModelDidNotAnswer("refused")
], ids=["prose", "unoffered-meaning", "no-meaning", "no-answer"])
def test_an_unusable_answer_is_asked_for_once_more_and_the_second_is_taken(
        unusable: Callable[[], Turn | Exception]) -> None:
    Scenario() \
        .given(a_model := _a_model_answering(unusable(),
                                             _a_submission({MEANING_FIELD: "question"}))) \
        .when(lambda: classify(SOME_WORDS, a_model)) \
        .then(_it_was_classified_as(Meaning.QUESTION))


@pytest.mark.unit
def test_two_unusable_answers_leave_the_message_unclassified() -> None:
    # And no third ask - the model that ran out of answers says so if there is.
    Scenario() \
        .given(a_model := _a_model_answering(_prose("Hard to say."),
                                             ModelDidNotAnswer("refused"))) \
        .when(lambda: classify(SOME_WORDS, a_model)) \
        .then(_it_was_classified_as(None))


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

            answer = self._remaining.pop(0)

            if isinstance(answer, Exception):
                raise answer

            return answer

    return InTurn()


def _a_submission(arguments: dict[str, Any]) -> Turn:
    return Turn(text="",
                tool_calls=[ToolCall(id="call_1", name=SUBMIT_TOOL_NAME, arguments=arguments)],
                input_tokens=0,
                output_tokens=0)


def _prose(text: str) -> Turn:
    return Turn(text=text, tool_calls=[], input_tokens=0, output_tokens=0)


def _it_was_classified_as(expected: Meaning | None) -> Assertion[Meaning | None]:
    def assertion(meaning: Meaning | None) -> bool:
        if meaning is not expected:
            raise AssertionError(
                f"Expected the message classified as [{expected}], got [{meaning}]."
            )

        return True

    return assertion


def _the_model_was_shown(asked: Kept[Transcript], words: str) -> Assertion[object]:
    def assertion(_: object) -> bool:
        shown = "\n".join(entry.text for entry in asked.only() if isinstance(entry, Ask))

        if words not in shown:
            raise AssertionError(
                f"Expected the model to be shown [{words}] exactly, and it was shown "
                f"[{shown}]."
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
