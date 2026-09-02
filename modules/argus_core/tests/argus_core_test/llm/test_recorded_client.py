from __future__ import annotations

from typing import Any

import pytest
from argus_core.llm.client import LLMClient, ModelRefused
from argus_core.llm.recorded_client import RecordedLLMClient
from argus_core.models.tool_definition import ToolDefinition
from argus_core.models.transcript import Ask, Transcript
from argus_core.models.turn import Turn
from argus_core.replay import Replay
from argus_testkit import Assertion, Scenario, all_of

from argus_core_test.framework.replay import (
    KeptEntries,
    a_recorder_that_keeps_what_it_is_given,
    the_entry_took,
    the_entry_was_recorded_for,
)

"""The receipt Argus keeps for every model call it makes (spec §4 principle 6).

An `LLMClient` that wraps another and writes down what passed through it. A
decorator rather than a change to the adapter, for two reasons: the adapter's
job is talking to Anthropic, and a second job in it would be a second reason to
change it; and wrapping the *Protocol* records whatever client Argus is
configured with rather than only the one that exists today.

What it records is Argus's own shapes - a transcript, a turn - not the wire's.
That is the level a replay is wanted at: an eval re-reads what the model was
asked and what it answered, and the JSON the SDK happened to send is neither
more truthful nor more useful for that.

`test_replay.py` holds the seam this uses. Here is only what the wrapper adds:
the payloads, the timing measured around the call, an answer handed back
untouched, and a call that produced no answer recorded all the same.
"""

SOME_INCIDENT_ID = "3cd00c42-6c21-4209-9d22-8f2f89455386"
SOME_MODEL = "claude-opus-5"

DONT_CARE_TRANSCRIPT: Transcript = [Ask(text="dont care what was asked")]


@pytest.mark.unit
def test_a_conversation_is_recorded_with_what_was_asked_and_what_came_back() -> None:
    # Both halves, because either alone is unreplayable: an answer with no
    # question cannot be re-examined, and a question with no answer is a call
    # somebody has to pay for again to learn anything from.
    a_turn = _a_turn_that_said("the error rate climbs at 22:15")

    Scenario() \
        .given(
            recorded := a_recorder_that_keeps_what_it_is_given()
        ) \
        .when(
            lambda: _a_recorded_client(_a_client_that_answers(a_turn), recorded)
                .converse(DONT_CARE_TRANSCRIPT, [_a_tool()])
        ) \
        .then(
            all_of(
                the_entry_was_recorded_for(recorded, SOME_INCIDENT_ID),
                _the_entry_asked(recorded, DONT_CARE_TRANSCRIPT),
                _the_entry_answered(recorded, a_turn)
            )
        )


@pytest.mark.unit
def test_the_answer_reaches_the_caller_untouched() -> None:
    # A decorator that changed the answer would be a participant in the work
    # rather than a record of it, and the loop above would be reasoning about
    # something the model did not say.
    a_turn = _a_turn_that_said("checking what changed before it")

    Scenario() \
        .given(
            dont_care_recorder := a_recorder_that_keeps_what_it_is_given()
        ) \
        .when(
            lambda: _a_recorded_client(_a_client_that_answers(a_turn), dont_care_recorder)
                .converse(DONT_CARE_TRANSCRIPT, [_a_tool()])
        ) \
        .then(
            _the_turn_returned_was(a_turn)
        )


@pytest.mark.unit
def test_a_call_is_timed_around_the_client_it_wraps() -> None:
    # No response carries this: the time a model took is gone the moment it
    # returns, and it is the one number a later reader cannot recover from the
    # payloads. Measured from an injected clock rather than a real one, so the
    # assertion is exact and the test does not take five seconds to say so.
    some_seconds_taken = 4.82
    the_seconds_taken_in_ms = int(some_seconds_taken * 1000)
    a_clock_that_advances = _a_clock_reading(0.0, some_seconds_taken)

    Scenario() \
        .given(
            recorded := a_recorder_that_keeps_what_it_is_given()
        ) \
        .when(
            lambda: _a_recorded_client(
                _a_client_that_answers(_a_turn_that_said("dont care what it said")),
                recorded,
                clock=a_clock_that_advances
            ).converse(DONT_CARE_TRANSCRIPT, [_a_tool()])
        ) \
        .then(
            the_entry_took(recorded, the_seconds_taken_in_ms)
        )


@pytest.mark.unit
def test_a_call_the_model_did_not_complete_is_recorded_too() -> None:
    # The calls most worth having a receipt for. A refusal is charged for and a
    # truncation spends the wall clock for nothing, and both are what an eval
    # asking "why did this run cost what it cost" is looking for. Recording
    # only the answers that arrived would leave those runs unexplained.
    #
    # The failure must also still reach the caller as it was: the loop above
    # distinguishes a refusal from a truncation and does different things about
    # them, so a decorator that swallowed or reshaped one would silently change
    # what the investigation does next.
    some_refusal = ModelRefused("the model did not complete its turn")

    Scenario() \
        .given(
            recorded := a_recorder_that_keeps_what_it_is_given()
        ) \
        .when(
            lambda: _what_was_raised_by(
                _a_recorded_client(_a_client_that_fails(some_refusal), recorded)
            )
        ) \
        .then(
            all_of(
                the_entry_was_recorded_for(recorded, SOME_INCIDENT_ID),
                _the_failure_recorded_was(recorded, some_refusal),
                _the_same_failure_reached_the_caller(some_refusal)
            )
        )


