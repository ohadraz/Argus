"""A change asked for by a claim the run has moved past, refused as deployed.

A worker paused past its lease wakes holding a claim the run has moved past, and
its next change to the world would be a second walk acting on an incident
somebody else is walking. The write tier refuses it - the server as `main`
starts it, asking the run's own row in a real database - and the walk is told so
in the one way it stops on.

Every part of that is pinned somewhere smaller: the hold against a real row in
the runs repository's suite, the refusal over a stand-in hold in the server's,
the fence crossing the wire in the transport's. What only this case can say is
that they are wired together: that the server actually started reads the run.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta
from typing import Any, Final

import httpx2
import pytest
from argus_core import (
    Fence,
    Holding,
    RunLost,
    WriteMcpEndpoint,
    connect_from_env,
    get_settings,
    utc_now,
)
from argus_core.mcp_transport import McpClient
from argus_core.models import Alert
from argus_incidents.repository import incidents, runs
from argus_testkit import Assertion, Scenario, all_of, an_error_was_raised, attempting
from github_double.server import DEFAULT_BASE_URL as GITHUB_DOUBLE_BASE_URL
from write_mcp_client import commit_to_new_branch, write_mcp

REQUEST_TIMEOUT_SECONDS: Final = 30.0

# The first claim's lease is over before it begins, which is what lets the
# second claim take the run back; the second's outlasts the test.
A_LEASE_ALREADY_OVER: Final = timedelta(seconds=-1)
A_GENEROUS_LEASE: Final = timedelta(minutes=5)

SOME_BRANCH: Final = "argus/fix-for-a-lost-run"


@pytest.fixture
def github_double() -> Iterator[httpx2.Client]:
    with httpx2.Client(base_url=GITHUB_DOUBLE_BASE_URL,
                       timeout=REQUEST_TIMEOUT_SECONDS) as control:
        control.post("/double-control/reset").raise_for_status()
        yield control
        control.post("/double-control/reset").raise_for_status()


@pytest.mark.integration
def test_a_change_for_a_claim_the_run_moved_past_is_refused_as_a_lost_run(
    github_double: httpx2.Client
) -> None:
    settings = get_settings()
    holding = Holding()

    with write_mcp(WriteMcpEndpoint.of(settings), holding=holding) as write:
        Scenario() \
            .given(
                stale := _a_claim_the_run_was_taken_back_from()
            ) \
            .when(attempting(
                lambda: _writing_a_branch_holding(holding, stale, write)
            )) \
            .then(all_of(
                an_error_was_raised(RunLost),
                _no_branch_was_written(github_double, SOME_BRANCH)
            ))


def _a_claim_the_run_was_taken_back_from() -> Fence:
    """The claim a paused worker still holds, after the run was claimed again."""
    with connect_from_env() as conn:
        incident_id = incidents.create(
            conn, Alert(service="io-shop", alert_name="HighErrorRate"), at=utc_now()
        )
        runs.enqueue(conn, incident_id)
        paused = runs.claim(conn, "worker-that-was-paused", A_LEASE_ALREADY_OVER)
        came_after = runs.claim(conn, "worker-that-came-after", A_GENEROUS_LEASE)
        assert paused is not None and came_after is not None

    return Fence(run_id=paused.id, epoch=paused.epoch)


def _writing_a_branch_holding(holding: Holding, held: Fence, write: McpClient) -> str:
    settings = get_settings()

    with holding.of(held):
        return commit_to_new_branch(
            branch=SOME_BRANCH,
            base_branch=settings.github_base_branch,
            files={"io_shop/dont_care.py": "dont care\n"},
            message="dont care",
            client=write
        )


def _no_branch_was_written(github_double: httpx2.Client, branch: str) -> Assertion[Any]:
    def assertion(_: Any) -> bool:
        written = github_double.get("/double-control/branches").json()["branches"]

        if branch in written:
            raise AssertionError(
                f"Expected nothing written for a claim the run had moved past, and "
                f"branch [{branch}] reached the repository: {written}."
            )

        return True

    return assertion
