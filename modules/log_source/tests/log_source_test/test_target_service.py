"""The service's logs, as the demo Target Service serves them.

What the adapter decides is where it asks and what it does with an answer that
is not one. The address is the deployment's and the route the service's, and a
service answering an error must arrive as a failure - never as a service that
wrote nothing, which a window over it would read as a quiet incident.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import create_autospec

import httpx2
import pytest
from argus_testkit import (
    Assertion,
    Scenario,
    an_error_was_raised,
    attempting,
    calling,
    the_answer_was,
)
from log_source.target_service import LOGS_PATH, TargetServiceLogSettings, target_service_logs

SOME_ADDRESS = "http://target.invalid"
SOME_LINES = ["2026-11-25T09:00:00Z INFO GET /account 200",
              "2026-11-25T09:00:01Z ERROR GET /account 500"]


@pytest.mark.unit
def test_the_logs_are_asked_for_at_the_address_the_deployment_configured() -> None:
    get = _a_service_answering(SOME_LINES)

    Scenario() \
        .given(fetch := target_service_logs(_some_settings(SOME_ADDRESS), get=get)) \
        .when(lambda: fetch()) \
        .then(_the_url_asked_for(get, f"{SOME_ADDRESS}{LOGS_PATH}"))


@pytest.mark.unit
def test_the_lines_the_service_answered_are_what_comes_back() -> None:
    Scenario() \
        .given(fetch := target_service_logs(_some_settings(),
                                            get=_a_service_answering(SOME_LINES))) \
        .when(lambda: fetch()) \
        .then(the_answer_was(SOME_LINES))


@pytest.mark.unit
def test_a_service_answering_an_error_status_is_a_failure_not_an_empty_log() -> None:
    # "Could not ask" must never arrive as "it wrote nothing": a window cut out
    # of an empty log is a quiet minute, and a quiet minute is evidence.
    get = _a_service_answering(SOME_LINES)
    get.return_value.raise_for_status.side_effect = httpx2.HTTPError("500 Server Error")

    Scenario() \
        .given(fetch := target_service_logs(_some_settings(), get=get)) \
        .when(attempting(lambda: fetch())) \
        .then(an_error_was_raised(httpx2.HTTPError))


@pytest.mark.unit
@pytest.mark.parametrize("some_body", [
    pytest.param({"lines": SOME_LINES}, id="an-object"),
    pytest.param([len(SOME_LINES), len(SOME_LINES[0])], id="a-list-of-numbers")
])
def test_a_body_that_is_not_a_list_of_lines_is_a_failure_not_lines(some_body: object) -> None:
    # The port promises lines or a raise. A body of any other shape, handed on,
    # would be taken for the lines the service wrote.
    Scenario() \
        .given(fetch := target_service_logs(_some_settings(),
                                            get=_a_service_answering(some_body))) \
        .when(attempting(lambda: fetch())) \
        .then(an_error_was_raised(ValueError))


@pytest.mark.unit
def test_the_service_is_configured_by_the_variable_it_always_was(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    # The name a deployment already sets, unchanged by the move out of the
    # kernel's `Settings` - a renamed variable is a deployment that silently
    # falls back to its default.
    some_url = "http://kuki.invalid:8181"

    Scenario() \
        .given(
            calling(lambda: monkeypatch.setenv("TARGET_SERVICE_URL", some_url))
        ) \
        .when(lambda: TargetServiceLogSettings()) \
        .then(the_answer_was(TargetServiceLogSettings(target_service_url=some_url)))


@pytest.mark.unit
def test_an_unconfigured_service_is_the_demos() -> None:
    # The default the kernel's `Settings` declared before the setting moved,
    # spelled out because there is nothing left to derive it from. Read off
    # the declared default rather than off a `TargetServiceLogSettings()`,
    # which would read the developer's own environment.
    the_demos_service = "http://localhost:8080"

    Scenario() \
        .when(lambda: TargetServiceLogSettings.model_construct().model_dump()) \
        .then(the_answer_was({"target_service_url": the_demos_service}))


def _some_settings(address: str = SOME_ADDRESS) -> TargetServiceLogSettings:
    return TargetServiceLogSettings(target_service_url=address)


def _a_service_answering(body: object) -> Any:
    """The HTTP client's `get`, answering every request with `body`. `Any`
    because what a test needs back is both the call and the record of how it
    was made."""
    response = create_autospec(httpx2.Response, instance=True)
    response.json.return_value = body

    get = create_autospec(httpx2.get)
    get.return_value = response

    return get


def _the_url_asked_for(get: Any, expected: str) -> Assertion[Any]:
    def assertion(dont_care: Any) -> bool:
        asked = get.call_args.args[0] if get.call_args.args else None

        if asked != expected:
            raise AssertionError(
                f"Expected the service to be asked for [{expected}], and it was "
                f"asked for [{asked}]."
            )

        return True

    return assertion
