"""The Anthropic-backed `LLMClient` - the only place Argus talks to a model.

Everything vendor-shaped lives here: the model id, the request parameters, and
the translation between a conversation Argus is holding and the messages the
API expects. Callers hold an `LLMClient` and pass a `Transcript`; nothing
outside this module knows that Anthropic exists.

The one seam below this file is `Settings.anthropic_base_url`, which points
the SDK somewhere else. That is how the test double is selected, and it is
deliberately the *only* difference between a test run and a real one: the
request parameters, the message rendering and the response parsing below all
still run.
"""

from __future__ import annotations

from typing import Final, cast

import anthropic
from anthropic.types import (
    CacheControlEphemeralParam,
    Message,
    MessageParam,
    OutputConfigParam,
    ThinkingConfigAdaptiveParam,
    ToolParam,
    ToolResultBlockParam,
    ToolUseBlockParam,
)

from argus_core.config import Settings, get_settings
from argus_core.llm.client import (
    AnswerTruncated,
    ModelDidNotAnswer,
    ModelRefused,
    TurnPaused,
)
from argus_core.models.tool_definition import ToolDefinition
from argus_core.models.transcript import (
    Ask,
    Exchange,
    ToolResult,
    ToolResults,
    Transcript,
)
from argus_core.models.turn import ToolCall, Turn

# Anthropic's own vocabulary for the parts of a message. Named here because
# this is the module that reads and writes them - a loop above holds a
# `Transcript` and a `Turn`, and never learns that a tool result is a content
# block or that a refusal is a stop reason.
#
# Public, unlike most of what this module knows, so that nothing has to restate
# them: one declaration of each is one fact about a third party, where a second
# copy is a second opinion that drifts the first time one is corrected. That is
# not an invitation to read them further up - a module comparing a `stop_reason`
# has been handed the wire when it should have been handed the domain.
#
# Named for the field rather than the spelling. `TOOL_USE_TYPE` and
# `TOOL_USE_STOP_REASON` are the same string and different things, and one name
# for both would claim the API promised they move together.
#
# `Final` is load-bearing: the SDK types these fields as `Literal`s, so a bare
# `str` fails on the way in and stops mypy narrowing the content union on the
# way out - compared against a plain variable every block stays every kind.
USER_ROLE: Final = "user"
ASSISTANT_ROLE: Final = "assistant"

TEXT_TYPE: Final = "text"
TOOL_RESULT_TYPE: Final = "tool_result"
TOOL_USE_TYPE: Final = "tool_use"
# Read by nothing here, and named anyway: `to_turn` excludes thinking blocks
# deliberately, and a kind of block this module has decided about belongs in
# the list of kinds it knows. It is also what a test builds a response out of.
THINKING_TYPE: Final = "thinking"
MESSAGE_TYPE: Final = "message"

END_TURN_STOP_REASON: Final = "end_turn"
TOOL_USE_STOP_REASON: Final = "tool_use"

# What separates two text blocks of one turn when they are joined. A newline
# rather than a space: the blocks are paragraphs of one account, and running
# them together would misrepresent where the model paused.
_BETWEEN_WHAT_IT_SAID = "\n"

MODEL = "claude-opus-5"

# Non-streaming, so this stays under the SDK's HTTP timeout. A turn is a short
# thing to say plus the calls it asks for; the tokens go on thinking, which
# this does not cap.
MAX_TOKENS = 16000

# What a turn offers the API to keep, so the next turn does not pay for it
# again. Five minutes, which is the shorter of the two lifetimes and the right
# one here: an investigation's turns follow each other in seconds, and each
# read restarts the clock, so the entry stays warm for as long as the loop is
# running and the longer lifetime would only double the write premium.
#
# Public and shared with the tests that assert on it, like the vocabulary
# above: "ephemeral" is Anthropic's word, and a second spelling of it in a test
# would be a second opinion about a third party rather than a check on this one.
EPHEMERAL_CACHE: Final = CacheControlEphemeralParam(type="ephemeral")

