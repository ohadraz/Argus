"""The Anthropic-backed `ModelProvider` - the only place Argus talks to a model.

Everything vendor-shaped lives here: the model id, the request parameters, how
Argus's reasoning scale and tool offers are spelled on the wire, how a model's
own slips into its native call syntax are repaired, and the translation between
a conversation Argus is holding and the messages the API expects. Callers hold
an `LLMClient` and pass a `Transcript`; a process's root builds an
`AnthropicProvider` and hands it out as the port, and nothing else knows that
Anthropic exists.

The one seam below this file is `Settings.anthropic_base_url`, which points
the SDK somewhere else. That is how the test double is selected, and it is
deliberately the *only* difference between a test run and a real one: the
request parameters, the message rendering and the response parsing below all
still run.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final, Literal, cast

import anthropic
from anthropic.types import (
    CacheControlEphemeralParam,
    Message,
    MessageParam,
    OutputConfigParam,
    TextBlockParam,
    ThinkingConfigAdaptiveParam,
    ToolChoiceAutoParam,
    ToolParam,
    ToolResultBlockParam,
    ToolUseBlockParam,
)
from anthropic.types.message_create_params import MessageCreateParamsBase

from core.config import LLMSettings
from core.llm.client import (
    AnswerTruncated,
    LLMClient,
    ModelDidNotAnswer,
    ModelRefused,
    ModelUnavailable,
    RequestRejected,
    TurnPaused,
)
from core.llm.escapes import with_escapes_resolved
from core.models.model_policy import (
    DEFAULT_MAX_OUTPUT_TOKENS,
    DEFAULT_MODEL,
    ModelPolicy,
    Reasoning,
)
from core.models.tool_definition import ToolDefinition
from core.models.transcript import (
    Ask,
    Exchange,
    ToolResult,
    ToolResults,
    Transcript,
)
from core.models.turn import ToolCall, Turn

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
THINKING_TYPE: Final = "thinking"
MESSAGE_TYPE: Final = "message"

END_TURN_STOP_REASON: Final = "end_turn"
TOOL_USE_STOP_REASON: Final = "tool_use"

AUTO_TOOL_CHOICE: Final = "auto"

# Which provider answered, as OTel's GenAI conventions spell Anthropic for the
# `gen_ai.provider.name` attribute (`core.telemetry`). Here, with the provider,
# because only the adapter knows which provider it is.
GEN_AI_PROVIDER_ANTHROPIC: Final = "anthropic"

# What an agent held to one tool call per turn asks for. `auto` rather than a
# forced choice, which the current models refuse outright; with parallel use
# off it lets the model call one tool or none, never two.
AT_MOST_ONE_TOOL_CALL: Final[ToolChoiceAutoParam] = ToolChoiceAutoParam(
    type=AUTO_TOOL_CHOICE, disable_parallel_tool_use=True
)

# What separates two text blocks of one turn when they are joined. A newline
# rather than a space: the blocks are paragraphs of one account, and running
# them together would misrepresent where the model paused.
_BETWEEN_WHAT_IT_SAID = "\n"

# Which model answers when nobody said. Aliased from the one declaration
# rather than spelled again here: an agent's model is configuration now, and
# two copies of a default are two answers the day one of them is updated.
#
# Still named in this module because this is where a reader looks for "what
# does Argus actually talk to", and because the contract suite calls the real
# API with it - that check is only worth anything if it names what the adapter
# would have named.
MODEL: Final = DEFAULT_MODEL

# How much room an answer gets when nobody said, aliased from the one
# declaration for the same reason `MODEL` is. Named here because the contract
# suite asks the real API with it, and that check means something only if it
# asks the way the adapter would.
MAX_TOKENS: Final = DEFAULT_MAX_OUTPUT_TOKENS

# Above this the SDK refuses a non-streaming request outright, by a rule
# of its own: it expects 128,000 tokens to take an hour, will not let a
# single response run past ten minutes, and 128000 * 600/3600 is this.
# Hardcoded there, and unmoved by the client's own timeout - so this is
# not a threshold to tune but the line where streaming stops being a
# preference and becomes the only way to ask.
LARGEST_UNSTREAMED_ANSWER: Final = 21_333

# Anthropic's five effort levels, as `output_config.effort` takes them.
type AnthropicEffort = Literal["low", "medium", "high", "xhigh", "max"]

# Where Argus's reasoning scale sits on Anthropic's: one for one, in order, so
# every level Anthropic offers is one a deployment can ask for. `low`, `medium`
# and `high` are spelled alike on both sides; Argus's two above them are what
# Anthropic calls `xhigh` and `max`.
#
# Public and shared with the test that asserts on it, like the vocabulary
# above: these are Anthropic's spellings, and a second copy in a test would be
# a second opinion about a third party.
EFFORT_ON_THE_WIRE: Final[Mapping[Reasoning, AnthropicEffort]] = {
    Reasoning.LOW: "low",
    Reasoning.MEDIUM: "medium",
    Reasoning.HIGH: "high",
    Reasoning.HIGHER: "xhigh",
    Reasoning.HIGHEST: "max"
}

# Anthropic's own vocabulary for a tool offer, named here because this is the
# one module that writes it. Everything above holds a `ToolDefinition` and
# never assembles a schema by hand - which is the point: the strictness rules
# below are easy to half-apply, and a schema that half-applies them is quietly
# permissive rather than broken.
_NAME_KEY: Final = "name"
_DESCRIPTION_KEY: Final = "description"
_INPUT_SCHEMA_KEY: Final = "input_schema"
_STRICT_KEY: Final = "strict"

# And JSON Schema's, for the part of the offer that stamps it strict.
_TYPE_KEY: Final = "type"
_PROPERTIES_KEY: Final = "properties"
_REQUIRED_KEY: Final = "required"
_ADDITIONAL_PROPERTIES_KEY: Final = "additionalProperties"
_OBJECT_TYPE: Final = "object"
_ARRAY_TYPE: Final = "array"

# How a model writes a tool argument when it slips out of JSON into its own
# call syntax, inside another argument's string: the prose ends with the
# closing tag of the argument it was in, and the value that should have been
# an argument of its own follows the opening tag of that one. Both halves are
# quoted from real submissions rather than guessed.
_A_PARAMETER_OPENS: Final = '<parameter name="'
_ITS_NAME_ENDS: Final = '">'

# What comes right before such an opening tag when the model has slipped: the
# closing tag of whatever it was writing - its own argument's, or an earlier
# parameter's it wrote the same way. A tag opened in the middle of a sentence is
# something the prose says, not a call.
_A_CLOSING_TAG_ENDS_IT: Final = re.compile(r"</[A-Za-z_][\w-]*>\s*$")

# The two JSON Schema types a model writes as JSON inside a tag, and what each
# decodes to. A string argument written in a tag is not JSON at all, so there is
# nothing to tell where it ends.
_DECODED_AS: Final[Mapping[str, type]] = {_ARRAY_TYPE: list, _OBJECT_TYPE: dict}

_logger = logging.getLogger(__name__)

# How many times the SDK may retry a call that never reached a verdict - a
# connection that dropped, a 429, a 5xx. Two, which is what the SDK would do
# unasked; the point of saying it is that a retry policy nobody chose is not a
# policy, and a default changing under us would change what an investigation
# costs and how long it takes without anything here mentioning it.
#
# Not raised beyond the default, because retries are paid for out of the
# investigation's own wall clock. The time bound is what answers to the human
# waiting on the incident, and a call retrying with backoff for a minute has
# spent a fifth of it before the model has said anything. Past two, a failure
# reaching Argus is one it should act on rather than wait through: said as
# `ModelUnavailable`, it is the caller's to decide about, and a walk that
# cannot go on without the answer has its run requeued to be tried again
# minutes later rather than held in a longer silence here.
TRANSPORT_RETRIES = 2

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

# How a turn asks to be told what the model was working through. Adaptive
# because the depth of reasoning a question deserves is the model's to judge,
# and summarised because the alternative is this model's default: the blocks
# arrive with empty text and `to_turn` faithfully reads nothing out of them.
#
# Free. Thinking is billed the same under every display setting - what the
# setting changes is only whether Argus is told any of it. Given that, the
# question is whether the reasoning behind a hypothesis is worth keeping, and
# for a system whose product is judgement there is no version of that question
# with a no in it.
#
# Public and shared with the test that asserts on it, like the cache
# breakpoint above, and whole rather than by field: a request that quietly
# stopped asking would otherwise pass a test checking the one part of it
# somebody remembered to look at.
SUMMARISED_THINKING: Final = ThinkingConfigAdaptiveParam(
    type="adaptive", display="summarized"
)

# What a turn that reasoned and then said and asked for nothing goes back as.
# Its reasoning is never resent, so without this it would be a message with no
# content, and the API refuses one of those as it refuses a text block with no
# text.
_A_TURN_THAT_SAID_NOTHING: Final = "(This turn said nothing.)"

# Named for the field rather than left as bare keys, like the vocabulary
# above: these are Anthropic's spellings of how a turn ended, and a test
# restating one would be a second opinion about a third party. `Final` for the
# same reason as the rest - the SDK types `stop_reason` as a `Literal`.
REFUSAL_STOP_REASON: Final = "refusal"
TRUNCATED_STOP_REASON: Final = "max_tokens"
PAUSED_STOP_REASON: Final = "pause_turn"

# The stop reasons that mean the model did not finish its turn. Each is its own
# type because they differ in what to do next; anything not listed is a turn
# that ended normally and is read as one.
_STOP_REASON_ERRORS: dict[str, type[ModelDidNotAnswer]] = {
    REFUSAL_STOP_REASON: ModelRefused,
    TRUNCATED_STOP_REASON: AnswerTruncated,
    PAUSED_STOP_REASON: TurnPaused,
}

# The SDK's errors that mean the model could not be reached for now, raised
# once its own retries are spent: 429, 529, any other 5xx, and a connection
# that failed or timed out (`APITimeoutError` is one). Each is said as
# `ModelUnavailable`; any other status - a 400 above all - is `RequestRejected`,
# and so is the one 429 that is not for now, the account's spending cap.
_UNAVAILABLE_FOR_NOW: Final = (anthropic.RateLimitError,
                               anthropic.OverloadedError,
                               anthropic.InternalServerError,
                               anthropic.APIConnectionError)

# The same, as the type an error names in its body - which is all there is to
# go by for an error event inside a stream that has already answered 200: the
# SDK raises it with the status the response had, as a plain `APIStatusError`.
RATE_LIMIT_ERROR_TYPE: Final = "rate_limit_error"
API_ERROR_TYPE: Final = "api_error"
OVERLOADED_ERROR_TYPE: Final = "overloaded_error"
TIMEOUT_ERROR_TYPE: Final = "timeout_error"
_UNAVAILABLE_ERROR_TYPES: Final = frozenset({RATE_LIMIT_ERROR_TYPE, API_ERROR_TYPE,
                                             OVERLOADED_ERROR_TYPE, TIMEOUT_ERROR_TYPE})

# How a rate limit that is really the account's spending cap is told apart from
# one that will lift in a moment (Anthropic's rate-limits page, "Reaching your
# spend cap"): the code in the error's details. A cap answers the same until
# somebody raises it, so it is never the model being unavailable for now.
SPEND_CAP_ERROR_CODE: Final = "enforced_spend_limit_reached"


def _is_the_spend_cap(failed: anthropic.APIStatusError) -> bool:
    """Whether the error's details carry the spending cap's code."""
    body = failed.body
    error = body.get("error") if isinstance(body, dict) else None
    details = error.get("details") if isinstance(error, dict) else None

    return isinstance(details, dict) and details.get("error_code") == SPEND_CAP_ERROR_CODE


def _in_the_apis_words(failed: anthropic.APIError) -> str:
    """What the API said went wrong: the message in the error's body, where it
    gave one, and the SDK's own words otherwise.

    Not `str` of the error, which for a status is the SDK's display form - a
    status code and the whole body as a Python dict - and that form reached
    every line a step said why it stopped on, Slack and the postmortem among
    them.
    """
    body = failed.body
    error = body.get("error") if isinstance(body, dict) else None
    message = error.get("message") if isinstance(error, dict) else None

    return message if isinstance(message, str) and message else failed.message


def _rejected(failed: anthropic.APIStatusError) -> RequestRejected:
    """A request the API would not take, said in its words. Without the status:
    an error inside a stream arrives with the 200 the stream answered first."""
    return RequestRejected(f"the model's API rejected the request: {_in_the_apis_words(failed)}")


def to_messages(transcript: Transcript) -> list[MessageParam]:
    """Renders a conversation Argus is holding as the messages the API expects.

    The whole of what this module knows about transcripts, and the reason
    `Transcript` can stay Argus's own type: a loop appends `Ask`, `Turn` and
    `ToolResults` and never learns that a tool result is a content block with
    an `is_error` flag.

    A `Turn`'s `reasoning` is not rendered here, deliberately; `to_turn` records
    why, since that is where it was read out of the response.

    Public rather than private because it is a pure function with real rules in
    it - which side each entry is attributed to, and that one turn's results
    travel together - and those rules are worth testing without a client, a key
    or a recording.
    """
    return [_a_message_for(exchange) for exchange in transcript]


def to_tool(tool: ToolDefinition) -> ToolParam:
    """Renders one tool as the API expects a tool offer to look.

    Always strict, and not by a per-tool choice. The dispatcher looks a
    tool up by name and calls it with whatever arrived; an argument the
    schema never promised is one nothing is written to handle. Strict mode
    is what makes the arguments a dispatcher receives exactly the arguments
    it declared - and `additionalProperties: false` is the half of that
    which is easiest to leave out, which is why it is written here rather
    than asked of every caller.

    Strict at every depth, not only at the top. A tool taking a list of
    records - a patch of whole files, each a path and its contents -
    carries objects the caller wrote, and the API demands the same of those.
    It refuses the whole request over one of them, so a nested object left
    permissive takes every other tool in the call down with it.

    Public for the reason `to_messages` is, and for one more: an eval's pool
    is named by the offer exactly as the model sees it, and this is the only
    rendering that carries every field the model reads.
    """
    return cast(ToolParam, {
        _NAME_KEY: tool.name,
        _DESCRIPTION_KEY: tool.description,
        _STRICT_KEY: True,
        _INPUT_SCHEMA_KEY: _strictly(
            {
                _TYPE_KEY: _OBJECT_TYPE,
                _PROPERTIES_KEY: tool.properties,
                _REQUIRED_KEY: tool.required
            }
        )
    })


def _strictly(schema: Any) -> Any:
    """The same schema, with every object in it forbidding what it did not name.

    A copy rather than an edit in place: `properties` is the caller's own
    fragment, usually a module-level constant, and stamping it where it lies
    would rewrite the definition somebody wrote rather than the offer being
    sent.

    Set rather than defaulted, so a fragment that said `true` is corrected
    rather than honoured. There is no tool here for which permissive is the
    right answer, and one arriving that way is a mistake rather than a choice.
    """
    if isinstance(schema, dict):
        stamped = {key: _strictly(value) for key, value in schema.items()}

        if stamped.get(_TYPE_KEY) == _OBJECT_TYPE:
            stamped[_ADDITIONAL_PROPERTIES_KEY] = False

        return stamped

    if isinstance(schema, list):
        return [_strictly(item) for item in schema]

    return schema


def to_turn(message: Message, offered: Sequence[ToolDefinition] = ()) -> Turn:
    """Reads one API response into the shape the loop works in.

    The other direction of `to_messages`, and here for the same reason: turning
    a vendor's payload into Argus's shape is this module's whole job. `Turn`
    itself knows nothing about it, so a module holding one does not depend on
    whoever answered.

    Every half selects by block type rather than by position. A response from
    a thinking model opens with a thinking block, so the first block is the
    model's reasoning far more often than it is the model's answer - and
    reasoning is not narration. It is the model working, frequently revising
    itself, and publishing it as Argus's account of an incident would put
    discarded conclusions in front of a human as though they were held ones.

    Which is why it is carried in a field of its own rather than dropped or
    joined to the text. Why a wrong hypothesis looked right is the most
    useful thing a later reader of an incident can have, and this response is
    the only place it ever exists; what is not read out of it here is gone.
    Nothing that narrates goes near it.

    It is not sent back either, and that is a decision rather than a rule.
    Anthropic's guidance is to echo thinking blocks unchanged while a
    conversation continues on the same model, and `SUMMARISED_THINKING` means
    the blocks hold real reasoning text rather than empty shells - so something
    is genuinely being dropped. Against that: on Sonnet 5 they were not
    load-bearing, so dropping them was neither an error nor a repriced turn -
    and whether that holds on Sonnet 5.5 and Opus 5.5, which the agents now run
    on, is unmeasured; nothing is replayed, so the history-editing check has
    nothing to refuse. The benefit is below the investigator eval's resolution,
    where five of six cases already sit at 50/50 - on rows that all asked
    Opus 5 at high with no brief, not the configured model - and the cost is
    not linear, since every turn's reasoning would be resent by every turn
    after it - quadratic across a walk of up to twelve rounds per
    investigation. The eval's own rows price that side exactly, each carrying
    what its run was billed, which is the measurement to take when the eval
    grows a case sharp enough to make the other side worth paying for.

    Text is joined rather than taken first, because one turn's words arrive as
    however many blocks the API chose to break them into and they are one
    account. Only a real `tool_use` block becomes a call: a model that wrote a
    call into its visible text - which happens when thinking is off - asked for
    nothing, and dispatching it would run something nobody requested.

    A call's arguments are read as the model meant them, which is two repairs
    of its own habits rather than of the API's: a character it escaped instead
    of writing, and an argument it wrote in its native call syntax inside
    another one (`_with_parameters_recovered`). Both are this vendor's model's,
    so both are made here, where every agent's answer passes once. The second
    needs the tools the request `offered`, since an argument is given back only
    under a name the tool declares and in the type it declares; with none
    offered, nothing is given back.

    Public for the same reason as `to_messages`: the rules above are worth
    testing against a hand-built response, without a client, a key or a
    recording.
    """
    declared = {tool.name: tool for tool in offered}

    return Turn(
        text=with_escapes_resolved(
            _BETWEEN_WHAT_IT_SAID.join(
                block.text for block in message.content if block.type == TEXT_TYPE
            )
        ),
        reasoning=_BETWEEN_WHAT_IT_SAID.join(
            block.thinking for block in message.content if block.type == THINKING_TYPE
        ),
        tool_calls=[
            ToolCall(
                id=block.id,
                name=block.name,
                arguments=_with_parameters_recovered(
                    declared.get(block.name), block.name,
                    _arguments_as_written(dict(block.input or {}))
                )
            )
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


def _what_it_cost(message: Message) -> Turn:
    """What an attempt was billed, with nothing to show for it.

    A `Turn` rather than a second shape for spend, so that whoever keeps a
    budget charges this the way it charges an answer - one arithmetic over the
    four counts instead of two to keep in agreement. Empty of content on
    purpose: the part the model managed to write is not an answer and nothing
    should be able to mistake it for one, while what it cost is a fact the
    caller has to have. No tool calls for the same reason - an attempt that
    carried nothing asked for nothing, and a call count that moved here would
    bound the wrong thing.

    Read off the same four fields `to_turn` reads, and deliberately not by
    calling it: that builds a turn out of the content, which is exactly what
    this one must not carry.
    """
    return Turn(
        text="",
        tool_calls=[],
        input_tokens=message.usage.input_tokens,
        output_tokens=message.usage.output_tokens,
        cache_read_tokens=message.usage.cache_read_input_tokens or 0,
        cache_write_tokens=message.usage.cache_creation_input_tokens or 0
    )


def _arguments_as_written(asked_for: dict[str, Any]) -> dict[str, Any]:
    """One request's arguments, with any character the model escaped written out.

    Every string, however deeply the tool's schema nests it: the case this was
    written for is one sentence inside a list of them, and arguments repaired
    only at the top level would leave the escape standing in the record.
    """
    return {name: _as_written(value) for name, value in asked_for.items()}


def _as_written(value: Any) -> Any:
    """One argument, repaired if it is prose and returned untouched if it is not.

    Strings only. A number, a boolean and a null are not things a model escapes
    a character into, and a walk that reached every value rather than every
    string would hand a tool a confidence it could no longer compare.
    """
    if isinstance(value, str):
        return with_escapes_resolved(value)

    if isinstance(value, list):
        return [_as_written(item) for item in value]

    if isinstance(value, dict):
        return {name: _as_written(item) for name, item in value.items()}

    return value


def _with_parameters_recovered(offer: ToolDefinition | None,
                               tool: str,
                               asked_for: dict[str, Any]) -> dict[str, Any]:
    """One request's arguments, with one written in tag form inside another
    given back to the argument it names.

    A real answer, five Code-Fix submissions across two paid runs and every one
    the same: the model closes the prose with `</explanation>`, opens
    `<parameter name="files">`, and writes the whole patch as JSON inside the
    explanation string - while the `files` argument that arrives properly
    holds a phrase pointing at it. Tool arguments in this model's own call
    syntax, in the middle of a JSON one. Nothing was lost and nothing was wrong
    with the fix; what it cost was the run, resubmitting an answer written
    correctly the first time, or worse, a pointer like `(see above)` written to
    a branch as a module.

    Repaired rather than refused: the wrapping was wrong and the answer was
    not. Here rather than in the agent that met it, because the syntax is this
    vendor's model's and any agent's argument can carry it.

    Given back only where all of these hold, because anything less turns prose
    that mentions a tag into a call nobody made:
    - the offered tool declares the name the tag gives, and declares it an
      array or an object - a value a model writes as JSON at all;
    - what follows the tag decodes as that type, so a JSON object written where
      the tool takes a list leaves a readable list alone;
    - the tag comes straight after a closing tag - of the argument it was in,
      or of an earlier parameter written the same way - which is how the slip
      reads every time it has been seen. A tag opened mid-sentence is something
      the prose says.
    Every tag in an argument is tried, in order, so an earlier tag for some
    other parameter does not hide the one that carries the value; the first
    that holds is given back. Its value replaces what arrived under that name
    rather than joining it: the two describe the same thing, and the one in the
    tag is the one the model elided. The argument it was written inside keeps
    everything before that tag, less the closing tag of its own name.

    Untouched where nothing holds - which is not the rare case it reads as: a
    patch written into prose carries the files' own newlines, so it is often
    not JSON at all. What arrived is then what the agent reads, and its own
    checks are what catch it.

    Said at WARNING each time it is made, naming the tool, the argument given
    back and the one it was written inside. The repaired call is what the
    transcript echoes and the replay log keeps, so nothing else shows the model
    slipped - and a model that starts slipping more often is worth seeing.
    """
    if offer is None:
        return asked_for

    for name, value in asked_for.items():
        if not isinstance(value, str):
            continue

        for opens in _every_opening_in(value):
            other, named, written = value[opens + len(_A_PARAMETER_OPENS):].partition(
                _ITS_NAME_ENDS
            )
            before = value[:opens]

            if not named or other == name or not _A_CLOSING_TAG_ENDS_IT.search(before):
                continue

            recovered = _a_value_of_its_declared_type(offer, other, written)

            if recovered is None:
                continue

            _logger.warning("tool argument recovered from tag form",
                            extra={"tool": tool, "argument": other, "written_inside": name})

            return {
                **asked_for,
                name: before.strip().removesuffix(f"</{name}>").strip(),
                other: recovered
            }

    return asked_for


def _every_opening_in(value: str) -> list[int]:
    """Where each parameter's opening tag starts in `value`, in order."""
    found: list[int] = []
    at = value.find(_A_PARAMETER_OPENS)

    while at != -1:
        found.append(at)
        at = value.find(_A_PARAMETER_OPENS, at + 1)

    return found


