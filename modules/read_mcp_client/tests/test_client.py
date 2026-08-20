from __future__ import annotations

import pytest
from conftest import FakeTargetServiceHandler
from read_mcp_client import get_log_lines


@pytest.mark.integration
def test_get_log_lines_reaches_the_real_read_mcp_server(
    running_read_mcp: type[FakeTargetServiceHandler],
) -> None:
    some_logs = ["INFO some line", "ERROR another line"]
    running_read_mcp.logs = some_logs

    result = get_log_lines()

    assert result == some_logs
