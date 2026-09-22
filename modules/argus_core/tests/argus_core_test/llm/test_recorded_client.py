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
untouched, a call passed on exactly as it was made, and a call that produced no
answer recorded all the same.
"""

from __future__ import annotations

from typing import Any, Final

import pytest
from argus_core.llm.client import AnswerTruncated, LLMClient, ModelRefused
from argus_core.llm.recorded_client import RecordedLLMClient
from argus_core.models.tool_definition import ToolDefinition
from argus_core.models.transcript import Ask, Transcript
from argus_core.models.turn import Turn
from argus_core.replay import Replay
from argus_testkit import (
    Assertion,
    Scenario,
    all_of,
    the_answer_was,
    the_same_error_reached_the_caller,
)

from argus_core_test.framework.llm import a_turn_that_said
from argus_core_test.framework.replay import (
    KeptEntries,
    a_recorder_that_keeps_what_it_is_given,
    the_entry_took,
    the_entry_was_recorded_for,
)

SOME_INCIDENT_ID = "3cd00c42-6c21-4209-9d22-8f2f89455386"
SOME_MODEL = "claude-opus-5"

DONT_CARE_TRANSCRIPT: Transcript = [Ask(text="dont care what was asked")]

# What the remembering double below holds before anybody asks it anything.
# `None` is the answer this file asserts - the caller named no room - so it
# cannot also be the state of a double nothing ever called, or a wrapper that
# never passed the call on at all would report exactly the right thing.
NOTHING_HAS_BEEN_ASKED: Final = -1


@pytest.mark.unit
def test_a_conversation_is_recorded_with_what_was_asked_and_what_came_back() -> None:
    # Both halves, because either alone is unreplayable: an answer with no
    # question cannot be re-examined, and a question with no answer is a call
    # somebody has to pay for again to learn anything from.
    a_turn = a_turn_that_said("the error rate climbs at 22:15")

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
    a_turn = a_turn_that_said("checking what changed before it")

    Scenario() \
        .given(
            dont_care_recorder := a_recorder_that_keeps_what_it_is_given()
        ) \
        .when(
            lambda: _a_recorded_client(_a_client_that_answers(a_turn), dont_care_recorder)
                .converse(DONT_CARE_TRANSCRIPT, [_a_tool()])
        ) \
        .then(
            the_answer_was(a_turn)
        )


@pytest.mark.unit
def test_what_the_caller_did_not_name_is_not_named_for_them() -> None:
    # The same claim as the test above, taken in the other direction: nothing
    # about the call changes on the way down either. A default of the
    # wrapper's own is not a convenience but a decision, and it is the one
    # decision nobody above can overrule - the seam a loop holds calls with two
    # arguments, so whatever this signature defaults to is what every call
    # supplies, and every production conversation is recorded.
    #
    # The adapter below reads a supplied figure as the caller's word and asks
    # its policy only when it is handed nothing. So a figure invented here is a
    # per-agent policy that can never take effect: an agent whose answers are
    # whole files asks for the room it was configured with and is given
    # sixteen thousand - under the threshold above which an answer streams, so
    # the streaming path is unreachable and the largest files cannot be
    # emitted at all.
    a_client = _a_client_that_remembers_its_room()

    Scenario() \
        .given(
            dont_care_recorder := a_recorder_that_keeps_what_it_is_given()
        ) \
        .when(
            lambda: _a_recorded_client(a_client, dont_care_recorder)
                .converse(DONT_CARE_TRANSCRIPT, [_a_tool()])
        ) \
        .then(
            _no_room_was_asked_for(a_client)
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
                _a_client_that_answers(a_turn_that_said("dont care what it said")),
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
                the_same_error_reached_the_caller(some_refusal)
            )
        )


@pytest.mark.unit
def test_a_call_that_produced_no_turn_still_records_what_it_cost() -> None:
    # Producing nothing is not the same as costing nothing. A turn stopped at
    # its cap generated every token of that cap before it was stopped, and
    # the budget charges for it - so an entry recording the failure without
    # its counts leaves the incident's reported total lower than the one the
    # loop enforced, which is the disagreement the four-count sum exists to
    # remove.
    #
    # These are also the least replaceable counts in the log. A completed
    # turn's cost can be inferred from the turn; a failure's exists nowhere
    # else once the adapter has raised.
    some_truncation = AnswerTruncated(
        "the model ran out of room before finishing its turn",
        billed=Turn(
            text="",
            tool_calls=[],
            input_tokens=3_104,
            output_tokens=16_000,
            cache_read_tokens=78_211,
            cache_write_tokens=4_096
        )
    )

    Scenario() \
        .given(
            recorded := a_recorder_that_keeps_what_it_is_given()
        ) \
        .when(
            lambda: _what_was_raised_by(
                _a_recorded_client(_a_client_that_fails(some_truncation), recorded)
            )
        ) \
        .then(
            all_of(
                _the_failure_recorded_was(recorded, some_truncation),
                _the_failure_recorded_cost(recorded, some_truncation.billed)
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
                 max_tokens: int | None = None) -> Turn:
        return self._turn


class _AClientThatFails:
    """An `LLMClient` whose model never completed its turn."""

    def __init__(self, failure: Exception) -> None:
        self._failure = failure

    def converse(self,
                 transcript: Transcript,
                 tools: list[ToolDefinition],
                 max_tokens: int | None = None) -> Turn:
        raise self._failure


class _AClientThatRemembersItsRoom:
    """An `LLMClient` that answers nothing in particular and keeps what it was
    asked for.

    Hand-written for the reason the two above are: `LLMClient` is a Protocol,
    and `create_autospec` does not strip `self` from a Protocol's signature,
    which turns every argument assertion into a puzzle.

    `max_tokens` is typed as the adapter types it rather than as the Protocol
    does, because the adapter is what this stands in for. The question being
    asked is what reaches the one implementation that holds a policy, and a
    double unable to hold `None` could not express the answer to it.
    """

    def __init__(self) -> None:
        self.room: int | None = NOTHING_HAS_BEEN_ASKED

    def converse(self,
                 transcript: Transcript,
                 tools: list[ToolDefinition],
                 max_tokens: int | None = None) -> Turn:
        self.room = max_tokens

        return a_turn_that_said("dont care what it said")


def _a_client_that_answers(turn: Turn) -> LLMClient:
    return _AClientThatAnswers(turn)


def _a_client_that_fails(failure: Exception) -> LLMClient:
    return _AClientThatFails(failure)


def _a_client_that_remembers_its_room() -> _AClientThatRemembersItsRoom:
    """Narrowed to itself rather than to `LLMClient`, because what this test
    reads afterwards is the room it was handed, which the Protocol has no
    business carrying."""
    return _AClientThatRemembersItsRoom()


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


def _no_room_was_asked_for(client: _AClientThatRemembersItsRoom) -> Assertion[Any]:
    """That the wrapper passed the caller's silence on as silence.

    Read off the wrapped client rather than off the recorded entry, because
    the entry is what the wrapper wrote down and the defect is what it handed
    on. Those are one line of code apart and they are not one claim: a receipt
    reading sixteen thousand while the adapter was handed nothing would be a
    wrapper that behaved correctly and reported badly, and this should fail
    for the other one.

    `None` rather than any figure, because `None` is what the adapter reads as
    "nobody said" - the only value that leaves the policy the client was built
    with able to decide. Every integer is an answer, this file's own included.
    """
    def assertion(_result: Any) -> bool:
        if client.room is not None:
            raise AssertionError(
                f"Expected the wrapped client to be left to its own policy for room, "
                f"and it was asked for [{client.room}]."
            )

        return True

    return assertion


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


def _the_failure_recorded_cost(recorded: KeptEntries, billed: Turn) -> Assertion[Any]:
    """What a call that produced no turn was charged for producing nothing.

    Under the same four keys a completed turn uses, because the same SQL adds
    them up: `get_tokens_spent` reads the counts out of the stored response,
    and a failure filing them anywhere else would be a spend the incident's
    own total cannot see. That total already has to agree with what the
    budget charged, and since a truncated turn is now charged, a receipt
    without these counts puts the two paths back into disagreement on exactly
    the calls that cost the most and explain the least.
    """
    def assertion(_result: Any) -> bool:
        response = recorded.only().response
        expected = {
            count: getattr(billed, count)
            for count in (
                "input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens"
            )
        }
        wrong = {
            count: (wanted, response.get(count))
            for count, wanted in expected.items()
            if response.get(count) != wanted
        }
        if wrong:
            raise AssertionError(
                f"Expected the entry to record what the call cost, and {wrong} "
                f"differed (expected, got) in {response}."
            )

        return True

    return assertion
