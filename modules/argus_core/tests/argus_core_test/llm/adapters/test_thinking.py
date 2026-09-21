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

from unittest.mock import Mock

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
from argus_core.models.tool_definition import ToolDefinition
from argus_core.models.transcript import Ask
from argus_core.models.turn import Turn
from argus_testkit import Assertion, Scenario


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
