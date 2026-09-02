from __future__ import annotations

from typing import Any
from unittest.mock import create_autospec

import httpx
import pytest
from argus_core.config import Settings
from argus_testkit.assertions import an_error_was_raised
from argus_testkit.scenario import Scenario, attempting
from write_mcp_server.flag_state import FlagNotSet, evaluated_flags, set_flag


@pytest.mark.unit
def test_setting_a_flag_off_addresses_its_environment() -> None:
    some_flag = "monthly-spend-feature"
    some_project = "default"
    some_environment = "production"
    provider = a_flag_provider_reporting([])

    set_flag(
        some_flag,
        enabled=False,
        settings=some_settings(project=some_project, environment=some_environment),
        post=provider.post,
        evaluate=provider.evaluate,
    )

    assert provider.post.call_args.args[0].endswith(
        f"/api/admin/projects/{some_project}/features/{some_flag}"
        f"/environments/{some_environment}/off"
    )


@pytest.mark.unit
def test_setting_a_flag_on_addresses_its_environment() -> None:
    # The direction that did not exist before. An incident can be caused by a
    # flag being withdrawn - a fallback disabled, traffic moved back to a path
    # that has since rotted - and an agent that can only turn flags off cannot
    # mitigate that incident at all.
    some_flag = "monthly-spend-feature"
    some_project = "default"
    some_environment = "production"
    provider = a_flag_provider_reporting([some_flag])

    set_flag(
        some_flag,
        enabled=True,
        settings=some_settings(project=some_project, environment=some_environment),
        post=provider.post,
        evaluate=provider.evaluate,
    )

    assert provider.post.call_args.args[0].endswith(
        f"/api/admin/projects/{some_project}/features/{some_flag}"
        f"/environments/{some_environment}/on"
    )


@pytest.mark.unit
def test_setting_a_flag_uses_the_credential_that_can_change_state() -> None:
    # The write tier exists to hold this one. A change authenticating with the
    # evaluation credential would fail against a real provider, and the tier
    # split would be describing a boundary the code does not actually use.
    some_admin_token = "*:*.some-admin-token"
    provider = a_flag_provider_reporting([])

    set_flag(
        DONT_CARE_FLAG,
        enabled=False,
        settings=some_settings(admin_token=some_admin_token),
        post=provider.post,
        evaluate=provider.evaluate,
    )

    assert provider.post.call_args.kwargs["headers"]["Authorization"] == some_admin_token


@pytest.mark.unit
def test_setting_a_flag_off_returns_only_once_it_evaluates_off() -> None:
    # A toggle is not instantly visible through the evaluation API. Returning
    # before it is would hand Mitigation a window in which it reads the old
    # value and refutes a hypothesis that was right.
    provider = a_flag_provider()
    provider.evaluate.side_effect = [[DONT_CARE_FLAG], [DONT_CARE_FLAG], []]

    set_flag(
        DONT_CARE_FLAG,
        enabled=False,
        settings=some_settings(),
        post=provider.post,
        evaluate=provider.evaluate,
    )

    assert provider.evaluate.call_count == 3


@pytest.mark.unit
def test_setting_a_flag_on_returns_only_once_it_evaluates_on() -> None:
    provider = a_flag_provider()
    provider.evaluate.side_effect = [[], [], [DONT_CARE_FLAG]]

    set_flag(
        DONT_CARE_FLAG,
        enabled=True,
        settings=some_settings(),
        post=provider.post,
        evaluate=provider.evaluate,
    )

    assert provider.evaluate.call_count == 3


@pytest.mark.unit
def test_a_flag_that_never_reaches_the_requested_state_is_not_reported_as_set() -> None:
    provider = a_flag_provider_reporting([DONT_CARE_FLAG])

    Scenario() \
        .when(
            attempting(
                lambda: set_flag(
                    DONT_CARE_FLAG,
                    enabled=False,
                    settings=some_settings(),
                    post=provider.post,
                    evaluate=provider.evaluate,
                )
            )
        ) \
        .then(
            an_error_was_raised(FlagNotSet)
        )


@pytest.mark.unit
def test_an_unreachable_provider_is_not_reported_as_set() -> None:
    some_transport_error = httpx.ConnectError("connection refused")
    provider = a_flag_provider_reporting([])
    provider.post.side_effect = some_transport_error

    Scenario() \
        .when(
            attempting(
                lambda: set_flag(
                    DONT_CARE_FLAG,
                    enabled=False,
                    settings=some_settings(),
                    post=provider.post,
                    evaluate=provider.evaluate,
                )
            )
        ) \
        .then(
            an_error_was_raised(FlagNotSet)
        )


@pytest.mark.unit
def test_switching_a_flag_off_records_that_it_had_been_on() -> None:
    # The descriptor names the state to restore, not the call that would
    # restore it: a tool renamed or resignatured later would leave the second
    # kind of record pointing at nothing.
    some_flag = "monthly-spend-feature"
    some_environment = "production"
    provider = a_flag_provider_reporting([])

    undo = set_flag(
        some_flag,
        enabled=False,
        settings=some_settings(environment=some_environment),
        post=provider.post,
        evaluate=provider.evaluate,
    )

    assert undo["flag"] == some_flag
    assert undo["environment"] == some_environment
    assert undo["was_enabled"] is True


@pytest.mark.unit
def test_switching_a_flag_on_records_that_it_had_been_off() -> None:
    # The undo of a mitigation that undid a switch-off. Recording `was_enabled`
    # as true here - as a revert-only tool would have to - would have the undo
    # leave the flag in the state that caused the incident.
    provider = a_flag_provider_reporting([DONT_CARE_FLAG])

    undo = set_flag(
        DONT_CARE_FLAG,
        enabled=True,
        settings=some_settings(),
        post=provider.post,
        evaluate=provider.evaluate,
    )

    assert undo["was_enabled"] is False


DONT_CARE_FLAG = "dont-care-flag"


class _FlagProvider:
    def __init__(self) -> None:
        self.post: Any = create_autospec(httpx.post)
        self.evaluate: Any = create_autospec(evaluated_flags)


def a_flag_provider() -> _FlagProvider:
    provider = _FlagProvider()
    provider.post.return_value = httpx.Response(
        status_code=200,
        json={},
        request=httpx.Request("POST", "http://flags.invalid/"),
    )
    return provider


def a_flag_provider_reporting(enabled_flags: list[str]) -> _FlagProvider:
    provider = a_flag_provider()
    provider.evaluate.return_value = enabled_flags
    return provider


def some_settings(project: str = "default",
                  environment: str = "production",
                  admin_token: str = "*:*.dont-care-admin-token") -> Settings:
    return Settings(
        unleash_base_url="http://flags.invalid",
        unleash_project=project,
        unleash_environment=environment,
        unleash_admin_token=admin_token,
    )
