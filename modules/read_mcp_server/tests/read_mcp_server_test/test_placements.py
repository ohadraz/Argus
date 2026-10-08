"""Where a service's replicas run, as the read tier answers it.

The channel that reads what no other one holds: a replica moved to another card
with nothing deployed is in no deployment history, no diff and no flag log. It is
only in where the pods are - so this is how the one failure mode whose cause is a
placement becomes evidence at all.

How the platform is asked - the tree, a pod's info, a host's labels - is the
adapter's, and pinned in its own suite. What is pinned here is that the answer
reaches the caller as the platform gave it, and that a platform that did not
answer is never reported as a service running nowhere.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import create_autospec

import pytest
from argus_core.models import PodPlacement
from argus_testkit import Assertion, Scenario, all_of, an_error_was_raised, attempting
from deployment_platform import (
    DeploymentPlatformError,
    DeploymentPlatformReads,
    PlatformRefused,
    PlatformUnreachable,
)
from read_mcp_server.placements import PlacementUnreadable, where_the_service_runs

SOME_SERVICE = "io-shop"


@pytest.mark.unit
def test_the_platforms_placements_reach_the_caller_as_it_gave_them() -> None:
    the_placements = [
        PodPlacement(
            pod="io-shop-a",
            node="gpu-v100-1",
            accelerator="Tesla-V100-SXM2-16GB",
            started_at=datetime(2026, 10, 7, 9, 0, tzinfo=UTC)
        ),
        PodPlacement(
            pod="io-shop-b",
            node="gpu-a100-0",
            accelerator="NVIDIA-A100-SXM4-40GB",
            started_at=datetime(2026, 10, 7, 21, 40, 30, tzinfo=UTC)
        )
    ]

    Scenario() \
        .given(platform := _a_platform_placing(the_placements)) \
        .when(lambda: where_the_service_runs(SOME_SERVICE, platform=platform)) \
        .then(all_of(
            _it_is(the_placements),
            lambda _: _the_service_was_asked_about_by_name(platform)
        ))


@pytest.mark.unit
@pytest.mark.parametrize(
    "failure",
    [PlatformUnreachable("platform is down"), PlatformRefused("not this answer")],
    ids=["unreachable", "refused"]
)
def test_a_platform_that_did_not_answer_is_not_reported_as_placing_nothing(
    failure: DeploymentPlatformError
) -> None:
    # An empty list would say the service runs nowhere, and a walk deciding from
    # it would find no replica that moved - an outage read as an all-clear.
    Scenario() \
        .given(platform := _a_platform_failing_with(failure)) \
        .when(attempting(
            lambda: where_the_service_runs(SOME_SERVICE, platform=platform)
        )) \
        .then(an_error_was_raised(PlacementUnreadable))


def _a_platform_placing(placements: list[PodPlacement]) -> Any:
    platform = create_autospec(DeploymentPlatformReads, instance=True)
    platform.placements_of.return_value = placements
    return platform


def _a_platform_failing_with(failure: DeploymentPlatformError) -> Any:
    platform = create_autospec(DeploymentPlatformReads, instance=True)
    platform.placements_of.side_effect = failure
    return platform


def _it_is(expected: list[PodPlacement]) -> Assertion[list[PodPlacement]]:
    def assertion(placements: list[PodPlacement]) -> bool:
        if placements != expected:
            raise AssertionError(
                f"Expected the platform's own placements {expected}, and the "
                f"caller got {placements}."
            )

        return True

    return assertion


def _the_service_was_asked_about_by_name(platform: Any) -> bool:
    asked = [call.args for call in platform.placements_of.call_args_list]

    if asked != [(SOME_SERVICE,)]:
        raise AssertionError(
            f"Expected the placement of [{SOME_SERVICE}] to be read once, and the "
            f"platform was asked {asked}."
        )

    return True
