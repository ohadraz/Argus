"""That a turn asks to be told what the model was working through.

The counterpart to `to_turn` carrying the reasoning: on this model the
thinking blocks arrive with empty text unless the request asks otherwise, so a
translation that reads them faithfully still reads nothing. Both halves are
needed and neither is visible from the other's side.

The regression this guards is silent in the worst way. Drop the request and
every call still succeeds, every turn still parses, the field is simply always
empty - and an empty reasoning is indistinguishable from a model that happened
not to reason. Nobody notices until someone goes looking for why a wrong
hypothesis looked right, months later, and finds the column blank for every
incident ever recorded.

Free, which is why it is asked for at all. Thinking is billed identically
under every display setting; what changes is only whether Argus is told.
"""

from __future__ import annotations

from unittest.mock import MagicMock, Mock

import anthropic
import pytest
from anthropic.types import Message, TextBlock, Usage
from argus_core.config import LLMSettings
from argus_core.llm.adapters.anthropic_adapter import (
    ASSISTANT_ROLE,
    END_TURN_STOP_REASON,
    MESSAGE_TYPE,
    SUMMARISED_THINKING,
    TEXT_TYPE,
    AnthropicLLMClient,
)
from argus_core.models import LARGEST_UNSTREAMED_ANSWER, Effort, ModelPolicy
from argus_core.models.tool_definition import ToolDefinition
from argus_core.models.transcript import Ask
from argus_core.models.turn import Turn
from argus_testkit import Assertion, Scenario
from argus_testkit.assertions import all_of


@pytest.mark.unit
def test_a_turn_asks_to_be_told_what_the_model_was_working_through() -> None:
    # Asserted against the request rather than the answer, because this is
    # made on the way out. A turn that came back with empty reasoning looks
    # identical whether the model reasoned in silence or was never asked to
    # say so, and only the request can tell the two apart.
    some_api = _an_api_that_answers()
    investigator = AnthropicLLMClient(_settings_that_reach_no_api(), client=some_api)
    dont_care_transcript = [Ask(text="dont care what was asked")]

    Scenario() \
        .given(
            a_tool := _a_tool()
        ) \
        .when(
            lambda: investigator.converse(dont_care_transcript, [a_tool])
        ) \
        .then(
            _the_request_asked_for_the_reasoning(some_api)
        )


@pytest.mark.unit
def test_a_turn_asks_the_model_its_agent_was_given_to_ask() -> None:
    # Per agent, because the agents are not the same shape of work: prose
    # with every figure pre-measured, a tool loop choosing what to read, and
    # whole files of code. One level across the three is wrong for at least
    # one of them, and which one is a thing to measure rather than assert.
    #
    # Bound to the client rather than passed per turn, so the loop still
    # chooses nothing - it holds a `(transcript, tools) -> Turn` and knows of
    # no model, no effort and no client, exactly as before.
    some_policy = ModelPolicy(model="claude-haiku-4-5", effort="low")
    some_api = _an_api_that_answers()
    an_agents_client = AnthropicLLMClient(
        _settings_that_reach_no_api(), policy=some_policy, client=some_api
    )
    dont_care_transcript = [Ask(text="dont care what was asked")]

    Scenario() \
        .given(
            a_tool := _a_tool()
        ) \
        .when(
            lambda: an_agents_client.converse(dont_care_transcript, [a_tool])
        ) \
        .then(
            all_of(
                _the_request_named_the_model(some_api, some_policy.model),
                _the_request_asked_for_effort(some_api, some_policy.effort)
            )
        )


@pytest.mark.unit
def test_an_answer_too_large_to_arrive_at_once_is_streamed() -> None:
    # Not a preference. Above 21,333 the SDK refuses a non-streaming request
    # before it sends one - it expects 128,000 tokens to take an hour and
    # will not let a single response run past ten minutes - so an agent whose
    # answers are whole files cannot ask for the room it needs any other way.
    # The largest file in the Target Service is 21,484 tokens, which is over
    # that line by 151: the cap is not tight for that class of fix, it is
    # impossible, and no retry can help because the same request overflows
    # the same ceiling every time.
    some_api = _an_api_that_answers()
    writing_whole_files = AnthropicLLMClient(
        _settings_that_reach_no_api(),
        policy=ModelPolicy(max_output_tokens=LARGEST_UNSTREAMED_ANSWER + 1),
        client=some_api
    )
    dont_care_transcript = [Ask(text="dont care what was asked")]

    Scenario() \
        .given(
            a_tool := _a_tool()
        ) \
        .when(
            lambda: writing_whole_files.converse(dont_care_transcript, [a_tool])
        ) \
        .then(
            _the_answer_was_streamed(some_api, LARGEST_UNSTREAMED_ANSWER + 1)
        )


@pytest.mark.unit
def test_an_answer_that_fits_is_asked_for_in_one_piece() -> None:
    # The other side of the threshold. Streaming is what the SDK requires
    # above the line, not what anything prefers below it: the same message
    # arrives either way, so an adapter that streamed unconditionally would
    # take on the harder-to-read failure mode for every agent in order to
    # serve the one that needs it.
    some_api = _an_api_that_answers()
    saying_something_short = AnthropicLLMClient(
        _settings_that_reach_no_api(),
        policy=ModelPolicy(max_output_tokens=LARGEST_UNSTREAMED_ANSWER),
        client=some_api
    )
    dont_care_transcript = [Ask(text="dont care what was asked")]

    Scenario() \
        .given(
            a_tool := _a_tool()
        ) \
        .when(
            lambda: saying_something_short.converse(dont_care_transcript, [a_tool])
        ) \
        .then(
            _the_answer_arrived_whole(some_api, LARGEST_UNSTREAMED_ANSWER)
        )


