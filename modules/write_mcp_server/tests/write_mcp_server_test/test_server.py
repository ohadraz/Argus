"""Which of the write tier's tools are changes, and so asked after the run first.

The one thing about the assembled server its own tools' suites cannot see: a
tool left unmarked changes the world for any walk at all, a stale one included,
and nothing about the tool itself would say so.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import create_autospec

import pytest
from argus_core import Fence, WriteMcpEndpoint
from argus_testkit import Assertion, Scenario
from deployment_platform import DeploymentPlatformWrites
from write_mcp_server.discarding import DiscardSettings
from write_mcp_server.fencing import FencedFastMCP
from write_mcp_server.flag_state import FlagWriteSettings
from write_mcp_server.server import build_server

from write_mcp_server_test.framework.settings import some_repository_settings

# Every tool that changes something outside the tier: the seven mitigations,
# the four restores that put them back, and the branch and pull request a fix
# is proposed on. The one read on this server is not among them.
EVERY_CHANGE = {
    "set_feature_flag", "restart_service", "roll_back_deployment", "restore_deployment",
    "scale_out", "restore_replica_count", "pin_autoscaler", "discard_cache_entries",
    "restore_autoscaler_floor", "pin_to_accelerator", "restore_accelerator_pin",
    "commit_to_new_branch", "open_pull_request"
}


@pytest.mark.unit
def test_every_tool_the_tier_serves_but_its_one_read_is_a_change() -> None:
    Scenario() \
        .given(
            server := _a_server()
        ) \
        .when(
            lambda: _what_it_serves(server)
        ) \
        .then(
            _changes_are(server, EVERY_CHANGE, reads={"get_recent_flag_changes"})
        )


def _a_server() -> FencedFastMCP:
    return build_server(
        WriteMcpEndpoint(write_mcp_host="127.0.0.1", write_mcp_port=8199,
                         write_mcp_url="http://127.0.0.1:8199"),
        FlagWriteSettings(unleash_base_url="http://unleash.invalid",
                          unleash_frontend_token="dont-care-frontend-token",
                          unleash_admin_token="dont-care-admin-token",
                          unleash_project="default",
                          unleash_environment="production"),
        some_repository_settings(),
        create_autospec(DeploymentPlatformWrites, instance=True),
        DiscardSettings(cache_url="redis://cache.invalid:6379"),
        _a_hold_never_asked
    )


@contextmanager
def _a_hold_never_asked(dont_care_fence: Fence) -> Iterator[bool]:
    raise AssertionError("Expected the run never asked after while assembling, and it was.")


def _what_it_serves(server: FencedFastMCP) -> set[str]:
    return {tool.name for tool in asyncio.run(server.list_tools())}


def _changes_are(server: FencedFastMCP,
                 expected: set[str],
                 reads: set[str]) -> Assertion[set[str]]:
    def assertion(served: set[str]) -> bool:
        if set(server.changes) != expected or served - set(server.changes) != reads:
            raise AssertionError(
                f"Expected {sorted(expected)} marked as changes and only {sorted(reads)} "
                f"served unmarked; marked were {sorted(server.changes)} and unmarked "
                f"{sorted(served - set(server.changes))}."
            )

        return True

    return assertion
