"""Every model call Argus makes, as a span and two measurements.

An `LLMClient` that wraps another and reports what passed through it - a
decorator for the reason `RecordedLLMClient` is one, and beside it rather than
instead of it: the replay log stands in for a call, and this tells whoever is
reading a trace what the call was, what it cost and how long it took.

Spelled in OTel's GenAI semantic conventions throughout, because a backend that
knows them draws a model call as one without being told. Two places where the
convention and Anthropic disagree are pinned here rather than left to whoever
reads a dashboard: what counts as an input token, and what a stop is called.

The tracer and meter are an SDK's in-memory pair, handed in where the process's
own would otherwise be taken, so nothing here touches global state.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from argus_core.llm.client import AnswerTruncated, LLMClient
from argus_core.llm.traced_client import TracedLLMClient
from argus_core.models.tool_definition import ToolDefinition
from argus_core.models.transcript import Ask, ToolResult, ToolResults, Transcript
from argus_core.models.turn import ToolCall, Turn
from argus_core.telemetry import (
    ARGUS_AGENT,
    ERROR_TYPE,
    GEN_AI_CLIENT_OPERATION_DURATION,
    GEN_AI_CLIENT_TOKEN_USAGE,
    GEN_AI_INPUT_MESSAGES,
    GEN_AI_OPERATION_NAME,
    GEN_AI_OUTPUT_MESSAGES,
    GEN_AI_PROVIDER_NAME,
    GEN_AI_REQUEST_MAX_TOKENS,
    GEN_AI_REQUEST_MODEL,
    GEN_AI_RESPONSE_FINISH_REASONS,
    GEN_AI_TOKEN_TYPE,
    GEN_AI_USAGE_CACHE_CREATION_INPUT_TOKENS,
    GEN_AI_USAGE_CACHE_READ_INPUT_TOKENS,
    GEN_AI_USAGE_INPUT_TOKENS,
    GEN_AI_USAGE_OUTPUT_TOKENS,
)
from argus_testkit import (
    Assertion,
    Scenario,
    all_of,
    attempting,
    the_answer_was,
    the_same_error_reached_the_caller,
)
from opentelemetry import baggage, context
from opentelemetry.trace import SpanKind, StatusCode

from argus_core_test.framework.llm import a_turn_that_said
from argus_core_test.framework.observing import Observed, attributes_of, observing

SOME_MODEL = "claude-opus-5"
SOME_PROVIDER = "anthropic"
SOME_ROOM = 16_000

DONT_CARE_TRANSCRIPT: Transcript = [Ask(text="dont care what was asked")]


@pytest.mark.unit
def test_a_call_is_a_client_span_named_for_the_operation_and_the_model() -> None:
    # The convention's name, `{operation} {model}`, and its kind: a call out of
    # this process to somebody else's service. The room is the one the call
    # actually got - the client's own, here, since the caller named none.
    Scenario() \
        .given(
            observed := observing()
        ) \
        .when(
            lambda: _a_traced_client(_a_client_that_answers(a_turn_that_said("dont care")),
                                     observed).converse(DONT_CARE_TRANSCRIPT, [])
        ) \
        .then(
            all_of(
                _the_span_is(observed, named=f"chat {SOME_MODEL}", kind=SpanKind.CLIENT),
                _the_span_carries(observed, {
                    GEN_AI_OPERATION_NAME: "chat",
                    GEN_AI_PROVIDER_NAME: SOME_PROVIDER,
                    GEN_AI_REQUEST_MODEL: SOME_MODEL,
                    GEN_AI_REQUEST_MAX_TOKENS: SOME_ROOM
                })
            )
        )


@pytest.mark.unit
def test_every_input_token_is_counted_as_input_cached_ones_included() -> None:
    # Where the convention and Anthropic disagree. Anthropic's input count is
    # the uncached remainder; the convention's is every token that went in,
    # with the cache counts as parts of it. A backend summing a figure that
    # left the cache out would show a cached investigation at a fraction of
    # its size - and the better the caching worked, the smaller it would look.
    some_uncached_input = 22
    some_output = 308
    some_cache_read = 9_479
    some_cache_write = 1_204
    a_turn = Turn(
        text="dont care",
        tool_calls=[],
        input_tokens=some_uncached_input,
        output_tokens=some_output,
        cache_read_tokens=some_cache_read,
        cache_write_tokens=some_cache_write
    )

    Scenario() \
        .given(
            observed := observing()
        ) \
        .when(
            lambda: _a_traced_client(_a_client_that_answers(a_turn), observed)
                .converse(DONT_CARE_TRANSCRIPT, [])
        ) \
        .then(
            _the_span_carries(observed, {
                GEN_AI_USAGE_INPUT_TOKENS: some_uncached_input + some_cache_read + some_cache_write,
                GEN_AI_USAGE_OUTPUT_TOKENS: some_output,
                GEN_AI_USAGE_CACHE_READ_INPUT_TOKENS: some_cache_read,
                GEN_AI_USAGE_CACHE_CREATION_INPUT_TOKENS: some_cache_write
            })
        )


@pytest.mark.unit
def test_a_turn_that_asked_for_a_tool_finished_to_call_it() -> None:
    a_turn_calling_a_tool = Turn(
        text="",
        tool_calls=[ToolCall(id="toolu_01", name="get_logs", arguments={})],
        input_tokens=1,
        output_tokens=1
    )

    Scenario() \
        .given(
            observed := observing()
        ) \
        .when(
            lambda: _a_traced_client(_a_client_that_answers(a_turn_calling_a_tool), observed)
                .converse(DONT_CARE_TRANSCRIPT, [])
        ) \
        .then(
            _the_span_carries(observed, {GEN_AI_RESPONSE_FINISH_REASONS: ("tool_call",)})
        )


@pytest.mark.unit
def test_a_turn_that_only_spoke_finished_by_stopping() -> None:
    Scenario() \
        .given(
            observed := observing()
        ) \
        .when(
            lambda: _a_traced_client(
                _a_client_that_answers(a_turn_that_said("the flag was switched at 22:14")),
                observed
            ).converse(DONT_CARE_TRANSCRIPT, [])
        ) \
        .then(
            _the_span_carries(observed, {GEN_AI_RESPONSE_FINISH_REASONS: ("stop",)})
        )


@pytest.mark.unit
def test_the_conversation_is_on_the_span_in_the_conventions_message_shape() -> None:
    # The whole of it, both ways. Telemetry is what a person debugging a walk
    # reads, and a model's answer read without the question is a guess about
    # why it said what it said.
    a_transcript: Transcript = [
        Ask(text="what caused the error rate to climb at 22:15?"),
        Turn(
            text="checking the logs first",
            tool_calls=[ToolCall(id="toolu_01", name="get_logs",
                                 arguments={"window_start": "22:00"})],
            input_tokens=1,
            output_tokens=1
        ),
        ToolResults(results=[ToolResult(call_id="toolu_01", content="22:14 flag switched")])
    ]
    the_answer = a_turn_that_said("the flag switched at 22:14")

    Scenario() \
        .given(
            observed := observing()
        ) \
        .when(
            lambda: _a_traced_client(_a_client_that_answers(the_answer), observed)
                .converse(a_transcript, [])
        ) \
        .then(
            all_of(
                _the_span_says(observed, GEN_AI_INPUT_MESSAGES, [
                    {"role": "user", "parts": [
                        {"type": "text",
                         "content": "what caused the error rate to climb at 22:15?"}
                    ]},
                    {"role": "assistant", "parts": [
                        {"type": "text", "content": "checking the logs first"},
                        {"type": "tool_call", "id": "toolu_01", "name": "get_logs",
                         "arguments": {"window_start": "22:00"}}
                    ]},
                    {"role": "tool", "parts": [
                        {"type": "tool_call_response", "id": "toolu_01",
                         "response": "22:14 flag switched"}
                    ]}
                ]),
                _the_span_says(observed, GEN_AI_OUTPUT_MESSAGES, [
                    {"role": "assistant",
                     "parts": [{"type": "text", "content": "the flag switched at 22:14"}],
                     "finish_reason": "stop"}
                ])
            )
        )


@pytest.mark.unit
def test_a_call_the_model_did_not_complete_is_an_error_span_carrying_what_it_cost() -> None:
    # A truncated turn generated every token of its cap before it was stopped,
    # and the trace is where somebody looks to find out why a walk cost what
    # it did. The failure still reaches the caller exactly as it was.
    some_truncation = AnswerTruncated(
        "the model ran out of room before finishing its turn",
        billed=Turn(text="", tool_calls=[], input_tokens=3_104, output_tokens=16_000)
    )

    Scenario() \
        .given(
            observed := observing()
        ) \
        .when(
            attempting(
                lambda: _a_traced_client(_a_client_that_fails(some_truncation), observed)
                    .converse(DONT_CARE_TRANSCRIPT, [])
            )
        ) \
        .then(
            all_of(
                the_same_error_reached_the_caller(some_truncation),
                _the_span_failed(observed),
                _the_span_carries(observed, {
                    ERROR_TYPE: "AnswerTruncated",
                    GEN_AI_RESPONSE_FINISH_REASONS: ("length",),
                    GEN_AI_USAGE_OUTPUT_TOKENS: 16_000
                })
            )
        )


@pytest.mark.unit
def test_a_call_is_measured_for_how_long_it_took_and_what_it_cost() -> None:
    # The two metrics the convention gives every model call. Measured on an
    # injected clock, so the duration is exact and the test does not take
    # four seconds to say so.
    some_seconds_taken = 4.82
    a_turn = Turn(text="dont care", tool_calls=[], input_tokens=100, output_tokens=40)

    Scenario() \
        .given(
            observed := observing()
        ) \
        .when(
            lambda: _a_traced_client(_a_client_that_answers(a_turn), observed,
                                     clock=_a_clock_reading(0.0, some_seconds_taken))
                .converse(DONT_CARE_TRANSCRIPT, [])
        ) \
        .then(
            all_of(
                _one_point_of(observed, GEN_AI_CLIENT_OPERATION_DURATION,
                              summing=some_seconds_taken,
                              labelled={GEN_AI_REQUEST_MODEL: SOME_MODEL,
                                        GEN_AI_PROVIDER_NAME: SOME_PROVIDER}),
                _one_point_of(observed, GEN_AI_CLIENT_TOKEN_USAGE,
                              summing=100, labelled={GEN_AI_TOKEN_TYPE: "input"}),
                _one_point_of(observed, GEN_AI_CLIENT_TOKEN_USAGE,
                              summing=40, labelled={GEN_AI_TOKEN_TYPE: "output"})
            )
        )


@pytest.mark.unit
def test_a_call_made_inside_an_agent_says_which_agent_made_it() -> None:
    # The client is built once and handed around, and was never told whose it
    # is. The agent says so in the baggage of its own span, and the call reads
    # it from there - onto the span and onto what was measured.
    Scenario() \
        .given(
            observed := observing()
        ) \
        .when(
            lambda: _inside_the_agent("investigator", lambda: _a_traced_client(
                _a_client_that_answers(a_turn_that_said("dont care")), observed
            ).converse(DONT_CARE_TRANSCRIPT, []))
        ) \
        .then(
            all_of(
                _the_span_carries(observed, {ARGUS_AGENT: "investigator"}),
                _one_point_of(observed, GEN_AI_CLIENT_OPERATION_DURATION,
                              labelled={ARGUS_AGENT: "investigator"})
            )
        )


@pytest.mark.unit
def test_the_answer_reaches_the_caller_untouched() -> None:
    a_turn = a_turn_that_said("checking what changed before it")

    Scenario() \
        .given(
            dont_care_observed := observing()
        ) \
        .when(
            lambda: _a_traced_client(_a_client_that_answers(a_turn), dont_care_observed)
                .converse(DONT_CARE_TRANSCRIPT, [])
        ) \
        .then(
            the_answer_was(a_turn)
        )


class _AClientThatAnswers:
    """An `LLMClient` returning a prepared turn - hand-written, as
    `test_recorded_client.py`'s are, because `create_autospec` does not strip
    `self` from a Protocol's signature."""

    def __init__(self, turn: Turn) -> None:
        self._turn = turn

    def converse(self,
                 transcript: Transcript,
                 tools: list[ToolDefinition],
                 max_tokens: int | None = None) -> Turn:
        return self._turn


