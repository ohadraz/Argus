"""An `LLMClient` that makes every model call a span, and measures it.

A decorator, for the reasons `RecordedLLMClient` beside it is one: the adapter's
job is talking to Anthropic, and wrapping the *Protocol* traces whatever client
a deployment is configured with. The two decorators answer different readers.
The replay log stands in for a call so an eval can re-read it without paying
again; this says, to whoever is looking at a trace, what the call was, what it
cost, how long it took and where in the walk it happened.

Spelled in OTel's GenAI semantic conventions (`argus_core.telemetry`), so a
backend that knows them - Langfuse among them - draws a model call as one
without being told. The whole conversation goes on the span: the files are for
debugging, and debugging a model's answer without the question is guessing.

Nothing about the call changes. The answer is handed back as it arrived and a
failure re-raised as it was thrown; with no SDK installed every span and every
instrument here is OTel's no-op, which is what a unit test or a process that
never started telemetry gets.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any

from opentelemetry import baggage, metrics, trace
from opentelemetry.metrics import Meter
from opentelemetry.trace import SpanKind, Status, StatusCode, Tracer
from opentelemetry.util.types import AttributeValue

from argus_core.llm.client import (
    AnswerTruncated,
    LLMClient,
    ModelDidNotAnswer,
    ModelRefused,
)
from argus_core.models.model_policy import DEFAULT_MAX_OUTPUT_TOKENS
from argus_core.models.tool_definition import ToolDefinition
from argus_core.models.transcript import Ask, Exchange, ToolResults, Transcript
from argus_core.models.turn import Turn
from argus_core.telemetry import (
    ARGUS_AGENT,
    ERROR_TYPE,
    FINISH_REASON_CONTENT_FILTER,
    FINISH_REASON_ERROR,
    FINISH_REASON_LENGTH,
    FINISH_REASON_STOP,
    FINISH_REASON_TOOL_CALL,
    GEN_AI_CHAT_OPERATION,
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
    MESSAGE_FINISH_REASON,
    MESSAGE_PARTS,
    MESSAGE_ROLE,
    PART_ARGUMENTS,
    PART_CONTENT,
    PART_ID,
    PART_NAME,
    PART_REASONING,
    PART_RESPONSE,
    PART_TEXT,
    PART_TOOL_CALL,
    PART_TOOL_CALL_RESPONSE,
    PART_TYPE,
    ROLE_ASSISTANT,
    ROLE_TOOL,
    ROLE_USER,
    TOKEN_TYPE_INPUT,
    TOKEN_TYPE_OUTPUT,
    UNIT_SECONDS,
    UNIT_TOKENS,
)

# Reading the clock the duration metric is measured on, so a test can hand
# over one that reads exactly what it says. A `Callable` rather than a Protocol
# because it takes no arguments.
Clock = Callable[[], float]

# The instrumentation scope every span and instrument here is reported under.
_SCOPE = __name__


class TracedLLMClient:
    """Wraps an `LLMClient`, making each call a span and two metric points.

    `model`, `provider` and `room` are supplied rather than asked of the
    client, as `RecordedLLMClient`'s are: the Protocol has none of them to ask
    for, and should not grow them. Which agent a call belongs to is not
    supplied at all - it is read off the baggage the agent's span set, since a
    client is built once and handed around, and was never told whose it is.

    `tracer` and `meter` default to the process's own, which is what makes the
    decorator free to wrap unconditionally: until `argus_telemetry` installs an
    SDK both are no-ops. A monotonic clock, not a wall clock, because what the
    duration metric measures is a duration.
    """

    def __init__(self,
                 client: LLMClient,
                 model: str,
                 provider: str,
                 room: int = DEFAULT_MAX_OUTPUT_TOKENS,
                 tracer: Tracer | None = None,
                 meter: Meter | None = None,
                 clock: Clock = time.monotonic) -> None:
        self._client = client
        self._model = model
        self._provider = provider
        self._room = room
        self._tracer = tracer if tracer is not None else trace.get_tracer(_SCOPE)
        measured_by = meter if meter is not None else metrics.get_meter(_SCOPE)
        self._duration = measured_by.create_histogram(
            GEN_AI_CLIENT_OPERATION_DURATION, unit=UNIT_SECONDS,
            description="How long a model call took, failed calls included."
        )
        self._tokens = measured_by.create_histogram(
            GEN_AI_CLIENT_TOKEN_USAGE, unit=UNIT_TOKENS,
            description="What a model call was billed, by kind of token."
        )
        self._clock = clock

    def converse(self,
                 transcript: Transcript,
                 tools: list[ToolDefinition],
                 max_tokens: int | None = None) -> Turn:
        """Takes one turn through the wrapped client, inside a span of its own.

        `max_tokens` is handed on exactly as it arrived, `None` included - the
        same reasoning as the recorder's: a figure invented here would be a
        policy nobody above could overrule. The span records the room the call
        actually got.
        """
        measured = self._what_every_measurement_carries()

        with self._tracer.start_as_current_span(
            f"{GEN_AI_CHAT_OPERATION} {self._model}",
            kind=SpanKind.CLIENT,
            attributes={
                **measured,
                GEN_AI_REQUEST_MAX_TOKENS: max_tokens if max_tokens is not None else self._room,
                GEN_AI_INPUT_MESSAGES: json.dumps(_messages_of(transcript))
            },
            # Said here rather than left to the SDK, so that the status says
            # which of the ways a model can fail to answer this was.
            set_status_on_exception=False
        ) as span:
            started_at = self._clock()

            try:
                turn = self._client.converse(transcript, tools, max_tokens)
            except Exception as error:
                failed = {**measured, ERROR_TYPE: type(error).__name__}
                span.set_attributes({
                    ERROR_TYPE: type(error).__name__,
                    GEN_AI_RESPONSE_FINISH_REASONS: [_why_it_stopped_short(error)]
                })
                span.set_status(Status(StatusCode.ERROR, str(error)))
                self._duration.record(self._clock() - started_at, failed)

                if isinstance(error, ModelDidNotAnswer):
                    span.set_attributes(_what_it_cost(error.billed))
                    self._count(error.billed, failed)

                raise

            finish_reason = _why_it_stopped(turn)
            span.set_attributes({
                **_what_it_cost(turn),
                GEN_AI_RESPONSE_FINISH_REASONS: [finish_reason],
                GEN_AI_OUTPUT_MESSAGES: json.dumps(
                    [{**_message_of(turn), MESSAGE_FINISH_REASON: finish_reason}]
                )
            })
            self._duration.record(self._clock() - started_at, measured)
            self._count(turn, measured)

            return turn

    def _what_every_measurement_carries(self) -> dict[str, AttributeValue]:
        """The attributes a call's span and both its metric points share.

        The agent only where the baggage names one: a call made outside any
        agent's span - a postmortem written from a script - is still a call,
        and an empty agent would be a value nobody chose.
        """
        attributes: dict[str, AttributeValue] = {
            GEN_AI_OPERATION_NAME: GEN_AI_CHAT_OPERATION,
            GEN_AI_PROVIDER_NAME: self._provider,
            GEN_AI_REQUEST_MODEL: self._model
        }
        agent = baggage.get_baggage(ARGUS_AGENT)

        if agent is not None:
            attributes[ARGUS_AGENT] = str(agent)

        return attributes

    def _count(self, turn: Turn, attributes: dict[str, AttributeValue]) -> None:
        """One token-usage point per kind of token, as the convention defines input."""
        self._tokens.record(_every_input_token(turn),
                            {**attributes, GEN_AI_TOKEN_TYPE: TOKEN_TYPE_INPUT})
        self._tokens.record(turn.output_tokens,
                            {**attributes, GEN_AI_TOKEN_TYPE: TOKEN_TYPE_OUTPUT})


def _every_input_token(turn: Turn) -> int:
    """Input as OTel counts it - cached tokens included - rather than as Anthropic does.

    The provider's `input_tokens` is only the uncached remainder. The
    convention's is every token that went in, with the two cache counts as
    parts of it, and a backend summing the convention's figure would otherwise
    report a cached investigation at a fraction of its size.
    """
    return turn.input_tokens + turn.cache_read_tokens + turn.cache_write_tokens


def _what_it_cost(turn: Turn) -> dict[str, AttributeValue]:
    return {
        GEN_AI_USAGE_INPUT_TOKENS: _every_input_token(turn),
        GEN_AI_USAGE_OUTPUT_TOKENS: turn.output_tokens,
        GEN_AI_USAGE_CACHE_READ_INPUT_TOKENS: turn.cache_read_tokens,
        GEN_AI_USAGE_CACHE_CREATION_INPUT_TOKENS: turn.cache_write_tokens
    }


def _why_it_stopped(turn: Turn) -> str:
    """A completed turn stopped either to call a tool or because it had finished."""
    return FINISH_REASON_TOOL_CALL if turn.tool_calls else FINISH_REASON_STOP


def _why_it_stopped_short(error: Exception) -> str:
    """The convention's reason for each way a model can fail to answer."""
    if isinstance(error, AnswerTruncated):
        return FINISH_REASON_LENGTH

    if isinstance(error, ModelRefused):
        return FINISH_REASON_CONTENT_FILTER

    return FINISH_REASON_ERROR


