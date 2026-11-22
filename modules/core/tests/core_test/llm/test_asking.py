"""One question put to a model until it gives a usable answer, or a set number
of times.

The intent reader asks two such questions - what a person meant, and the answer
to what they asked - and each was its own copy of the same loop: ask, read the
one tool the answer comes in, and ask the same thing again where nothing usable
came back. What counts as usable is the caller's, so it is handed in. What a
failure to answer is, and when to stop, is said once here.

The same question each time, word for word: a retry that changed the asking
would be a different question, and a recorded answer replayed against it would
no longer be the answer to what was asked.
"""

from __future__ import annotations

import pytest
from argus_testkit import (
    Assertion,
    Kept,
    Scenario,
    all_of,
    attempting,
    the_answer_was,
    the_same_error_reached_the_caller,
)
from core.llm import LLMClient, ModelRefused, ModelUnavailable, ask_until_answered, the_call
from core.models import Ask, ToolCall, ToolDefinition, Transcript, Turn

SOME_FIELD = "answer"
SOME_TOOL = ToolDefinition(name="submit_answer", description="Submit your answer.",
                           properties={SOME_FIELD: {"type": "string"}}, required=[SOME_FIELD])
SOME_QUESTION: Transcript = [Ask(text="What did the person mean?")]
SOME_ATTEMPTS = 2
SOME_ANSWER = "resolve"
SOME_OTHER_ANSWER = "question"
# An answer the model holds for an ask beyond the attempts, which it must never
# be given the chance to send.
AN_ANSWER_NEVER_ASKED_FOR = "asked once too often"


@pytest.mark.unit
def test_the_first_usable_answer_is_the_answer_and_nothing_more_is_asked() -> None:
    # A model asked again would be a model that answered twice: the test's
    # model has one answer, and says so if asked for a second.
    Scenario() \
        .given(a_model := _a_model_answering(_an_answer(SOME_ANSWER))) \
        .when(lambda: ask_until_answered(a_model, SOME_QUESTION, [SOME_TOOL], _the_answer_in,
                                         attempts=SOME_ATTEMPTS)) \
        .then(the_answer_was(SOME_ANSWER))


@pytest.mark.unit
def test_an_unusable_answer_is_asked_for_again_and_the_next_usable_one_taken() -> None:
    Scenario() \
        .given(a_model := _a_model_answering(_a_reply_in_prose(),
                                             _an_answer(SOME_OTHER_ANSWER))) \
        .when(lambda: ask_until_answered(a_model, SOME_QUESTION, [SOME_TOOL], _the_answer_in,
                                         attempts=SOME_ATTEMPTS)) \
        .then(the_answer_was(SOME_OTHER_ANSWER))


@pytest.mark.unit
def test_a_model_that_did_not_answer_is_asked_again() -> None:
    # A refusal, a truncated answer or a paused turn is a turn with no answer
    # in it, and is asked again as one.
    Scenario() \
        .given(a_model := _a_model_answering(_a_refusal(), _an_answer(SOME_OTHER_ANSWER))) \
        .when(lambda: ask_until_answered(a_model, SOME_QUESTION, [SOME_TOOL], _the_answer_in,
                                         attempts=SOME_ATTEMPTS)) \
        .then(the_answer_was(SOME_OTHER_ANSWER))


@pytest.mark.unit
def test_no_usable_answer_in_every_attempt_is_no_answer_and_no_more_is_asked() -> None:
    # The model has an answer left for a third ask, and is never given it: a
    # caller that reads messages in order holds up every one behind this one
    # for as long as it keeps asking.
    Scenario() \
        .given(a_model := _a_model_answering(_a_reply_in_prose(), _a_refusal(),
                                             _an_answer(AN_ANSWER_NEVER_ASKED_FOR))) \
        .when(lambda: ask_until_answered(a_model, SOME_QUESTION, [SOME_TOOL], _the_answer_in,
                                         attempts=SOME_ATTEMPTS)) \
        .then(the_answer_was(None))


