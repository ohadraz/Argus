"""Whether an agent's turn may hold more than one tool call.

An agent whose turn ends the conversation has no use for a second call beside
the first, and one arrived anyway: the postmortem sent its write-up and, in the
same turn, a second submission filled with placeholders. Refusing the pair was
right and cost a whole turn on every walk. Asked for at the API instead, the
second call is never made, so it is never paid for.

Only an agent held to it asks. Every other request stays as it was to the byte,
because a field added to all of them would change what every cached prefix and
every recording was made of, for agents whose parallel reads are the point.

Whether the API *honours* the request is the third party's half and is not
checked against a stand-in here. What is checked is that Argus asks.
"""

from __future__ import annotations

from unittest.mock import Mock

import pytest
from argus_core.llm.adapters.anthropic_adapter import (
    AT_MOST_ONE_TOOL_CALL,
    AnthropicLLMClient,
)
from argus_core.models.model_policy import (
    LARGEST_UNSTREAMED_ANSWER,
    ModelPolicy,
)
from argus_core.models.tool_definition import ToolDefinition
from argus_core.models.transcript import Ask
from argus_core.models.turn import Turn
from argus_testkit import Assertion, Scenario

from argus_core_test.framework.llm import an_api_that_answers, settings_that_reach_no_api


@pytest.mark.unit
def test_an_agent_held_to_one_tool_call_per_turn_asks_for_at_most_one() -> None:
    some_api = an_api_that_answers()
    a_single_shot_agent = AnthropicLLMClient(
        settings_that_reach_no_api(),
        policy=ModelPolicy(one_tool_call_per_turn=True),
        client=some_api
    )
    dont_care_transcript = [Ask(text="dont care what was asked")]

    Scenario() \
        .given(
            a_tool := _a_tool()
        ) \
        .when(
            lambda: a_single_shot_agent.converse(dont_care_transcript, [a_tool])
        ) \
        .then(
            _asked_for_at_most_one_tool_call(some_api)
        )


@pytest.mark.unit
def test_an_agent_not_held_to_one_tool_call_asks_nothing_of_how_many() -> None:
    # Absent rather than set to the API's default: the same meaning, a
    # different request, and a different request is a cache miss and a
    # recording that no longer matches what it answered.
    some_api = an_api_that_answers()
    an_investigating_agent = AnthropicLLMClient(
        settings_that_reach_no_api(), policy=ModelPolicy(), client=some_api
    )
    dont_care_transcript = [Ask(text="dont care what was asked")]

    Scenario() \
        .given(
            a_tool := _a_tool()
        ) \
        .when(
            lambda: an_investigating_agent.converse(dont_care_transcript, [a_tool])
        ) \
        .then(
            _asked_nothing_of_how_many_tool_calls(some_api)
        )


@pytest.mark.unit
def test_an_agent_whose_answers_must_stream_is_held_to_one_tool_call_too() -> None:
    # The request is built once for both ways of asking, so this holds by
    # construction - asserted anyway, because two requests built separately
    # would pass everything above.
    some_api = an_api_that_answers()
    a_streaming_agent = AnthropicLLMClient(
        settings_that_reach_no_api(),
        policy=ModelPolicy(one_tool_call_per_turn=True,
                           max_output_tokens=LARGEST_UNSTREAMED_ANSWER + 1),
        client=some_api
    )
    dont_care_transcript = [Ask(text="dont care what was asked")]

    Scenario() \
        .given(
            a_tool := _a_tool()
        ) \
        .when(
            lambda: a_streaming_agent.converse(dont_care_transcript, [a_tool])
        ) \
        .then(
            _asked_for_at_most_one_tool_call(some_api, streamed=True)
        )


def _asked_for_at_most_one_tool_call(api: Mock, streamed: bool = False) -> Assertion[Turn]:
    def assertion(_: Turn) -> bool:
        asking = api.messages.stream if streamed else api.messages.create
        asked = asking.call_args.kwargs.get("tool_choice")

        if asked != AT_MOST_ONE_TOOL_CALL:
            raise AssertionError(
                f"Expected the turn to ask for {AT_MOST_ONE_TOOL_CALL}, and it "
                f"asked for {asked}.")

        return True

    return assertion


def _asked_nothing_of_how_many_tool_calls(api: Mock) -> Assertion[Turn]:
    def assertion(_: Turn) -> bool:
        asked = api.messages.create.call_args.kwargs

        if "tool_choice" in asked:
            raise AssertionError(
                f"Expected no tool_choice from an agent not held to one tool call, "
                f"and it asked for {asked['tool_choice']}.")

        return True

    return assertion


def _a_tool() -> ToolDefinition:
    return ToolDefinition(
        name="submit_postmortem",
        description="Submit the postmortem.",
        properties={"summary": {"type": "string"}},
        required=["summary"]
    )