def _messages_of(transcript: Transcript) -> list[dict[str, Any]]:
    return [_message_of(exchange) for exchange in transcript]


def _message_of(exchange: Exchange) -> dict[str, Any]:
    """One exchange as the GenAI convention spells a message: a role and its parts."""
    if isinstance(exchange, Ask):
        return {MESSAGE_ROLE: ROLE_USER,
                MESSAGE_PARTS: [{PART_TYPE: PART_TEXT, PART_CONTENT: exchange.text}]}

    if isinstance(exchange, ToolResults):
        return {MESSAGE_ROLE: ROLE_TOOL,
                MESSAGE_PARTS: [
                    {PART_TYPE: PART_TOOL_CALL_RESPONSE,
                     PART_ID: result.call_id,
                     PART_RESPONSE: result.content}
                    for result in exchange.results
                ]}

    return {MESSAGE_ROLE: ROLE_ASSISTANT, MESSAGE_PARTS: _parts_of(exchange)}


def _parts_of(turn: Turn) -> list[dict[str, Any]]:
    """What the model said, in the order it said it: thinking, prose, then calls."""
    parts: list[dict[str, Any]] = []

    if turn.reasoning:
        parts.append({PART_TYPE: PART_REASONING, PART_CONTENT: turn.reasoning})

    if turn.text:
        parts.append({PART_TYPE: PART_TEXT, PART_CONTENT: turn.text})

    parts.extend(
        {PART_TYPE: PART_TOOL_CALL,
         PART_ID: call.id,
         PART_NAME: call.name,
         PART_ARGUMENTS: call.arguments}
        for call in turn.tool_calls
    )

    return parts
