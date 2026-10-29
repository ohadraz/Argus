"""A model that could not be reached for now, said in Argus's terms.

The SDK says it with errors of its own - too many requests, overloaded, a server
error, a connection that failed or timed out - and retries them itself first.
What still fails after that reaches a caller that may well be able to go on
without the answer: an order suggested for a chain already written is worth
having, and not worth losing the write-up over. A caller can only decide that
about an error it can name without importing the vendor, so the adapter
translates these into one.

Only these. A request the API rejected as asked - a 400 - is not the model
being unavailable: in a replay it is a recording that no longer matches, and it
has to stay loud. Nor is the account's spending cap, though the API says it as a
429 like any rate limit: it answers the same until somebody raises it, and a
caller told the model is unavailable for now would ask again. Both are said as
rejected instead, and loud all the same.

Either way in the API's own words: the message its body gave. The SDK's display
of the error is a status code and the whole body, and that is what reached the
walk, Slack and the postmortem wherever a step said why it stopped.

A streamed answer can fail after its 200 has arrived, as an error event inside
the stream, and the SDK raises that with the status the response already had -
so it is told by the type the event names, not by a status.
"""

from __future__ import annotations

from unittest.mock import Mock

import anthropic
import httpx2
import pytest
from argus_core.llm import ModelUnavailable, RequestRejected
from argus_core.llm.adapters.anthropic_adapter import AnthropicLLMClient
from argus_core.models.model_policy import LARGEST_UNSTREAMED_ANSWER
from argus_core.models.tool_definition import ToolDefinition
from argus_core.models.transcript import Ask
from argus_testkit import Assertion, Scenario

from argus_core_test.framework.llm import settings_that_reach_no_api

SOME_REQUEST = httpx2.Request("POST", "https://api.invalid/v1/messages")

# What the API's body says a spending cap with, as its rate-limits page gives
# it: a rate limit's type, and a code in the details that tells the two apart.
SOME_WORDS_THE_CAP_IS_SAID_IN = "This request would exceed your organization's spend limit."
A_SPEND_CAP = {"type": "error",
               "error": {"type": "rate_limit_error", "message": SOME_WORDS_THE_CAP_IS_SAID_IN,
                         "details": {"error_code": "enforced_spend_limit_reached"}}}
SOME_WORDS_A_REJECTION_IS_SAID_IN = "messages: at least one message is required"


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
def test_a_request_the_api_rejected_as_asked_is_not_said_as_unavailable() -> None:
    a_bad_request = anthropic.BadRequestError(
        "dont care", response=httpx2.Response(400, request=SOME_REQUEST),
        body=_a_body_saying("invalid_request_error", SOME_WORDS_A_REJECTION_IS_SAID_IN))

    Scenario() \
        .given(
            client := AnthropicLLMClient(settings_that_reach_no_api(),
                                         client=_an_api_failing_with(a_bad_request))
        ) \
        .when(
            lambda: _what_was_raised_by(client)
        ) \
        .then(
            _the_failure_was_rejected_saying(SOME_WORDS_A_REJECTION_IS_SAID_IN, a_bad_request)
        )


@pytest.mark.unit
def test_a_rejection_the_api_gave_no_words_for_is_said_in_the_sdks() -> None:
    # A body with no message - a proxy's page, say - leaves the SDK's own
    # account of the error as the only one there is.
    a_bad_request = anthropic.BadRequestError(
        "some account of a request rejected", response=httpx2.Response(400, request=SOME_REQUEST),
        body=None)

    Scenario() \
        .given(
            client := AnthropicLLMClient(settings_that_reach_no_api(),
                                         client=_an_api_failing_with(a_bad_request))
        ) \
        .when(
            lambda: _what_was_raised_by(client)
        ) \
        .then(
            _the_failure_was_rejected_saying("some account of a request rejected", a_bad_request)
        )


@pytest.mark.unit
def test_a_model_unavailable_for_now_is_said_in_the_apis_words() -> None:
    some_words = "Overloaded"
    overloaded = anthropic.OverloadedError(
        "dont care", response=httpx2.Response(529, request=SOME_REQUEST),
        body=_a_body_saying("overloaded_error", some_words))

    Scenario() \
        .given(
            client := AnthropicLLMClient(settings_that_reach_no_api(),
                                         client=_an_api_failing_with(overloaded))
        ) \
        .when(
            lambda: _what_was_raised_by(client)
        ) \
        .then(
            _the_failure_was_unavailable_saying(some_words)
        )


