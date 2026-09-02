from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

import pytest
from argus_core.models.flag_change import FlagChange
from argus_testkit.assertions import Assertion, all_of
from argus_testkit.scenario import Scenario
from write_mcp_client import get_recent_flag_changes, set_feature_flag

from write_mcp_client_test.fake_feature_flag_provider import FakeUnleashHandler, a_running_write_mcp


@pytest.fixture
def running_write_mcp() -> Iterator[type[FakeUnleashHandler]]:
    """A fake flag provider and a real `write_mcp_server` process in front of
    it, for the length of one test."""
    with a_running_write_mcp() as provider:
        yield provider


@pytest.mark.integration
def test_switching_a_flag_off_reaches_the_provider_through_the_real_write_server(
    running_write_mcp: type[FakeUnleashHandler]
) -> None:
    # The whole path in one call: the typed client, a real MCP round trip, the
    # tool, the admin adapter, and the provider's own wire shape - with only the
    # provider at the far end faked. And the assertion is on the provider's
    # state, not on what the client said: an action Argus reports taking and did
    # not take is the failure that matters.
    some_flag = "monthly-spend-feature"

    Scenario() \
        .given(
            the_provider_has_enabled(running_write_mcp, some_flag)
        ) \
        .when(
            lambda: set_feature_flag(some_flag, enabled=False)
        ) \
        .then(all_of(
            the_undo_descriptor_says_it_had_been(enabled=True),
            the_provider_now_reports_enabled(running_write_mcp, []),
        ))


@pytest.mark.integration
def test_switching_a_flag_on_reaches_the_provider_through_the_real_write_server(
    running_write_mcp: type[FakeUnleashHandler]
) -> None:
    # The direction a revert-only write tier could not perform, and the one an
    # incident caused by a flag being switched off needs.
    some_flag = "monthly-spend-feature"

    Scenario() \
        .given(
            the_provider_has_enabled(running_write_mcp)
        ) \
        .when(
            lambda: set_feature_flag(some_flag, enabled=True)
        ) \
        .then(all_of(
            the_undo_descriptor_says_it_had_been(enabled=False),
            the_provider_now_reports_enabled(running_write_mcp, [some_flag]),
        ))


@pytest.mark.integration
def test_reading_flag_changes_reaches_the_provider_through_the_real_write_server(
    running_write_mcp: type[FakeUnleashHandler]
) -> None:
    some_flag = "monthly-spend-feature"

    Scenario() \
        .given(
            the_provider_recorded(
                running_write_mcp,
                [a_disabling_of(some_flag, at=INSIDE_THE_WINDOW)],
            )
        ) \
        .when(
            lambda: get_recent_flag_changes(SINCE)
        ) \
        .then(
            the_changes_are([(some_flag, False)])
        )


@pytest.mark.integration
def test_a_change_the_client_made_can_be_undone_through_the_same_call(
    running_write_mcp: type[FakeUnleashHandler]
) -> None:
    # Undoing a refuted mitigation is this same tool with the state reversed,
    # which is the only reason one tool serves both directions. If the round
    # trip only worked one way, a refuted action could not be put back.
    some_flag = "monthly-spend-feature"

    Scenario() \
        .given(
            the_provider_has_enabled(running_write_mcp, some_flag)
        ) \
        .when(
            lambda: _undoing(set_feature_flag(some_flag, enabled=False), some_flag)
        ) \
        .then(
            the_provider_now_reports_enabled(running_write_mcp, [some_flag])
        )


SINCE = "2026-08-20T11:00:00Z"
INSIDE_THE_WINDOW = "2026-08-20T11:04:38.033Z"
DONT_CARE_ACTOR = "dont-care-actor"


def _undoing(undo_descriptor: dict[str, Any], flag: str) -> dict[str, Any]:
    return set_feature_flag(flag, enabled=bool(undo_descriptor["was_enabled"]))


def the_provider_has_enabled(handler: type[FakeUnleashHandler],
                             *flags: str) -> Callable[[], None]:
    def step() -> None:
        handler.enabled_flags = set(flags)

    return step


def the_provider_recorded(handler: type[FakeUnleashHandler],
                          events: list[dict[str, Any]]) -> Callable[[], None]:
    def step() -> None:
        handler.events = events

    return step


def a_disabling_of(flag: str, at: str) -> dict[str, Any]:
    """One row of the provider's event log, in its own wire shape."""
    return {
        "id": 11,
        "type": "feature-environment-disabled",
        "createdBy": DONT_CARE_ACTOR,
        "createdAt": at,
        "featureName": flag,
        "project": "default",
        "environment": "production",
    }


def the_undo_descriptor_says_it_had_been(enabled: bool) -> Assertion[dict[str, Any]]:
    def assertion(undo_descriptor: dict[str, Any]) -> bool:
        actual = undo_descriptor.get("was_enabled")
        if actual is not enabled:
            raise AssertionError(f"Expected was_enabled {enabled}, got {actual}.")

        return True

    return assertion


def the_provider_now_reports_enabled(handler: type[FakeUnleashHandler],
                                     expected: list[str]) -> Assertion[object]:
    def assertion(dont_care_result: object) -> bool:
        actual = sorted(handler.enabled_flags)
        if actual != sorted(expected):
            raise AssertionError(f"Expected enabled flags {sorted(expected)}, got {actual}.")

        return True

    return assertion


def the_changes_are(expected: list[tuple[str, bool]]) -> Assertion[list[FlagChange]]:
    def assertion(changes: list[FlagChange]) -> bool:
        actual = [(change.flag, change.enabled) for change in changes]
        if actual != expected:
            raise AssertionError(f"Expected changes {expected}, got {actual}.")

        return True

    return assertion