# The stop reasons that mean the model did not finish its turn. Each is its own
# type because they differ in what to do next; anything not listed is a turn
# that ended normally and is read as one.
_STOP_REASON_ERRORS: dict[str, type[ModelDidNotAnswer]] = {
    "refusal": ModelRefused,
    "max_tokens": AnswerTruncated,
    "pause_turn": TurnPaused,
}


def to_messages(transcript: Transcript) -> list[MessageParam]:
    """Renders a conversation Argus is holding as the messages the API expects.

    The whole of what this module knows about transcripts, and the reason
    `Transcript` can stay Argus's own type: a loop appends `Ask`, `Turn` and
    `ToolResults` and never learns that a tool result is a content block with
    an `is_error` flag.

    Public rather than private because it is a pure function with real rules in
    it - which side each entry is attributed to, and that one turn's results
    travel together - and those rules are worth testing without a client, a key
    or a recording.
    """
    return [_a_message_for(exchange) for exchange in transcript]


def to_turn(message: Message) -> Turn:
    """Reads one API response into the shape the loop works in.

    The other direction of `to_messages`, and here for the same reason: turning
    a vendor's payload into Argus's shape is this module's whole job. `Turn`
    itself knows nothing about it, so a module holding one does not depend on
    whoever answered.

    Both halves select by block type rather than by position. A response from a
    thinking model opens with a thinking block, so the first block is the
    model's reasoning far more often than it is the model's answer - and
    reasoning is not narration. It is the model working, frequently revising
    itself, and publishing it as Argus's account of an incident would put
    discarded conclusions in front of a human as though they were held ones.

    Text is joined rather than taken first, because one turn's words arrive as
    however many blocks the API chose to break them into and they are one
    account. Only a real `tool_use` block becomes a call: a model that wrote a
    call into its visible text - which happens when thinking is off - asked for
    nothing, and dispatching it would run something nobody requested.

    Public for the same reason as `to_messages`: the rules above are worth
    testing against a hand-built response, without a client, a key or a
    recording.
    """
    return Turn(
        text=_BETWEEN_WHAT_IT_SAID.join(
            block.text for block in message.content if block.type == TEXT_TYPE
        ),
        tool_calls=[
            ToolCall(id=block.id, name=block.name, arguments=dict(block.input or {}))
            for block in message.content
            if block.type == TOOL_USE_TYPE
        ],
        input_tokens=message.usage.input_tokens,
        output_tokens=message.usage.output_tokens,
        # Both nullable on the SDK's `Usage` and read as zero here: the API
        # omits them where nothing was cached, and "no cache was used" is a
        # measured zero rather than an absence a caller should have to decide
        # about. `input_tokens` is only the uncached remainder once either is
        # non-zero, which is why all three travel together or not at all.
        cache_read_tokens=message.usage.cache_read_input_tokens or 0,
        cache_write_tokens=message.usage.cache_creation_input_tokens or 0
    )


def _a_message_for(exchange: Exchange) -> MessageParam:
    """One entry of a transcript, as the one message it becomes.

    One message per entry, never more: `ToolResults` already holds every
    result of a turn, so the grouping the API requires is carried by the type
    rather than reconstructed here.
    """
    if isinstance(exchange, Ask):
        return {"role": USER_ROLE, "content": exchange.text}

    if isinstance(exchange, ToolResults):
        return {
            "role": USER_ROLE,
            "content": [_a_result_block_for(result) for result in exchange.results],
        }

    return {
        "role": ASSISTANT_ROLE,
        "content": [_a_tool_use_block_for(call) for call in exchange.tool_calls],
    }


def _a_result_block_for(result: ToolResult) -> ToolResultBlockParam:
    """What one tool produced, labelled with the call it answers.

    `is_error` is sent only when the tool actually failed. Marking every result
    would have the model treating each log window it retrieved as something to
    recover from.
    """
    block: ToolResultBlockParam = {
        "type": TOOL_RESULT_TYPE,
        "tool_use_id": result.call_id,
        "content": result.content,
    }
    if result.failed:
        block["is_error"] = True

    return block