class _AClientThatFails:
    def __init__(self, failure: Exception) -> None:
        self._failure = failure

    def converse(self,
                 transcript: Transcript,
                 tools: list[ToolDefinition],
                 max_tokens: int | None = None) -> Turn:
        raise self._failure


def _a_client_that_answers(turn: Turn) -> LLMClient:
    return _AClientThatAnswers(turn)


def _a_client_that_fails(failure: Exception) -> LLMClient:
    return _AClientThatFails(failure)


def _a_clock_reading(*seconds: float) -> Any:
    """A clock that reads each of these in turn, so a duration is exact."""
    readings = iter(seconds)

    def clock() -> float:
        return next(readings)

    return clock


def _a_traced_client(client: LLMClient,
                     observed: Observed,
                     clock: Any = None) -> TracedLLMClient:
    if clock is None:
        return TracedLLMClient(client, SOME_MODEL, SOME_PROVIDER, room=SOME_ROOM,
                               tracer=observed.tracer, meter=observed.meter)

    return TracedLLMClient(client, SOME_MODEL, SOME_PROVIDER, room=SOME_ROOM,
                           tracer=observed.tracer, meter=observed.meter, clock=clock)


def _inside_the_agent(agent: str, call: Any) -> Any:
    """Runs `call` with the agent named in the baggage, as an agent's span leaves it."""
    token = context.attach(baggage.set_baggage(ARGUS_AGENT, agent))

    try:
        return call()
    finally:
        context.detach(token)


