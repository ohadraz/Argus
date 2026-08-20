from __future__ import annotations

from typing import cast

from argus_core.config import get_settings
from argus_core.mcp_transport import call_mcp_tool


def get_log_lines(window: str | None = None, filters: str | None = None) -> list[str]:
    settings = get_settings()
    result = call_mcp_tool(
        f"{settings.read_mcp_url}/mcp", "get_log_lines", window=window, filters=filters
    )
    return cast(list[str], result)
