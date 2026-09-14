"""What the provider's answer means, and what an unanswered question must not become.

Two layers, tested apart because they fail for different reasons. Reading the
answer is where "off" being an absence rather than a false is decided; making
the request is where a credential, a URL and an outage live.

The credential test is the one that guards the tier. `argus-read-mcp` holds a
token that can evaluate flags and cannot change one, and the type it is handed
has no field an admin token could arrive in - so the only way to send the wrong
credential is to change both this test and `FlagReadSettings`.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import create_autospec

import httpx
import pytest
from argus_testkit import Assertion, Scenario, an_error_was_raised, attempting
from read_mcp_server.flags import (
    FetchToggles,
    FlagProviderUnavailable,
    FlagReadSettings,
    enabled_flags,
    fetch_evaluated_toggles,
)


@pytest.mark.unit
def test_an_enabled_flag_is_reported() -> None:
    Scenario() \
        .given(
            some_flag := "monthly-spend-feature",
            provider := _a_flag_provider_reporting(_a_toggle(some_flag))
        ) \
        .when(
            lambda: enabled_flags(fetch=provider)
        ) \
        .then(
            _the_flags_reported_are([some_flag])
        )


@pytest.mark.unit
def test_every_enabled_flag_is_reported() -> None:
    Scenario() \
        .given(
            some_flag := "monthly-spend-feature",
            some_other_flag := "recommendations-v2",
            provider := _a_flag_provider_reporting(
                _a_toggle("monthly-spend-feature"),
                _a_toggle("recommendations-v2")
            )
        ) \
        .when(
            lambda: enabled_flags(fetch=provider)
        ) \
        .then(
            _the_flags_reported_are([some_flag, some_other_flag])
        )


@pytest.mark.unit
def test_a_flag_the_provider_does_not_mention_is_not_enabled() -> None:
    # The provider answers with the flags that evaluate true; one that is off is
    # absent from the response rather than present and false. A reader that
    # looked for `enabled: false` would find nothing and report every flag as on.
    Scenario() \
        .given(
            provider := _a_flag_provider_reporting()
        ) \
        .when(
            lambda: enabled_flags(fetch=provider)
        ) \
        .then(
            _the_flags_reported_are([])
        )


@pytest.mark.unit
def test_a_flag_reported_as_not_enabled_is_not_reported() -> None:
    Scenario() \
        .given(
            dont_care_flag := "monthly-spend-feature",
            provider := _a_flag_provider_reporting(
                _a_toggle(dont_care_flag, enabled=False)
            )
        ) \
        .when(
            lambda: enabled_flags(fetch=provider)
        ) \
        .then(
            _the_flags_reported_are([])
        )


@pytest.mark.unit
def test_an_unreachable_provider_raises_rather_than_reporting_nothing_enabled() -> None:
    # "Could not ask" and "nothing is on" are opposite facts. Mitigation reads
    # this to decide which flag to revert; an outage reported as an empty list
    # would look like an environment with no flag to revert at all.
    Scenario() \
        .given(
            some_transport_error := httpx.ConnectError("connection refused"),
            get := _a_mock_http_get(raises=some_transport_error)
        ) \
        .when(
            attempting(
                lambda: fetch_evaluated_toggles(settings=_some_settings(), get=get)
            )
        ) \
        .then(
            an_error_was_raised(FlagProviderUnavailable)
        )


@pytest.mark.unit
def test_an_error_response_raises_rather_than_reporting_nothing_enabled() -> None:
    Scenario() \
        .given(
            get := _a_mock_http_get(answers=_a_response(status_code=401,
                                                        body={"error": "unauthorized"}))
        ) \
        .when(
            attempting(
                lambda: fetch_evaluated_toggles(settings=_some_settings(), get=get)
            )
        ) \
        .then(
            an_error_was_raised(FlagProviderUnavailable)
        )


@pytest.mark.unit
def test_the_evaluation_credential_is_the_one_sent() -> None:
    # The read tier holds the evaluation token and no other. If this call ever
    # started authenticating with something that could change a flag, the tier
    # split would be a comment rather than a property of the process.
    Scenario() \
        .given(
            some_frontend_token := "default:production.some-frontend-token",
            settings := _some_settings(frontend_token=some_frontend_token),
            get := _a_mock_http_get(answers=_a_response(status_code=200,
                                                        body={"toggles": []}))
        ) \
        .when(
            lambda: fetch_evaluated_toggles(settings=settings, get=get)
        ) \
        .then(
            _the_credential_sent_was(some_frontend_token, by=get)
        )


def _some_settings(
    frontend_token: str = "default:production.dont-care-token"
) -> FlagReadSettings:
    return FlagReadSettings(
        unleash_base_url="http://flags.invalid",
        unleash_frontend_token=frontend_token
    )


def _a_toggle(name: str, enabled: bool = True) -> dict[str, Any]:
    return {"name": name, "enabled": enabled, "variant": {"name": "disabled"}}


def _a_response(status_code: int, body: dict[str, Any]) -> httpx.Response:
    return httpx.Response(
        status_code=status_code,
        json=body,
        request=httpx.Request("GET", "http://flags.invalid/api/frontend")
    )


def _a_flag_provider_reporting(*toggles: dict[str, Any]) -> Any:
    """A stand-in for whatever asks the provider, answering exactly these.

    Spec'd against `FetchToggles` rather than against the real fetcher: the
    fetcher takes the credential it sends, and what reads its answer is handed
    something that takes nothing at all. Specing against the concrete function
    would be specing against the wrong shape.
    """
    provider = create_autospec(FetchToggles, instance=True)
    provider.return_value = list(toggles)

    return provider


def _a_mock_http_get(answers: httpx.Response | None = None,
                     raises: Exception | None = None) -> Any:
    """A stand-in transport, already answering the way the test needs.

    Built armed rather than armed afterwards, so that a `given` states the
    whole world in one expression instead of a value and then a statement
    about it.
    """
    get = create_autospec(httpx.get)

    if raises is not None:
        get.side_effect = raises
    else:
        get.return_value = answers

    return get


def _the_flags_reported_are(expected: list[str]) -> Assertion[list[str]]:
    def the_flags_reported_are(reported: list[str]) -> bool:
        if reported != expected:
            raise AssertionError(
                f"expected the flags reported to be {expected}, "
                f"and they were {reported}"
            )

        return True

    return the_flags_reported_are


def _the_credential_sent_was(expected: str, by: Any) -> Assertion[Any]:
    """That the header carried this token and no other.

    Read off `call_args` rather than through `assert_called_with`, which does
    not survive a spec built from a `Protocol`: the `self` parameter is left on
    the signature, so every comparison fails while printing identically.
    """
    def the_credential_sent_was(dont_care_result: Any) -> bool:
        sent = by.call_args.kwargs["headers"]["Authorization"]

        if sent != expected:
            raise AssertionError(
                f"expected the evaluation credential [{expected}] to be sent, "
                f"and what went was [{sent}]"
            )

        return True

    return the_credential_sent_was
