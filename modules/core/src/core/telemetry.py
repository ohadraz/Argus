"""The names Argus's telemetry is spelled in, declared once.

Most of them are OpenTelemetry's: the GenAI and MCP semantic conventions say
what a model call and a tool call are named and which attributes they carry, so
any backend reading Argus's traces recognises them without being told. Those
conventions are still marked "Development" and have renamed attributes before
(`gen_ai.system` became `gen_ai.provider.name`), which is why every one of them
is spelled here and nowhere else - a rename is one line.

The rest are Argus's own, under its own `argus.` prefix, for the two things no
convention knows about: which incident a span belongs to, and which agent made
it.

Plain strings rather than OTel's `opentelemetry-semantic-conventions` package,
whose GenAI names are already deprecated there in favour of a repository that
publishes no Python package. A dependency on names that point elsewhere is a
dependency on somebody else's migration.
"""

from __future__ import annotations

from typing import Final

# --- GenAI: a model call (OTel GenAI semantic conventions) ---

# The operation a model call is - a chat completion, in OTel's vocabulary for
# what `converse` does - and the provider answering it.
GEN_AI_OPERATION_NAME: Final = "gen_ai.operation.name"
GEN_AI_CHAT_OPERATION: Final = "chat"
GEN_AI_PROVIDER_NAME: Final = "gen_ai.provider.name"
GEN_AI_PROVIDER_ANTHROPIC: Final = "anthropic"
GEN_AI_REQUEST_MODEL: Final = "gen_ai.request.model"
GEN_AI_REQUEST_MAX_TOKENS: Final = "gen_ai.request.max_tokens"

# What the call cost, as the provider reported it. `input_tokens` is every
# input token, cached ones included, and the two cache counts are parts of it -
# the convention's definition, which is not Anthropic's: there, input is only
# the uncached remainder.
GEN_AI_USAGE_INPUT_TOKENS: Final = "gen_ai.usage.input_tokens"
GEN_AI_USAGE_OUTPUT_TOKENS: Final = "gen_ai.usage.output_tokens"
GEN_AI_USAGE_CACHE_READ_INPUT_TOKENS: Final = "gen_ai.usage.cache_read.input_tokens"
GEN_AI_USAGE_CACHE_CREATION_INPUT_TOKENS: Final = "gen_ai.usage.cache_creation.input_tokens"

# Why the model stopped, one reason per choice - Argus asks for one.
GEN_AI_RESPONSE_FINISH_REASONS: Final = "gen_ai.response.finish_reasons"
FINISH_REASON_STOP: Final = "stop"
FINISH_REASON_TOOL_CALL: Final = "tool_call"
FINISH_REASON_LENGTH: Final = "length"
FINISH_REASON_CONTENT_FILTER: Final = "content_filter"
FINISH_REASON_ERROR: Final = "error"

# The conversation itself, as JSON in the convention's message shape.
GEN_AI_INPUT_MESSAGES: Final = "gen_ai.input.messages"
GEN_AI_OUTPUT_MESSAGES: Final = "gen_ai.output.messages"

# The message shape's own vocabulary: who said it, and what kind of part each
# piece of it is.
MESSAGE_ROLE: Final = "role"
MESSAGE_PARTS: Final = "parts"
MESSAGE_FINISH_REASON: Final = "finish_reason"
ROLE_USER: Final = "user"
ROLE_ASSISTANT: Final = "assistant"
ROLE_TOOL: Final = "tool"
PART_TYPE: Final = "type"
PART_TEXT: Final = "text"
PART_REASONING: Final = "reasoning"
PART_TOOL_CALL: Final = "tool_call"
PART_TOOL_CALL_RESPONSE: Final = "tool_call_response"
PART_CONTENT: Final = "content"
PART_ID: Final = "id"
PART_NAME: Final = "name"
PART_ARGUMENTS: Final = "arguments"
PART_RESPONSE: Final = "response"

# The two metrics every model call records, and the attribute that tells the
# token metric's two kinds of point apart.
GEN_AI_CLIENT_OPERATION_DURATION: Final = "gen_ai.client.operation.duration"
GEN_AI_CLIENT_TOKEN_USAGE: Final = "gen_ai.client.token.usage"
GEN_AI_TOKEN_TYPE: Final = "gen_ai.token.type"
TOKEN_TYPE_INPUT: Final = "input"
TOKEN_TYPE_OUTPUT: Final = "output"

# UCUM, as OTel's metrics are unit-ed.
UNIT_SECONDS: Final = "s"
UNIT_TOKENS: Final = "{token}"

# --- GenAI: an agent at work (OTel GenAI semantic conventions) ---

# A step of the walk that belongs to one of Argus's agents is the convention's
# `invoke_agent` operation, and its span is named `invoke_agent {agent}`.
GEN_AI_INVOKE_AGENT_OPERATION: Final = "invoke_agent"
GEN_AI_AGENT_NAME: Final = "gen_ai.agent.name"

# --- MCP: a tool call (OTel MCP semantic conventions) ---

# A tool call is the `tools/call` method, aimed at one tool - which is also
# what its span is named, `{method} {tool}` - and an operation GenAI calls
# executing a tool.
MCP_METHOD_NAME: Final = "mcp.method.name"
MCP_TOOLS_CALL_METHOD: Final = "tools/call"
GEN_AI_TOOL_NAME: Final = "gen_ai.tool.name"
GEN_AI_EXECUTE_TOOL_OPERATION: Final = "execute_tool"
MCP_CLIENT_OPERATION_DURATION: Final = "mcp.client.operation.duration"

# Which server a call went to (OTel general semantic conventions).
SERVER_ADDRESS: Final = "server.address"
SERVER_PORT: Final = "server.port"

# --- Errors (OTel general semantic conventions) ---

# What went wrong, as a low-cardinality name - the exception's class.
ERROR_TYPE: Final = "error.type"

# --- Argus's own ---

# Which agent a span or a metric point belongs to. Carried as baggage as well
# as set on the agent's span, so that a model call made deep inside an agent -
# by a client that was never told whose it is - can still say.
ARGUS_AGENT: Final = "argus.agent"
ARGUS_INCIDENT_ID: Final = "argus.incident.id"

# Which claimed run of the incident a log record was written in. Two walks of
# one incident share its trace, so this is what tells their records apart.
ARGUS_RUN_ID: Final = "argus.run.id"

# Which node of the walk's graph a span is - every step has one, the
# orchestrator's own included, which have no agent's name to go by.
ARGUS_WALK_STEP: Final = "argus.walk.step"

# One walk, start to finish: how many there were and how long each took, told
# apart by how the incident ended.
ARGUS_INCIDENT_WALKS: Final = "argus.incident.walks"
ARGUS_INCIDENT_WALK_DURATION: Final = "argus.incident.walk.duration"
ARGUS_INCIDENT_OUTCOME: Final = "argus.incident.outcome"
UNIT_WALKS: Final = "{walk}"
