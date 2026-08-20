from __future__ import annotations

from collections.abc import Callable

import httpx
from argus_core.config import get_settings
from mcp.server.fastmcp import FastMCP

settings = get_settings()
mcp = FastMCP(
    "argus-read-mcp",
    host=settings.read_mcp_host,
    port=settings.read_mcp_port,
)

Fetch = Callable[[], list[str]]


def _fetch_target_service_logs() -> list[str]:
    response = httpx.get(f"{settings.target_service_url}/logs", timeout=10.0)
    response.raise_for_status()
    logs: list[str] = response.json()
    return logs


def _get_log_lines(fetch: Fetch = _fetch_target_service_logs) -> list[str]:
    return fetch()


@mcp.tool()
def get_log_lines(window: str | None = None, filters: str | None = None) -> list[str]:
    """Fetches the Target Service's current log and returns it as lines.

    `window`/`filters` match the tool's eventual shape (spec §16 - real
    time-windowed, bucket-scoped retrieval) but aren't acted on yet: no
    caller can supply a meaningful value for either until `metrics-mcp` and
    the ReAct loop exist to drive them, so this is a pass-through fetch for
    now (design.md Non-Goals). The `fetch` injection seam lives on the
    private `_get_log_lines`, not here - a `Callable`-typed default param on
    an `@mcp.tool()`-decorated function breaks FastMCP's JSON-schema
    generation (verified directly - `pydantic.errors.PydanticInvalidForJsonSchema:
    Cannot generate a JsonSchema for core_schema.CallableSchema`)."""
    return _get_log_lines()


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
