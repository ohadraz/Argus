from __future__ import annotations

from unittest.mock import Mock

import anthropic
import pytest
from anthropic.types import Message, TextBlock, Usage
from argus_core.config import Settings
from argus_core.llm.adapters.anthropic_adapter import (
    ASSISTANT_ROLE,
    END_TURN_STOP_REASON,
    EPHEMERAL_CACHE,
    MESSAGE_TYPE,
    TEXT_TYPE,
    AnthropicLLMClient,
)
from argus_core.models.tool_definition import ToolDefinition
from argus_core.models.transcript import Ask
from argus_core.models.turn import Turn
from argus_testkit import Assertion, Scenario

"""What every turn of an investigation asks the API to keep.

A loop re-sends the whole transcript each turn, so by the end of a walk the
same opening message and the same tool results have been read at full price
five or six times over. One breakpoint turns all but the newest of that into a
cache read at a tenth of the price.

The regression this guards is silent by construction: drop the breakpoint and
every request still succeeds, every suite still passes, and only the bill
changes. Nothing else here would notice.

Whether the API *honours* the breakpoint is the third party's half of the
bargain and cannot be checked against a stand-in - that one lives in
`tests/contract/`, where it is paid for.
"""


@pytest.mark.unit
def test_a_turn_asks_for_what_it_sent_to_be_cached() -> None:
    # The breakpoint is asked for at the top level rather than pinned to a
    # block: the API places it on the last cacheable block and moves it forward
    # as the transcript grows, which is exactly the shape of an investigation -
    # each turn's prefix is the previous turn's whole request.
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
            _the_request_asked_to_cache(some_api)
        )


def _the_request_asked_to_cache(api: Mock) -> Assertion[Turn]:
    """That the turn just taken offered its prefix to the cache.

    Asserted against the call rather than the answer, because the saving is
    made on the way out. A turn that came back correctly and paid full price
    for it is the failure this exists to catch, and it looks identical from
    the answer's side.
    """
    def assertion(_: Turn) -> bool:
        asked_for = api.messages.create.call_args.kwargs.get("cache_control")

        if asked_for != EPHEMERAL_CACHE:
            raise AssertionError(
                f"Expected the turn to ask for {EPHEMERAL_CACHE}, got {asked_for}."
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


def _settings_that_reach_no_api() -> Settings:
    """Configuration for a client that has been handed its own API stand-in.

    The key is empty because nothing here authenticates: the SDK client is
    injected, so the one thing `Settings` is still read for is how many
    candidates a verdict may carry.
    """
    return Settings(anthropic_api_key="")


def _an_api_that_answers(said: str = "dont care what it said") -> Mock:
    """An SDK client that completes its turn and records what it was asked.

    Specced against `anthropic.Anthropic` so a rename of the client's own
    surface fails here rather than passing against a mock that would answer to
    anything.
    """
    dont_care_input_tokens = 1
    dont_care_output_tokens = 1

    api = Mock(spec=anthropic.Anthropic)
    api.messages.create.return_value = Message(
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

    return api
