"""What a model was configured with, what it said, and something to say it.

Three things several of `argus_core`'s LLM suites each built for themselves.
The settings are here because the value is a decision rather than a datum - an
empty key is how a test says "this client was handed its own API and
authenticates with nobody", and a suite that wrote its own would be free to
disagree about what that means.

The SDK stand-in is here for the other reason a helper is worth sharing: it is
a rig rather than a value. Standing in for a vendor's client means both ways of
asking wired up, the context manager the streamed one is reached through, and a
`Message` complete enough for the adapter to translate - and the suites that
need it are the ones asserting *which way* the adapter asked. A stand-in that
answered only one way would decide those tests by omission, which is a thing to
get wrong once rather than once per suite.
"""

from __future__ import annotations

from unittest.mock import MagicMock, Mock

import anthropic
from anthropic.types import Message, TextBlock, Usage
from argus_core.config import LLMSettings
from argus_core.llm.adapters.anthropic_adapter import (
    ASSISTANT_ROLE,
    END_TURN_STOP_REASON,
    MESSAGE_TYPE,
    TEXT_TYPE,
)
from argus_core.models.turn import Turn


def settings_that_reach_no_api() -> LLMSettings:
    """Configuration for a client that has been handed its own API stand-in.

    The key is empty because nothing here authenticates: the SDK client is
    injected, so the one thing `Settings` is still read for is how many
    candidates a verdict may carry.
    """
    return LLMSettings(anthropic_api_key="", anthropic_base_url="")


def a_turn_that_said(said: str) -> Turn:
    """A turn carrying words and nothing else - no tool calls, no real counts.

    The token counts are present but arbitrary: a `Turn` cannot be built
    without them, and no test using this builder is about what anything cost.
    A test that *is* about the counts states them itself.
    """
    dont_care_tokens = 1

    return Turn(
        text=said,
        tool_calls=[],
        input_tokens=dont_care_tokens,
        output_tokens=dont_care_tokens
    )


def an_api_that_answers(said: str = "dont care what it said") -> Mock:
    """An SDK client that completes its turn and records what it was asked.

    Specced against `anthropic.Anthropic` so a rename of the client's own
    surface fails here rather than passing against a mock that would answer to
    anything.

    Answers both ways of asking, because which one the adapter chose is the
    subject of the tests that reach for this and must not be the thing that
    makes them pass. A specced `Mock` cannot be a context manager on its own -
    the protocol is looked up on the type - so the streamed side is a
    `MagicMock` handing back an object with the one method the adapter calls
    on it.
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
