"""A model that could not be reached for now, said in Argus's terms.

The SDK says it with errors of its own - too many requests, overloaded, a server
error, a connection that failed or timed out - and retries them itself first.
What still fails after that reaches a caller that may well be able to go on
without the answer: an order suggested for a chain already written is worth
having, and not worth losing the write-up over. A caller can only decide that
about an error it can name without importing the vendor, so the adapter
translates these into one.

Only these. A request the API refused as asked - a 400 - is not the model
being unavailable: in a replay it is a recording that no longer matches, and it
has to stay loud.

A streamed answer can fail after its 200 has arrived, as an error event inside
the stream, and the SDK raises that with the status the response already had -
so it is told by the type the event names, not by a status.
"""

from __future__ import annotations

from unittest.mock import Mock

import anthropic
import httpx2
import pytest
from argus_core.llm import ModelUnavailable
from argus_core.llm.adapters.anthropic_adapter import AnthropicLLMClient
from argus_core.models.model_policy import LARGEST_UNSTREAMED_ANSWER
from argus_core.models.tool_definition import ToolDefinition
from argus_core.models.transcript import Ask
from argus_testkit import Assertion, Scenario

from argus_core_test.framework.llm import settings_that_reach_no_api

SOME_REQUEST = httpx2.Request("POST", "https://api.invalid/v1/messages")


@pytest.mark.unit
@pytest.mark.parametrize("failure", [
    anthropic.RateLimitError("dont care", response=httpx2.Response(429, request=SOME_REQUEST),
                             body=None),
    anthropic.OverloadedError("dont care", response=httpx2.Response(529, request=SOME_REQUEST),
                              body=None),
    anthropic.InternalServerError("dont care",
                                  response=httpx2.Response(503, request=SOME_REQUEST),
                                  body=None),
    anthropic.APIConnectionError(request=SOME_REQUEST),
    anthropic.APITimeoutError(request=SOME_REQUEST)
], ids=["too-many-requests", "overloaded", "a-server-error", "no-connection", "timed-out"])
def test_a_model_that_could_not_be_reached_for_now_is_said_as_unavailable(
        failure: Exception) -> None:
    Scenario() \
        .given(
            client := AnthropicLLMClient(settings_that_reach_no_api(),
                                         client=_an_api_failing_with(failure))
        ) \
        .when(
            lambda: _what_was_raised_by(client)
        ) \
        .then(
            _the_failure_was_unavailable_for(failure)
        )


@pytest.mark.unit
def test_a_request_the_api_refused_as_asked_is_not_said_as_unavailable() -> None:
    a_bad_request = anthropic.BadRequestError(
        "dont care", response=httpx2.Response(400, request=SOME_REQUEST), body=None)

    Scenario() \
        .given(
            client := AnthropicLLMClient(settings_that_reach_no_api(),
                                         client=_an_api_failing_with(a_bad_request))
        ) \
        .when(
            lambda: _what_was_raised_by(client)
        ) \
        .then(
            _the_failure_was_left_as(a_bad_request)
        )


@pytest.mark.unit
@pytest.mark.parametrize("error_type", ["overloaded_error", "api_error", "rate_limit_error",
                                        "timeout_error"])
def test_a_stream_that_failed_for_now_after_it_answered_is_said_as_unavailable(
        error_type: str) -> None:
    failure = _an_error_event_in_a_stream(error_type)

    Scenario() \
        .given(
            client := AnthropicLLMClient(settings_that_reach_no_api(),
                                         client=_an_api_failing_with(failure))
        ) \
        .when(
            lambda: _what_was_raised_by(client, streamed=True)
        ) \
        .then(
            _the_failure_was_unavailable_for(failure)
        )


@pytest.mark.unit
def test_a_stream_refused_as_asked_after_it_answered_is_not_said_as_unavailable() -> None:
    failure = _an_error_event_in_a_stream("invalid_request_error")

    Scenario() \
        .given(
            client := AnthropicLLMClient(settings_that_reach_no_api(),
                                         client=_an_api_failing_with(failure))
        ) \
        .when(
            lambda: _what_was_raised_by(client, streamed=True)
        ) \
        .then(
            _the_failure_was_left_as(failure)
        )


def _an_error_event_in_a_stream(error_type: str) -> anthropic.APIStatusError:
    """What the SDK raises for an error event in a stream that answered 200: a
    plain status error carrying the event's body."""
    return anthropic.APIStatusError(
        "dont care",
        response=httpx2.Response(200, request=SOME_REQUEST),
        body={"type": "error", "error": {"type": error_type, "message": "dont care"}})


def _what_was_raised_by(client: AnthropicLLMClient,
                        streamed: bool = False) -> Exception | None:
    """Runs the turn and hands back whatever came out of it - returned rather
    than allowed to escape, so what was raised can be read. Streamed where
    asked, by asking for more room than an unstreamed answer may have."""
    dont_care_transcript = [Ask(text="dont care what was asked")]
    dont_care_tool = ToolDefinition(name="dont_care", description="dont care",
                                    properties={}, required=[])

    try:
        client.converse(dont_care_transcript, [dont_care_tool],
                        max_tokens=LARGEST_UNSTREAMED_ANSWER + 1 if streamed else None)
    except Exception as error:
        return error

    return None


def _the_failure_was_unavailable_for(cause: Exception) -> Assertion[Exception | None]:
    """Unavailable, with the vendor's error kept as its cause for whoever reads
    the log."""
    def assertion(raised: Exception | None) -> bool:
        if not isinstance(raised, ModelUnavailable) or raised.__cause__ is not cause:
            raise AssertionError(
                f"Expected the turn to raise [ModelUnavailable] from [{cause!r}], got "
                f"[{raised!r}] from [{getattr(raised, '__cause__', None)!r}].")

        return True

    return assertion


def _the_failure_was_left_as(expected: Exception) -> Assertion[Exception | None]:
    def assertion(raised: Exception | None) -> bool:
        if raised is not expected:
            raise AssertionError(f"Expected the turn to raise [{expected!r}] as it was, "
                                 f"got [{raised!r}].")

        return True

    return assertion


def _an_api_failing_with(failure: Exception) -> Mock:
    """An SDK client whose every request fails as `failure` - specced against
    `anthropic.Anthropic`, so a rename of its surface fails here."""
    api = Mock(spec=anthropic.Anthropic)
    api.messages.create.side_effect = failure
    api.messages.stream.side_effect = failure

    return api
