from __future__ import annotations

from typing import Any
from unittest.mock import create_autospec

import httpx
import pytest
from argus_core.config import Settings
from argus_testkit.assertions import an_error_was_raised
from argus_testkit.scenario import Scenario, attempting
from read_mcp_server.flags import (
    FlagProviderUnavailable,
    enabled_flags,
    fetch_evaluated_toggles,
)


@pytest.mark.unit
def test_an_enabled_flag_is_reported() -> None:
    some_flag = "monthly-spend-feature"
    provider = a_mock_flag_provider()
    provider.return_value = [a_toggle(some_flag)]

    assert enabled_flags(fetch=provider) == [some_flag]


@pytest.mark.unit
def test_every_enabled_flag_is_reported() -> None:
    some_flag = "monthly-spend-feature"
    some_other_flag = "recommendations-v2"
    provider = a_mock_flag_provider()
    provider.return_value = [a_toggle(some_flag), a_toggle(some_other_flag)]

    assert enabled_flags(fetch=provider) == [some_flag, some_other_flag]


@pytest.mark.unit
def test_a_flag_the_provider_does_not_mention_is_not_enabled() -> None:
    # The provider answers with the flags that evaluate true; one that is off is
    # absent from the response rather than present and false. A reader that
    # looked for `enabled: false` would find nothing and report every flag as on.
    provider = a_mock_flag_provider()
    provider.return_value = []

    assert enabled_flags(fetch=provider) == []


@pytest.mark.unit
def test_a_flag_reported_as_not_enabled_is_not_reported() -> None:
    dont_care_flag = "monthly-spend-feature"
    provider = a_mock_flag_provider()
    provider.return_value = [a_toggle(dont_care_flag, enabled=False)]

    assert enabled_flags(fetch=provider) == []


@pytest.mark.unit
def test_an_unreachable_provider_raises_rather_than_reporting_nothing_enabled() -> None:
    # "Could not ask" and "nothing is on" are opposite facts. Mitigation reads
    # this to decide which flag to revert; an outage reported as an empty list
    # would look like an environment with no flag to revert at all.
    some_transport_error = httpx.ConnectError("connection refused")
    get = a_mock_http_get()
    get.side_effect = some_transport_error

    Scenario() \
        .when(
            attempting(lambda: fetch_evaluated_toggles(settings=some_settings(), get=get))
        ) \
        .then(
            an_error_was_raised(FlagProviderUnavailable)
        )


@pytest.mark.unit
def test_an_error_response_raises_rather_than_reporting_nothing_enabled() -> None:
    get = a_mock_http_get()
    get.return_value = httpx.Response(
        status_code=401,
        json={"error": "unauthorized"},
        request=httpx.Request("GET", "http://flags.invalid/api/frontend"),
    )

    Scenario() \
        .when(
            attempting(lambda: fetch_evaluated_toggles(settings=some_settings(), get=get))
        ) \
        .then(
            an_error_was_raised(FlagProviderUnavailable)
        )


@pytest.mark.unit
def test_the_evaluation_credential_is_the_one_sent() -> None:
    # The read tier holds the evaluation token and no other. If this call ever
    # started authenticating with something that could change a flag, the tier
    # split would be a comment rather than a property of the process.
    some_frontend_token = "default:production.some-frontend-token"
    settings = some_settings(frontend_token=some_frontend_token)
    get = a_mock_http_get()
    get.return_value = httpx.Response(
        status_code=200,
        json={"toggles": []},
        request=httpx.Request("GET", "http://flags.invalid/api/frontend"),
    )

    fetch_evaluated_toggles(settings=settings, get=get)

    assert get.call_args.kwargs["headers"]["Authorization"] == some_frontend_token


def some_settings(frontend_token: str = "default:production.dont-care-token") -> Settings:
    return Settings(
        unleash_base_url="http://flags.invalid",
        unleash_frontend_token=frontend_token,
    )


def a_toggle(name: str, enabled: bool = True) -> dict[str, Any]:
    return {"name": name, "enabled": enabled, "variant": {"name": "disabled"}}


def a_mock_flag_provider() -> Any:
    return create_autospec(fetch_evaluated_toggles)


def a_mock_http_get() -> Any:
    return create_autospec(httpx.get)
