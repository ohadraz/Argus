from __future__ import annotations

import pytest
from read_mcp_server.server import _get_log_lines


@pytest.mark.unit
def test_get_log_lines_returns_whatever_fetch_returns() -> None:
    some_logs = ["INFO line one", "ERROR line two"]

    result = _get_log_lines(fetch=lambda: some_logs)

    assert result == some_logs