@pytest.mark.unit
def test_a_spending_cap_is_not_said_as_unavailable() -> None:
    a_spend_cap = anthropic.RateLimitError(
        "dont care", response=httpx2.Response(429, request=SOME_REQUEST), body=A_SPEND_CAP)

    Scenario() \
        .given(
            client := AnthropicLLMClient(settings_that_reach_no_api(),
                                         client=_an_api_failing_with(a_spend_cap))
        ) \
        .when(
            lambda: _what_was_raised_by(client)
        ) \
        .then(
            _the_failure_was_rejected_saying(SOME_WORDS_THE_CAP_IS_SAID_IN, a_spend_cap)
        )


@pytest.mark.unit
def test_a_stream_stopped_by_a_spending_cap_after_it_answered_is_not_said_as_unavailable() -> None:
    a_spend_cap = anthropic.APIStatusError(
        "dont care", response=httpx2.Response(200, request=SOME_REQUEST), body=A_SPEND_CAP)

    Scenario() \
        .given(
            client := AnthropicLLMClient(settings_that_reach_no_api(),
                                         client=_an_api_failing_with(a_spend_cap))
        ) \
        .when(
            lambda: _what_was_raised_by(client, streamed=True)
        ) \
        .then(
            _the_failure_was_rejected_saying(SOME_WORDS_THE_CAP_IS_SAID_IN, a_spend_cap)
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
def test_a_stream_rejected_as_asked_after_it_answered_is_not_said_as_unavailable() -> None:
    failure = _an_error_event_in_a_stream("invalid_request_error",
                                          SOME_WORDS_A_REJECTION_IS_SAID_IN)

    Scenario() \
        .given(
            client := AnthropicLLMClient(settings_that_reach_no_api(),
                                         client=_an_api_failing_with(failure))
        ) \
        .when(
            lambda: _what_was_raised_by(client, streamed=True)
        ) \
        .then(
            _the_failure_was_rejected_saying(SOME_WORDS_A_REJECTION_IS_SAID_IN, failure)
        )


def _a_body_saying(error_type: str, message: str) -> dict[str, object]:
    """An error's body as the API sends it: its type, and what it says."""
    return {"type": "error", "error": {"type": error_type, "message": message}}


def _an_error_event_in_a_stream(error_type: str,
                                message: str = "dont care") -> anthropic.APIStatusError:
    """What the SDK raises for an error event in a stream that answered 200: a
    plain status error carrying the event's body."""
    return anthropic.APIStatusError(
        "dont care",
        response=httpx2.Response(200, request=SOME_REQUEST),
        body=_a_body_saying(error_type, message))


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


def _the_failure_was_unavailable_saying(words: str) -> Assertion[Exception | None]:
    """Unavailable, in the API's words and not the SDK's display of the error."""
    def assertion(raised: Exception | None) -> bool:
        if not isinstance(raised, ModelUnavailable) or not str(raised).endswith(words):
            raise AssertionError(
                f"Expected the turn to raise [ModelUnavailable] ending [{words}], got "
                f"[{raised!r}].")

        return True

    return assertion


def _the_failure_was_rejected_saying(words: str,
                                     cause: Exception) -> Assertion[Exception | None]:
    """Rejected, in the API's own words, with the vendor's error kept as its
    cause for whoever reads the log."""
    def assertion(raised: Exception | None) -> bool:
        if (not isinstance(raised, RequestRejected) or raised.__cause__ is not cause
                or not str(raised).endswith(words)):
            raise AssertionError(
                f"Expected the turn to raise [RequestRejected] ending [{words}] from "
                f"[{cause!r}], got [{raised!r}] from "
                f"[{getattr(raised, '__cause__', None)!r}].")

        return True

    return assertion


def _an_api_failing_with(failure: Exception) -> Mock:
    """An SDK client whose every request fails as `failure` - specced against
    `anthropic.Anthropic`, so a rename of its surface fails here."""
    api = Mock(spec=anthropic.Anthropic)
    api.messages.create.side_effect = failure
    api.messages.stream.side_effect = failure

    return api