def _a_tool_use_block_for(call: ToolCall) -> ToolUseBlockParam:
    """One request the model made, sent back to it as part of its own turn.

    The model's turn has to be replayed for its results to mean anything - a
    result answers a request by id, and an id the conversation never issued
    answers nothing.
    """
    return {
        "type": TOOL_USE_TYPE,
        "id": call.id,
        "name": call.name,
        "input": call.arguments,
    }


# What the SDK is handed when a `base_url` override means nothing is going to
# authenticate against Anthropic. It is a placeholder, and it says so.
_UNUSED_API_KEY = "not-a-real-key-the-base-url-is-overridden"


def _api_key_for(configured_key: str, base_url: str | None) -> str:
    """The key to give the SDK, which refuses to build a request without one.

    An overridden `base_url` means the requests are not going to Anthropic, so
    there is no key to have and requiring one would put an API key in the way
    of a test that never calls the API. A fresh clone has to be able to run the
    integration suite, and it has no key.

    The override is what makes this safe: with no override the configured key
    is passed through untouched, empty or not, and the SDK's own error is the
    right one to see. This never invents credentials for the real API.
    """
    if base_url is not None and not configured_key:
        return _UNUSED_API_KEY
    return configured_key


class AnthropicLLMClient:
    """`LLMClient` backed by the real Anthropic Messages API.

    The client is built once and reused: `messages.create` is stateless, and a
    per-call client would throw away the connection pool for no benefit.
    """

    def __init__(self,
                 settings: Settings | None = None,
                 client: anthropic.Anthropic | None = None) -> None:
        """Builds the SDK client this talks through, unless handed one.

        `client` is the seam a test reaches for when what it is checking is the
        request rather than the answer - the same need `_api_key_for` already
        answers from the other side. Configuration still decides everything
        about a real one; passing a client only says that this one is not.
        """
        resolved = settings if settings is not None else get_settings()
        base_url = resolved.anthropic_base_url or None
        self._client = client if client is not None else anthropic.Anthropic(
            api_key=_api_key_for(resolved.anthropic_api_key, base_url),
            # An empty setting means the real API, which is what the SDK does
            # with `base_url=None`. Passing "" would point it at nothing.
            base_url=base_url,
        )

    def converse(self,
                 transcript: Transcript,
                 tools: list[ToolDefinition],
                 max_tokens: int = MAX_TOKENS) -> Turn:
        """Takes one turn of a conversation in which the model may ask for tools.

        The only way of asking. It hands the model a transcript and a set of
        tools and gets back whatever it wants to do next - which is usually not
        an answer but a request for evidence.

        The loop above calls this once per turn and owns the transcript.
        Deliberately so: what has been asked and answered is the loop's
        business, and a client that remembered it would make two investigations
        share state through this object.

        Adaptive thinking at high effort: the judgement being asked for is
        which evidence would settle the question, which is exactly what gets
        worse without reasoning.

        A turn that is not a turn raises rather than returning: a refusal, a
        truncated answer, or a pause. The three differ in what to do next, so
        each is its own type, and none of them is a `Turn` a loop could
        mistake for progress.
        """
        # `to_wire` answers in Argus's terms - a plain mapping - so that
        # `ToolDefinition` stays a domain model and its callers do not import
        # the SDK to hold one. The shape is the API's, and this is the module
        # that already knows that, so the cast belongs here and nowhere else.
        offered = [cast(ToolParam, tool.to_wire()) for tool in tools]

        answer = self._client.messages.create(
            model=MODEL,
            max_tokens=max_tokens,
            # Asked for at the top level rather than pinned to a block: the API
            # places the breakpoint on the last cacheable block and moves it
            # forward as the transcript grows, which is the shape of this loop -
            # every turn's prefix is the previous turn's entire request. Pinning
            # it would freeze the saving at whatever the first turn sent.
            cache_control=EPHEMERAL_CACHE,
            output_config=OutputConfigParam(effort="high"),
            thinking=ThinkingConfigAdaptiveParam(type="adaptive"),
            tools=offered,
            messages=to_messages(transcript),
        )

        error_type = _STOP_REASON_ERRORS.get(answer.stop_reason or "")
        if error_type is not None:
            raise error_type(
                f"the model did not complete its turn (stop_reason={answer.stop_reason})"
            )

        return to_turn(answer)
