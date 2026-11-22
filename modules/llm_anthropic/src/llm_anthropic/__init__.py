"""The Anthropic adapter for the kernel's `ModelProvider` port, built by a
process's root and by nothing else.

The wire vocabulary is exported beside the provider so that nothing has to
restate it: the suites that build an answer the SDK would give, and the files
that stand where a root would, name each word from here.
"""

from llm_anthropic.adapter import (
    ASSISTANT_ROLE,
    AT_MOST_ONE_TOOL_CALL,
    EFFORT_ON_THE_WIRE,
    END_TURN_STOP_REASON,
    EPHEMERAL_CACHE,
    LARGEST_UNSTREAMED_ANSWER,
    MAX_TOKENS,
    MESSAGE_TYPE,
    MODEL,
    REFUSAL_STOP_REASON,
    SUMMARISED_THINKING,
    TEXT_TYPE,
    THINKING_TYPE,
    TOOL_USE_STOP_REASON,
    TOOL_USE_TYPE,
    TRUNCATED_STOP_REASON,
    AnthropicEffort,
    AnthropicLLMClient,
    AnthropicProvider,
    AnthropicSettings,
    to_messages,
    to_tool,
    to_turn,
)

__all__ = [
    "ASSISTANT_ROLE",
    "AT_MOST_ONE_TOOL_CALL",
    "EFFORT_ON_THE_WIRE",
    "END_TURN_STOP_REASON",
    "EPHEMERAL_CACHE",
    "LARGEST_UNSTREAMED_ANSWER",
    "MAX_TOKENS",
    "MESSAGE_TYPE",
    "MODEL",
    "REFUSAL_STOP_REASON",
    "SUMMARISED_THINKING",
    "TEXT_TYPE",
    "THINKING_TYPE",
    "TOOL_USE_STOP_REASON",
    "TOOL_USE_TYPE",
    "TRUNCATED_STOP_REASON",
    "AnthropicEffort",
    "AnthropicLLMClient",
    "AnthropicProvider",
    "AnthropicSettings",
    "to_messages",
    "to_tool",
    "to_turn"
]
