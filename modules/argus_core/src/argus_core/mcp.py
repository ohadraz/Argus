from __future__ import annotations

from typing import Protocol


class MCPClient(Protocol):
    def call_tool(self, name: str, **kwargs: object) -> object: ...


class StubMCPClient:
    """Placeholder shape other modules import against - no real MCP server
    calls in the walking-skeleton change (design.md Non-Goals)."""

    def call_tool(self, name: str, **kwargs: object) -> object:
        raise NotImplementedError("no real MCP tool calls in the walking-skeleton change")


def get_mcp_client(server: str) -> MCPClient:
    return StubMCPClient()
