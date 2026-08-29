from __future__ import annotations

import asyncio

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


def call_mcp_tool(url: str, name: str, **kwargs: object) -> object:
    """Generic streamable-HTTP MCP tool call - the shared transport plumbing
    that a server's own typed `*_client` package (e.g. `logs_mcp_client`)
    wraps with real argument/return types. Synchronous to match the rest of
    this codebase (LangGraph nodes, `agent_investigator.investigate()`) -
    opens a fresh connection and event loop per call via `asyncio.run`,
    rather than pushing async down through every caller for what is, for
    now, low call volume."""
    return asyncio.run(_call_mcp_tool(url, name, **kwargs))


async def _call_mcp_tool(url: str, name: str, **kwargs: object) -> object:
    async with (
        streamable_http_client(url) as (read, write, _),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        result = await session.call_tool(name, arguments=kwargs)

        if result.isError:
            raise RuntimeError(f"MCP tool call [{name}] failed: {result.content!r}")

        structured = result.structuredContent

        if structured is None:
            return None

        # A tool returning something that is not already a JSON object - a
        # list of log lines, a list of buckets - has it wrapped under `result`,
        # because a structured-content payload has to be an object at the top
        # level. A tool returning a dict is already one, and arrives unwrapped.
        # Unwrapping unconditionally worked only for as long as every tool
        # returned a list.
        return structured.get("result", structured)