def _the_span_is(observed: Observed, named: str, kind: SpanKind) -> Assertion[Any]:
    def assertion(_result: Any) -> bool:
        span = observed.only_span()

        if (span.name, span.kind) != (named, kind):
            raise AssertionError(
                f"Expected a [{kind.name}] span named [{named}], "
                f"got a [{span.kind.name}] span named [{span.name}]."
            )

        return True

    return assertion


def _the_span_carries(observed: Observed, expected: dict[str, Any]) -> Assertion[Any]:
    """That the span holds each of these attributes, and says which it does not."""
    def assertion(_result: Any) -> bool:
        carried = dict(observed.only_span().attributes or {})
        wrong = {
            key: (wanted, carried.get(key))
            for key, wanted in expected.items()
            if carried.get(key) != wanted
        }

        if wrong:
            raise AssertionError(
                f"Expected the span to carry these, and {wrong} differed "
                f"(expected, got) among {carried}."
            )

        return True

    return assertion


def _the_span_says(observed: Observed, attribute: str, expected: Any) -> Assertion[Any]:
    """That a JSON attribute, parsed, is exactly this."""
    def assertion(_result: Any) -> bool:
        said = (observed.only_span().attributes or {}).get(attribute)
        parsed = json.loads(str(said)) if said is not None else None

        if parsed != expected:
            raise AssertionError(
                f"Expected [{attribute}] to say {expected}, and it said {parsed}."
            )

        return True

    return assertion


def _the_span_failed(observed: Observed) -> Assertion[Any]:
    def assertion(_result: Any) -> bool:
        status = observed.only_span().status.status_code

        if status is not StatusCode.ERROR:
            raise AssertionError(f"Expected the span's status to be ERROR, got [{status.name}].")

        return True

    return assertion


def _one_point_of(observed: Observed,
                  metric: str,
                  labelled: dict[str, Any],
                  summing: float | None = None) -> Assertion[Any]:
    """That exactly one point of the metric carries these labels - and, given
    `summing`, that it recorded one value adding up to that."""
    def assertion(_result: Any) -> bool:
        points = observed.points_of(metric)
        matching = [
            point for point in points
            if labelled.items() <= attributes_of(point).items()
        ]

        if len(matching) != 1:
            raise AssertionError(
                f"Expected one point of [{metric}] labelled {labelled}, and there were "
                f"{len(matching)} among {[attributes_of(point) for point in points]}."
            )

        if summing is not None and (matching[0].count, matching[0].sum) != (1, summing):
            raise AssertionError(
                f"Expected [{metric}] to have recorded one value of [{summing}], and it "
                f"recorded {matching[0].count} adding up to [{matching[0].sum}]."
            )

        return True

    return assertion