class _AClientThatAnswers:
    """An `LLMClient` that returns a prepared turn and asks nothing of anyone.

    Hand-written rather than autospecced: `LLMClient` is a Protocol, and
    `create_autospec` does not strip `self` from a Protocol's signature, which
    turns every argument assertion into a puzzle.
    """

    def __init__(self, turn: Turn) -> None:
        self._turn = turn

    def converse(self,
                 transcript: Transcript,
                 tools: list[ToolDefinition],
                 max_tokens: int = 1) -> Turn:
        return self._turn


class _AClientThatFails:
    """An `LLMClient` whose model never completed its turn."""

    def __init__(self, failure: Exception) -> None:
        self._failure = failure

    def converse(self,
                 transcript: Transcript,
                 tools: list[ToolDefinition],
                 max_tokens: int = 1) -> Turn:
        raise self._failure


def _a_client_that_answers(turn: Turn) -> LLMClient:
    return _AClientThatAnswers(turn)


def _a_client_that_fails(failure: Exception) -> LLMClient:
    return _AClientThatFails(failure)


def _a_clock_reading(*seconds: float) -> Any:
    """A clock that reads each of these in turn, so a duration is exact."""
    readings = iter(seconds)

    def clock() -> float:
        return next(readings)

    return clock


def _a_recorded_client(client: LLMClient,
                       recorded: KeptEntries,
                       clock: Any = None) -> RecordedLLMClient:
    replay = Replay(SOME_INCIDENT_ID, recorded.take)

    if clock is None:
        return RecordedLLMClient(client, replay, target=SOME_MODEL)

    return RecordedLLMClient(client, replay, target=SOME_MODEL, clock=clock)


def _a_tool() -> ToolDefinition:
    return ToolDefinition(
        name="get_logs",
        description="Return the service's log lines for a time window.",
        properties={"window_start": {"type": "string"}},
        required=["window_start"]
    )


def _a_turn_that_said(said: str) -> Turn:
    dont_care_tokens = 1

    return Turn(
        text=said,
        tool_calls=[],
        input_tokens=dont_care_tokens,
        output_tokens=dont_care_tokens
    )


def _what_was_raised_by(client: RecordedLLMClient) -> Exception | None:
    """Runs the call and hands back whatever came out of it.

    The failure is returned rather than allowed to escape, because the
    assertions are about the record it left behind as much as about itself -
    and a `pytest.raises` around the scenario would end it before the recorder
    could be read.
    """
    try:
        client.converse(DONT_CARE_TRANSCRIPT, [_a_tool()])
    except Exception as error:
        return error

    return None


def _the_entry_asked(recorded: KeptEntries, transcript: Transcript) -> Assertion[Any]:
    """The conversation as it stood when the call was made."""
    def assertion(_result: Any) -> bool:
        asked = recorded.only().request.get("transcript")
        expected = [exchange.model_dump(mode="json") for exchange in transcript]

        if asked != expected:
            raise AssertionError(f"Expected the entry to have asked {expected}, got {asked}.")

        return True

    return assertion


def _the_entry_answered(recorded: KeptEntries, turn: Turn) -> Assertion[Any]:
    def assertion(_result: Any) -> bool:
        answered = recorded.only().response
        expected = turn.model_dump(mode="json")

        if answered != expected:
            raise AssertionError(
                f"Expected the entry to have answered {expected}, got {answered}."
            )

        return True

    return assertion


def _the_failure_recorded_was(recorded: KeptEntries, failure: Exception) -> Assertion[Any]:
    """What the record says about a call that produced no turn.

    The type is asserted rather than the message: which of the ways a model can
    fail to answer this was is what a later reader acts on, and the wording is
    the adapter's to change.
    """
    def assertion(_result: Any) -> bool:
        response = recorded.only().response
        expected = type(failure).__name__

        if response.get("error") != expected:
            raise AssertionError(
                f"Expected the entry to record a [{expected}], got {response}."
            )

        return True

    return assertion


def _the_same_failure_reached_the_caller(failure: Exception) -> Assertion[Exception | None]:
    def assertion(raised: Exception | None) -> bool:
        if raised is not failure:
            raise AssertionError(
                f"Expected [{failure!r}] to reach the caller, got [{raised!r}]."
            )

        return True

    return assertion


def _the_turn_returned_was(turn: Turn) -> Assertion[Turn]:
    def assertion(returned: Turn) -> bool:
        if returned != turn:
            raise AssertionError(f"Expected [{turn!r}] back, got [{returned!r}].")

        return True

    return assertion
