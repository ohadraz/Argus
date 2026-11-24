"""How Argus reaches an MCP server and answers as one: the held client session,
the traced server, and the refusal both sides read.

A package of its own so the kernel installs no MCP SDK, no HTTP client and no
ASGI server; the two tiers' clients, both servers, the Mitigator and the walk
take it.
"""

from mcp_transport.refusals import REFUSAL_KEY, ToolRefusal, ToolRefusalKind, ToolRefused
from mcp_transport.transport import (
    ACTION_META_KEY,
    FENCE_META_KEY,
    PING_SECONDS,
    ActionExhausted,
    Asking,
    AskingBound,
    ChangedSince,
    LostAfterSending,
    McpClient,
    McpToolError,
    McpUnreachable,
    PlatformUnreachable,
    TracedMCPServer,
    WhichAsking,
    a_change_made_since,
    a_lost_run,
    a_refusal_saying_what_it_left,
    an_exhausted_action,
    an_http_client_waiting,
    an_unreachable_platform,
    every_tool_listed,
    serving_a_tool_call,
    with_what_it_left,
)

__all__ = [
    "ACTION_META_KEY",
    "FENCE_META_KEY",
    "PING_SECONDS",
    "REFUSAL_KEY",
    "ActionExhausted",
    "Asking",
    "AskingBound",
    "ChangedSince",
    "LostAfterSending",
    "McpClient",
    "McpToolError",
    "McpUnreachable",
    "PlatformUnreachable",
    "ToolRefusal",
    "ToolRefusalKind",
    "ToolRefused",
    "TracedMCPServer",
    "WhichAsking",
    "a_change_made_since",
    "a_lost_run",
    "a_refusal_saying_what_it_left",
    "an_exhausted_action",
    "an_http_client_waiting",
    "an_unreachable_platform",
    "every_tool_listed",
    "serving_a_tool_call",
    "with_what_it_left"
]
