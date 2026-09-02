from __future__ import annotations

import copy
from collections.abc import Iterator
from functools import partial
from http import HTTPStatus as HttpStatus
from typing import Any

import anthropic
import httpx
import pytest
from anthropic_double import recordings
from anthropic_double.server import DEFAULT_BASE_URL
from argus_core.config import Settings
from argus_core.llm.adapters.anthropic_adapter import AnthropicLLMClient
from argus_core.llm.client import AnswerTruncated, ModelRefused, TurnPaused
from argus_core.models.tool_definition import ToolDefinition
from argus_core.models.transcript import Ask, Transcript
from argus_core.models.turn import Turn
from argus_testkit.assertions import Assertion, an_error_was_raised
from argus_testkit.scenario import Scenario, attempting

from tests.framework.recordings import RECORDED_TOOL_USE_TURN

# What the model is handed. The double answers from what the test seeded and
# never from what it was asked, so this only has to be a conversation.
DONT_CARE_TRANSCRIPT: Transcript = [Ask(text="dont care what was asked")]


@pytest.fixture
def double() -> Iterator[httpx.Client]:
    with httpx.Client(base_url=DEFAULT_BASE_URL, timeout=30.0) as control:
        control.post("/double-control/reset").raise_for_status()
        yield control
        control.post("/double-control/reset").raise_for_status()


@pytest.fixture
def client() -> AnthropicLLMClient:
    # No API key on purpose: these run from a fresh clone, and the double is
    # the reason that is possible.
    return AnthropicLLMClient(
        Settings(anthropic_api_key="", anthropic_base_url=DEFAULT_BASE_URL)
    )


@pytest.mark.integration
def test_a_refusal_is_not_reported_as_a_malformed_answer(
    double: httpx.Client, client: AnthropicLLMClient
) -> None:
    # A refusal is a complete, well-formed response that declines.
    _the_llm_stopped_due_to_refusale = partial(_the_llm_stopped_due_to, 
                                               double, "refusal")


    Scenario() \
        .given(
            _the_llm_stopped_due_to_refusale()
        ) \
        .when(
            attempting(lambda: client.converse(DONT_CARE_TRANSCRIPT, [_a_tool()]))
        ) \
        .then(
            an_error_was_raised(ModelRefused)
        )


@pytest.mark.integration
def test_a_truncated_response_is_not_reported_as_a_malformed_answer(
    double: httpx.Client, client: AnthropicLLMClient
) -> None:
    _the_llm_stopped_due_to_max_token = partial(_the_llm_stopped_due_to, 
                                                double, "max_tokens")


    Scenario() \
        .given(
            _the_llm_stopped_due_to_max_token()
        ) \
        .when(
            attempting(lambda: client.converse(DONT_CARE_TRANSCRIPT, [_a_tool()]))
        ) \
        .then(
            an_error_was_raised(AnswerTruncated)
        )


@pytest.mark.integration
def test_a_rate_limit_reaches_the_caller_as_the_sdks_own_error(
    double: httpx.Client, client: AnthropicLLMClient
) -> None:
    # Not wrapped: a rate limit is a transport fact, and the SDK already has
    # the right word for it. Wrapping would only hide the retry-after header.
    _the_llm_hit_rate_limit = partial(_llm_returned_status, double, HttpStatus.TOO_MANY_REQUESTS)

    Scenario() \
        .given(
            _the_llm_hit_rate_limit()
        ) \
        .when(
            attempting(lambda: client.converse(DONT_CARE_TRANSCRIPT, [_a_tool()]))
        ) \
        .then(
            an_error_was_raised(anthropic.RateLimitError)
        )




@pytest.mark.integration
def test_a_paused_turn_reaches_the_loop_as_a_pause(
    double: httpx.Client, client: AnthropicLLMClient
) -> None:
    # The third of the taxonomy, and the one no recording has ever carried -
    # which is why it is worth staging. A pause the adapter did not recognise
    # arrives as a turn with no calls, and the loop reads a model that paused as
    # a model that had nothing to say.
    _the_llm_paused = partial(_the_llm_stopped_due_to, double, "pause_turn")

    Scenario() \
        .given(
            _the_llm_paused()
        ) \
        .when(
            attempting(lambda: client.converse(DONT_CARE_TRANSCRIPT, [_a_tool()]))
        ) \
        .then(
            an_error_was_raised(TurnPaused)
        )


@pytest.mark.integration
def test_a_completed_turn_reaches_the_loop_as_the_calls_it_asked_for(
    double: httpx.Client, client: AnthropicLLMClient
) -> None:
    # The path the others are all departures from: a real recorded body,
    # through the real adapter, arriving as something the loop can dispatch on.
    # Which tool it asked for is judgement and belongs to the eval suite; that a
    # tool-use body becomes a turn carrying calls is the adapter's contract.
    _the_llm_answered = partial(_the_llm_answered_from, double, RECORDED_TOOL_USE_TURN)

    Scenario() \
        .given(
            _the_llm_answered()
        ) \
        .when(
            lambda: client.converse(DONT_CARE_TRANSCRIPT, [_a_tool()])
        ) \
        .then(
            _it_asked_for_something()
        )


def _a_tool() -> ToolDefinition:
    return ToolDefinition(
        name="get_logs",
        description="Return the service's log lines for a time window.",
        properties={"window_start": {"type": "string"}},
        required=["window_start"]
    )


def _it_asked_for_something() -> Assertion[Turn]:
    def assertion(turn: Turn) -> bool:
        if not turn.tool_calls:
            raise AssertionError(
                f"Expected the turn to carry the calls it asked for, got [{turn!r}]."
            )

        return True

    return assertion


def _the_llm_answered_from(double: httpx.Client, recording: str) -> None:
    double.post("/double-control/seed", json={"recording": recording, "repeat": None})


def _a_response_that_stopped_for(stop_reason: str) -> dict[str, Any]:
    """A real recorded turn with its stop reason changed, and nothing else.

    Built from a recording rather than written here, so that everything except
    the field under test is a shape Anthropic actually produced. Nothing is
    stripped from the content: the tool calls are what a completed turn is read
    for, and a body without them could not tell the two cases apart.
    """
    body = copy.deepcopy(recordings.load(RECORDED_TOOL_USE_TURN))
    body["stop_reason"] = stop_reason

    return body


def _the_llm_stopped_due_to(double: httpx.Client, reason: str) -> None:
    double.post("/double-control/seed", json={"body": _a_response_that_stopped_for(reason)})


def _llm_returned_status(double: httpx.Client, status: HttpStatus) -> None:
    double.post("/double-control/seed", json={"status": status, "repeat": None})