def _a_value_of_its_declared_type(offer: ToolDefinition, argument: str, written: str) -> Any:
    """The value written at the start of `written`, where `offer` declares
    `argument` an array or an object and that is what it decodes as - or `None`.

    Trailing text after it is tolerated, which is what `raw_decode` buys: a
    model that closed the tag, or wrote another paragraph after it, still
    wrote the value.
    """
    declared = offer.properties.get(argument, {}).get(_TYPE_KEY)
    decoded_as = _DECODED_AS.get(declared) if isinstance(declared, str) else None

    if decoded_as is None:
        return None

    try:
        decoded, _ = json.JSONDecoder().raw_decode(written.strip())
    except ValueError:
        return None

    return decoded if isinstance(decoded, decoded_as) else None


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

    if not exchange.tool_calls:
        # A turn of words alone goes back as its words. Sent as its calls -
        # none - it would be a message with nothing in it, which the API
        # refuses; and one with no words either still has to carry something.
        return {
            "role": ASSISTANT_ROLE,
            "content": [
                TextBlockParam(type=TEXT_TYPE, text=exchange.text or _A_TURN_THAT_SAID_NOTHING)
            ],
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


def _the_standing_brief(brief: str) -> list[TextBlockParam]:
    """An agent's standing instructions, as the one block they are sent in.

    A list of blocks rather than the plain string the API also accepts,
    because a breakpoint is a field on a block: sent as a string the words
    would arrive and the marker could not, and the saving this exists for
    would silently be no saving at all.

    One block, and nothing appended to it ever. What makes the prefix worth
    caching is that it is byte-identical across incidents, so anything about
    the incident belongs in `messages` - where it already is.
    """
    return [
        TextBlockParam(type=TEXT_TYPE, text=brief, cache_control=EPHEMERAL_CACHE)
    ]


@dataclass(frozen=True)
class AnthropicProvider:
    """`ModelProvider` answered by Anthropic, reached where `settings` say.

    What a process's root builds and hands out as the port. It holds where
    the API is and with whose key, and builds a client per policy when asked -
    one SDK client each, as the factory always built, so nothing about a
    conversation is shared between two incidents through this.

    `sdk` is the seam a test reaches for when what it is checking is the
    request rather than the answer: every client built is handed it instead of
    one of its own. Configuration still decides everything about a real one.

    A frozen value, so that two providers built from the same settings are the
    same provider - which is how a test reads off a binding which one an agent
    was given. Its settings are left out of its `repr`, because they carry the
    key, and a provider printed in a log or a failure would print it.
    """

    settings: LLMSettings = field(repr=False)
    sdk: anthropic.Anthropic | None = None

    @property
    def name(self) -> str:
        return GEN_AI_PROVIDER_ANTHROPIC

    def client(self, policy: ModelPolicy, /) -> LLMClient:
        return AnthropicLLMClient(self.settings, policy=policy, client=self.sdk)


class AnthropicLLMClient:
    """`LLMClient` backed by the real Anthropic Messages API.

    The client is built once and reused: `messages.create` is stateless, and a
    per-call client would throw away the connection pool for no benefit.
    """

    def __init__(self,
                 settings: LLMSettings,
                 policy: ModelPolicy | None = None,
                 client: anthropic.Anthropic | None = None) -> None:
        """Builds the SDK client this talks through, unless handed one.

        `policy` is which model answers and how hard it is asked to think, and
        it is held here rather than taken per call. Which agent this client
        serves is fixed for the whole of an incident while the transcript is
        not, so binding it once keeps the choice out of a seam whose subject
        is a conversation - and leaves a loop holding something that knows of
        no model, no effort and no client, which is the whole point of that
        seam. Defaulted, so a caller with no opinion gets what every agent got
        when there was one answer for all of them.

        `client` is the seam a test reaches for when what it is checking is the
        request rather than the answer - the same need `_api_key_for` already
        answers from the other side. Configuration still decides everything
        about a real one; passing a client only says that this one is not.
        """
        self._policy = policy if policy is not None else ModelPolicy()
        base_url = settings.anthropic_base_url or None
        self._client = client if client is not None else anthropic.Anthropic(
            api_key=_api_key_for(settings.anthropic_api_key, base_url),
            # An empty setting means the real API, which is what the SDK does
            # with `base_url=None`. Passing "" would point it at nothing.
            base_url=base_url,
            max_retries=TRANSPORT_RETRIES,
        )

    def converse(self,
                 transcript: Transcript,
                 tools: list[ToolDefinition],
                 max_tokens: int | None = None) -> Turn:
        """Takes one turn of a conversation in which the model may ask for tools.

        The only way of asking. It hands the model a transcript and a set of
        tools and gets back whatever it wants to do next - which is usually not
        an answer but a request for evidence.

        The loop above calls this once per turn and owns the transcript.
        Deliberately so: what has been asked and answered is the loop's
        business, and a client that remembered it would make two investigations
        share state through this object.

        Adaptive thinking, at whatever effort this client's agent was
        given: the judgement being asked for is which evidence would settle
        the question, which is exactly what gets worse without reasoning.

        How much room the answer gets comes from the policy unless a caller
        names a figure, and above `LARGEST_UNSTREAMED_ANSWER` the answer is
        streamed. That is not a preference about latency: past that line the
        SDK refuses an ordinary request before sending it, so an agent whose
        answers are whole files has no other way to ask for the room it
        needs. Below the line nothing streams, because nothing gains by it:
        the same message arrives either way, and the simpler request is the
        one whose failures are easier to read.

        A turn that is not a turn raises rather than returning: a refusal, a
        truncated answer, or a pause. The three differ in what to do next, so
        each is its own type, and none of them is a `Turn` a loop could
        mistake for progress.
        """
        offered = [to_tool(tool) for tool in tools]
        room = max_tokens if max_tokens is not None else self._policy.max_output_tokens

        answer = self._answered(transcript, offered, room)

        error_type = _STOP_REASON_ERRORS.get(answer.stop_reason or "")
        if error_type is not None:
            # Billed before it is raised, because this is the only place the
            # counts exist. The API reports them on a response this method
            # then declines to return, so a failure raised without them takes
            # what the attempt cost with it - and a turn stopped at its cap
            # cost a whole cap of output.
            raise error_type(
                f"the model did not complete its turn (stop_reason={answer.stop_reason})",
                billed=_what_it_cost(answer)
            )

        return to_turn(answer, tools)

    def _answered(self,
                  transcript: Transcript,
                  offered: list[ToolParam],
                  room: int) -> Message:
        """One response, asked for whichever way this much room allows.

        The two calls take the same arguments and mean the same thing; only
        the transport differs, and `get_final_message` assembles the streamed
        one back into exactly what the other returns. So everything after
        this - the stop reason, the counts, the translation - is written once
        and never learns which way the answer arrived.
        """
        asked = self._request(transcript, offered, room)

        # What comes back is a `Message` either way - the stream assembles a
        # `ParsedMessage`, which is one with nothing parsed into it here - and
        # that is the whole reason the rest of `converse` can be written once.
        try:
            if room <= LARGEST_UNSTREAMED_ANSWER:
                return self._client.messages.create(**asked)

            with self._client.messages.stream(**asked) as streamed:
                return streamed.get_final_message()
        except _UNAVAILABLE_FOR_NOW as unavailable:
            if isinstance(unavailable, anthropic.APIStatusError) and _is_the_spend_cap(unavailable):
                raise _rejected(unavailable) from unavailable

            raise ModelUnavailable(f"the model could not be reached for now: "
                                   f"{_in_the_apis_words(unavailable)}") from unavailable
        except anthropic.APIStatusError as failed:
            if failed.type not in _UNAVAILABLE_ERROR_TYPES or _is_the_spend_cap(failed):
                raise _rejected(failed) from failed

            raise ModelUnavailable(f"the model could not be reached for now: "
                                   f"{_in_the_apis_words(failed)}") from failed

    def _request(self,
                 transcript: Transcript,
                 offered: list[ToolParam],
                 room: int) -> MessageCreateParamsBase:
        """Everything one turn asks for, as the arguments both ways take.

        Built once rather than at each call so the two cannot drift: a
        breakpoint or an effort level that reached only the unstreamed path
        would be a difference nothing here declares and only the bill would
        notice.

        Two breakpoints, and they are asked for in different ways because they
        are caching different things. The top-level one rides the end of the
        transcript and saves within one incident. The one on the standing
        brief sits on a block that is identical in every incident this agent
        ever handles - and since `tools` renders before `system`, the prefix it
        closes includes the whole tool list, which is the larger half of the
        saving for an agent carrying many tools.

        The `system` key is absent rather than empty when an agent has nothing
        standing to say. An empty block would still be a breakpoint, and a
        breakpoint on nothing is a write premium charged every incident against
        a prefix no later request can read.
        """
        asked = MessageCreateParamsBase(
            model=self._policy.model,
            max_tokens=room,
            # Asked for at the top level rather than pinned to a block: the API
            # places the breakpoint on the last cacheable block and moves it
            # forward as the transcript grows, which is the shape of this loop -
            # every turn's prefix is the previous turn's entire request. Pinning
            # it would freeze the saving at whatever the first turn sent.
            cache_control=EPHEMERAL_CACHE,
            output_config=OutputConfigParam(effort=EFFORT_ON_THE_WIRE[self._policy.effort]),
            thinking=SUMMARISED_THINKING,
            tools=offered,
            messages=to_messages(transcript),
        )

        if self._policy.brief:
            asked["system"] = _the_standing_brief(self._policy.brief)

        # Absent rather than set to the API's default for every other agent:
        # the same meaning, but a different request, and every cached prefix
        # and recording was made of the request as it was.
        if self._policy.one_tool_call_per_turn:
            asked["tool_choice"] = AT_MOST_ONE_TOOL_CALL

        return asked