@pytest.mark.unit
def test_every_attempt_asks_the_same_question_with_the_same_tools() -> None:
    asked: Kept[Transcript] = Kept()
    offered: Kept[list[ToolDefinition]] = Kept()

    Scenario() \
        .given(a_model := _a_model_answering(_a_reply_in_prose(), _an_answer(SOME_ANSWER),
                                             asked=asked, offered=offered)) \
        .when(lambda: ask_until_answered(a_model, SOME_QUESTION, [SOME_TOOL], _the_answer_in,
                                         attempts=SOME_ATTEMPTS)) \
        .then(all_of(_each_was(asked, SOME_QUESTION, times=SOME_ATTEMPTS),
                     _each_was(offered, [SOME_TOOL], times=SOME_ATTEMPTS)))


@pytest.mark.unit
def test_a_model_that_could_not_be_reached_is_not_asked_again() -> None:
    # Unreachable is not unanswered: it is the provider, not the question, and
    # it reaches the caller as it was raised.
    dont_care_reason = "dont-care outage"
    some_outage = ModelUnavailable(dont_care_reason)

    Scenario() \
        .given(a_model := _a_model_answering(some_outage, _an_answer(AN_ANSWER_NEVER_ASKED_FOR))) \
        .when(attempting(lambda: ask_until_answered(a_model, SOME_QUESTION, [SOME_TOOL],
                                                    _the_answer_in, attempts=SOME_ATTEMPTS))) \
        .then(the_same_error_reached_the_caller(some_outage))


def _the_answer_in(turn: Turn) -> str | None:
    """The caller's reading: the answer the turn submitted, or None."""
    answering = the_call(turn, SOME_TOOL.name)

    return None if answering is None else str(answering.arguments[SOME_FIELD])


def _a_model_answering(*answers: Turn | Exception,
                       asked: Kept[Transcript] | None = None,
                       offered: Kept[list[ToolDefinition]] | None = None) -> LLMClient:
    """Answers each call from the list in turn - raising where the answer is an
    error - and keeps what it was asked. Asked more times than it has answers,
    it fails the test rather than repeating its last one."""
    class InTurn:
        def __init__(self) -> None:
            self._remaining = list(answers)

        def converse(self,
                     transcript: Transcript,
                     tools: list[ToolDefinition],
                     max_tokens: int | None = None) -> Turn:
            if asked is not None:
                asked.take(transcript)
            if offered is not None:
                offered.take(tools)

            if not self._remaining:
                raise AssertionError("The model was called more times than the test expected.")

            answer = self._remaining.pop(0)

            if isinstance(answer, Exception):
                raise answer

            return answer

    return InTurn()


def _an_answer(answer: str) -> Turn:
    dont_care_call_id = "dont-care-call-id"
    dont_care_tokens = 0

    return Turn(text="",
                tool_calls=[ToolCall(id=dont_care_call_id, name=SOME_TOOL.name,
                                     arguments={SOME_FIELD: answer})],
                input_tokens=dont_care_tokens, output_tokens=dont_care_tokens)


def _a_reply_in_prose() -> Turn:
    dont_care_prose = "dont-care prose"
    dont_care_tokens = 0

    return Turn(text=dont_care_prose, tool_calls=[], input_tokens=dont_care_tokens,
                output_tokens=dont_care_tokens)


def _a_refusal() -> ModelRefused:
    dont_care_reason = "dont-care refusal"

    return ModelRefused(dont_care_reason)


def _each_was[T](kept: Kept[T], expected: T, *, times: int) -> Assertion[object]:
    def assertion(_: object) -> bool:
        if kept.taken != [expected] * times:
            raise AssertionError(
                f"Expected the model asked {times} times with [{expected}] each time; "
                f"it was asked with {kept.taken}.")

        return True

    return assertion