def _the_request_named_the_model(api: Mock, model: str) -> Assertion[Turn]:
    def assertion(_: Turn) -> bool:
        asked = api.messages.create.call_args.kwargs.get("model")

        if asked != model:
            raise AssertionError(f"Expected the turn to ask [{model}], got [{asked}].")

        return True

    return assertion


def _the_request_asked_for_effort(api: Mock, effort: Effort) -> Assertion[Turn]:
    """How hard the model was asked to think, read off the request.

    Off the request rather than the answer, like the breakpoint and the
    thinking display: effort changes what a turn costs and how good it is,
    and both of those look like an ordinary answer from this side. Nothing
    but the call itself records that the wrong one was asked for.
    """
    def assertion(_: Turn) -> bool:
        asked = (api.messages.create.call_args.kwargs.get("output_config") or {}).get("effort")

        if asked != effort:
            raise AssertionError(f"Expected the turn to ask for [{effort}] effort, got [{asked}].")

        return True

    return assertion


def _the_request_asked_for_the_reasoning(api: Mock) -> Assertion[Turn]:
    def assertion(_: Turn) -> bool:
        asked_for = api.messages.create.call_args.kwargs.get("thinking")

        if asked_for != SUMMARISED_THINKING:
            raise AssertionError(
                f"Expected the turn to ask for {SUMMARISED_THINKING}, got {asked_for}."
            )

        return True

    return assertion


def _a_tool() -> ToolDefinition:
    return ToolDefinition(
        name="get_logs",
        description="Return the service's log lines for a time window.",
        properties={"window_start": {"type": "string"}},
        required=["window_start"]
    )


def _settings_that_reach_no_api() -> LLMSettings:
    """Configuration for a client that has been handed its own API stand-in."""
    return LLMSettings(anthropic_api_key="", anthropic_base_url="")


def _an_api_that_answers(said: str = "dont care what it said") -> Mock:
    """An SDK client that completes its turn and records what it was asked.

    Specced against `anthropic.Anthropic` so a rename of the client's own
    surface fails here rather than passing against a mock that would answer to
    anything.

    Answers both ways of asking, because which one the adapter chose is the
    subject of two tests here and must not be the thing that makes them pass.
    A specced `Mock` cannot be a context manager on its own - the protocol is
    looked up on the type - so the streamed side is a `MagicMock` handing back
    an object with the one method the adapter calls on it.
    """
    dont_care_input_tokens = 1
    dont_care_output_tokens = 1

    answered = Message(
        id="dont_care_id",
        model="dont_care_model",
        role=ASSISTANT_ROLE,
        type=MESSAGE_TYPE,
        stop_reason=END_TURN_STOP_REASON,
        stop_sequence=None,
        content=[TextBlock(type=TEXT_TYPE, text=said)],
        usage=Usage(
            input_tokens=dont_care_input_tokens, output_tokens=dont_care_output_tokens
        )
    )

    api = Mock(spec=anthropic.Anthropic)
    api.messages.create.return_value = answered

    streamed = MagicMock()
    streamed.__enter__.return_value.get_final_message.return_value = answered
    api.messages.stream.return_value = streamed

    return api


def _the_answer_was_streamed(api: Mock, max_output_tokens: int) -> Assertion[Turn]:
    """That the room asked for was asked for the only way it can be.

    Both halves matter and neither implies the other. A streamed call with
    the old cap has only the room it always had; an unstreamed call with the
    new one never reaches the API at all, because the SDK refuses it before
    sending - a failure at the first large fix rather than at the first test.
    """
    def assertion(_: Turn) -> bool:
        if not api.messages.stream.called:
            raise AssertionError(
                "Expected an answer this large to be streamed, and it was asked for "
                "in one piece."
            )

        asked = api.messages.stream.call_args.kwargs.get("max_tokens")
        if asked != max_output_tokens:
            raise AssertionError(
                f"Expected room for [{max_output_tokens}] tokens, got [{asked}]."
            )

        return True

    return assertion


def _the_answer_arrived_whole(api: Mock, max_output_tokens: int) -> Assertion[Turn]:
    """That an answer which fits is not streamed anyway.

    Not because streaming would fail - the stand-in the offline suites
    replay through serves either shape now - but because nothing is bought
    by it. The same message arrives, and the simpler request is the one
    whose failures are easier to read.
    """
    def assertion(_: Turn) -> bool:
        if api.messages.stream.called:
            raise AssertionError(
                "Expected an answer this size to be asked for in one piece, and it "
                "was streamed."
            )

        asked = api.messages.create.call_args.kwargs.get("max_tokens")
        if asked != max_output_tokens:
            raise AssertionError(
                f"Expected room for [{max_output_tokens}] tokens, got [{asked}]."
            )

        return True

    return assertion
