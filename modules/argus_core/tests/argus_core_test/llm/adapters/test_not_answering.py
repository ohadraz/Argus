"""What a turn that did not answer carries back with it.

The counts are the point. A turn stopped at its cap generated every token of
that cap and was billed for all of them, and a refusal is a complete response
charged as one - so a failure that came back empty-handed did not come back
free. The adapter is the only place that ever sees those numbers: the SDK
reports them on a response this module then declines to return, and anything
not read here is gone.

The regression this guards is the expensive kind of silent. Drop the counts
and every request still succeeds, every suite still passes, and only a loop
retrying on a bound that cannot move notices - by not stopping.
"""

from __future__ import annotations

from unittest.mock import Mock

import anthropic
import pytest
from anthropic.types import Message, StopReason, TextBlock, Usage
from argus_core.config import LLMSettings
from argus_core.llm import AnswerTruncated, ModelDidNotAnswer, ModelRefused
from argus_core.llm.adapters.anthropic_adapter import (
    ASSISTANT_ROLE,
    MESSAGE_TYPE,
    REFUSAL_STOP_REASON,
    TEXT_TYPE,
    TRUNCATED_STOP_REASON,
    AnthropicLLMClient,
)
from argus_core.models.tool_definition import ToolDefinition
from argus_core.models.transcript import Ask
from argus_testkit import Assertion, Scenario, all_of


@pytest.mark.unit
def test_a_turn_stopped_at_its_cap_carries_what_it_was_billed() -> None:
    # Every count, because the prompt is not billed at one rate: the cached
    # halves are most of what a turn of an investigation sends, and a failure
    # reporting only the uncached remainder understates itself exactly where
    # the caching worked. The output count is the cap itself - that is what
    # running out of room means.
    some_input_tokens = 3_104
    some_output_tokens = 16_000
    some_cache_read_tokens = 78_211
    some_cache_write_tokens = 4_096
    an_api = _an_api_that_stops_at(
        TRUNCATED_STOP_REASON,
        input_tokens=some_input_tokens,
        output_tokens=some_output_tokens,
        cache_read_tokens=some_cache_read_tokens,
        cache_write_tokens=some_cache_write_tokens
    )

    Scenario() \
        .given(
            client := AnthropicLLMClient(_settings_that_reach_no_api(), client=an_api)
        ) \
        .when(
            lambda: _what_was_raised_by(client)
        ) \
        .then(
            all_of(
                _the_failure_was(AnswerTruncated),
                _the_failure_was_billed(
                    input_tokens=some_input_tokens,
                    output_tokens=some_output_tokens,
                    cache_read_tokens=some_cache_read_tokens,
                    cache_write_tokens=some_cache_write_tokens
                )
            )
        )


@pytest.mark.unit
def test_a_refusal_carries_what_it_was_billed_too() -> None:
    # A refusal is a finished response that says no, and it is charged like
    # any other. Asserted separately from the turn above because the two are
    # raised as different types and a fix attaching the counts to one of them
    # would leave the other free.
    some_input_tokens = 2_890
    some_output_tokens = 141
    an_api = _an_api_that_stops_at(
        REFUSAL_STOP_REASON,
        input_tokens=some_input_tokens,
        output_tokens=some_output_tokens
    )

    Scenario() \
        .given(
            client := AnthropicLLMClient(_settings_that_reach_no_api(), client=an_api)
        ) \
        .when(
            lambda: _what_was_raised_by(client)
        ) \
        .then(
            all_of(
                _the_failure_was(ModelRefused),
                _the_failure_was_billed(
                    input_tokens=some_input_tokens, output_tokens=some_output_tokens
                )
            )
        )


def _what_was_raised_by(client: AnthropicLLMClient) -> Exception | None:
    """Runs the turn and hands back whatever came out of it.

    Returned rather than allowed to escape, because what the failure carries
    is the subject here - and a `pytest.raises` around the scenario would end
    it before anything could be read off what was raised.
    """
    dont_care_transcript = [Ask(text="dont care what was asked")]

    try:
        client.converse(dont_care_transcript, [_a_tool()])
    except Exception as error:
        return error

    return None


def _the_failure_was(expected: type[ModelDidNotAnswer]) -> Assertion[Exception | None]:
    def assertion(raised: Exception | None) -> bool:
        if not isinstance(raised, expected):
            raise AssertionError(
                f"Expected the turn to raise [{expected.__name__}], got [{raised!r}]."
            )

        return True

    return assertion


def _the_failure_was_billed(input_tokens: int,
                            output_tokens: int,
                            cache_read_tokens: int = 0,
                            cache_write_tokens: int = 0) -> Assertion[Exception | None]:
    """Every count the API reported, on the failure that carried none of it.

    All four named at every call site rather than summed, so a failure says
    which count went missing. A total would pass a turn that lost its cache
    read and gained the same number of output tokens, which is a thing a
    refactor can do and a bill would notice before this did.
    """
    def assertion(raised: Exception | None) -> bool:
        if not isinstance(raised, ModelDidNotAnswer):
            raise AssertionError(f"Expected a failure carrying counts, got [{raised!r}].")

        expected = {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cache_read_tokens": cache_read_tokens,
            "cache_write_tokens": cache_write_tokens
        }
        wrong = {
            count: (wanted, getattr(raised.billed, count))
            for count, wanted in expected.items()
            if getattr(raised.billed, count) != wanted
        }
        if wrong:
            raise AssertionError(
                f"Expected the failure to carry what it was billed, and "
                f"{wrong} differed (expected, got)."
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


def _an_api_that_stops_at(stop_reason: StopReason,
                          input_tokens: int,
                          output_tokens: int,
                          cache_read_tokens: int = 0,
                          cache_write_tokens: int = 0) -> Mock:
    """An SDK client whose turn ends for a reason that is not an answer.

    Specced against `anthropic.Anthropic` so a rename of the client's own
    surface fails here rather than passing against a mock that would answer to
    anything. The content is a text block rather than empty because a
    truncated turn really does carry the part it managed to write - what makes
    it a failure is the stop reason, not an absence.
    """
    api = Mock(spec=anthropic.Anthropic)
    api.messages.create.return_value = Message(
        id="dont_care_id",
        model="dont_care_model",
        role=ASSISTANT_ROLE,
        type=MESSAGE_TYPE,
        stop_reason=stop_reason,
        stop_sequence=None,
        content=[TextBlock(type=TEXT_TYPE, text="as far as it got before")],
        usage=Usage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_input_tokens=cache_read_tokens,
            cache_creation_input_tokens=cache_write_tokens
        )
    )

    return api
