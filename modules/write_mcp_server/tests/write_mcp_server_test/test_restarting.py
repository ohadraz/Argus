from __future__ import annotations

from typing import Any
from unittest.mock import create_autospec

import httpx
import pytest
from argus_core.models import RestartedService
from argus_testkit import (
    Assertion,
    Scenario,
    all_of,
    an_error_was_raised,
    attempting,
    dont_care_sleep,
)
from write_mcp_server.restarting import (
    RESTART_ACTION,
    RESTART_GROUP,
    RESTART_KIND,
    ObserveStartTime,
    RestartSettings,
    ServiceNotRestarted,
    restart_service,
    the_process_start_time,
)

DONT_CARE_SERVICE = "dont-care-service"
DONT_CARE_URL = "http://argocd.invalid/"
SOME_ACTION_PATH = "/api/v1/applications/{application}/resource/actions/v2"

# Two readings of the gauge that are unmistakably different processes, in
# seconds since the epoch, because that is what the metric is. What separates
# them is that they differ - not how far apart they are, and not which is
# later, since the two clocks involved are not the same clock.
THE_PROCESS_THAT_WAS_SERVING = 1_756_000_000.0
THE_PROCESS_THAT_CAME_UP = 1_756_000_600.0


@pytest.mark.unit
def test_a_restart_is_asked_for_as_the_action_the_platform_registers_it_under() -> None:
    # A restart is not an endpoint. The platform runs a script registered
    # against a kind of resource, and what dispatches to it is the whole of
    # group, kind, namespace, name and action - a request missing one of them
    # is a request that reaches no script at all.
    some_namespace = "kuki-production"
    some_resource_name = "kuki-shop"
    platform = a_platform()

    Scenario() \
        .given(platform) \
        .when(
            lambda: restart_service(
                DONT_CARE_SERVICE,
                settings=some_settings(namespace=some_namespace,
                                       resource_name=some_resource_name),
                post=platform.post,
                observe=platform.observe,
                sleep=dont_care_sleep
            )
        ) \
        .then(
            _the_action_asked_for_is(
                {
                    "namespace": some_namespace,
                    "resourceName": some_resource_name,
                    "group": RESTART_GROUP,
                    "kind": RESTART_KIND,
                    "action": RESTART_ACTION
                },
                platform
            )
        )


@pytest.mark.unit
def test_a_restart_is_addressed_to_the_application_it_names() -> None:
    # The service Argus names is what the alert and the metrics name, and the
    # path is where that name becomes the platform's own. Configured as a
    # template rather than built here, so the demo's stand-in and a real
    # server are one setting with two values.
    some_service = "kuki-service"
    some_base_url = "http://argocd.kuki.com"
    platform = a_platform()

    Scenario() \
        .given(platform) \
        .when(
            lambda: restart_service(
                some_service,
                settings=some_settings(base_url=some_base_url),
                post=platform.post,
                observe=platform.observe,
                sleep=dont_care_sleep
            )
        ) \
        .then(
            _the_application_addressed_is(
                f"{some_base_url}/api/v1/applications/{some_service}"
                f"/resource/actions/v2",
                platform
            )
        )


@pytest.mark.unit
def test_a_restart_is_asked_for_under_the_credential_that_can_change_state() -> None:
    # The write tier exists to hold this one, exactly as the flag write does.
    some_token = "dont-care-looking-but-load-bearing-token"
    platform = a_platform()

    Scenario() \
        .given(platform) \
        .when(
            lambda: restart_service(
                DONT_CARE_SERVICE,
                settings=some_settings(auth_token=some_token),
                post=platform.post,
                observe=platform.observe,
                sleep=dont_care_sleep
            )
        ) \
        .then(
            _the_credential_sent_is(f"Bearer {some_token}", platform)
        )


@pytest.mark.unit
def test_a_platform_that_takes_no_credential_is_sent_no_header_at_all() -> None:
    # `Bearer ` with nothing after it is a malformed credential, not an absent
    # one, and a server that takes none - the demo's stand-in does - would
    # refuse it. Absence has to be absence.
    no_token_at_all = ""
    platform = a_platform()

    Scenario() \
        .given(platform) \
        .when(
            lambda: restart_service(
                DONT_CARE_SERVICE,
                settings=some_settings(auth_token=no_token_at_all),
                post=platform.post,
                observe=platform.observe,
                sleep=dont_care_sleep
            )
        ) \
        .then(
            _no_credential_was_sent(platform)
        )


@pytest.mark.unit
def test_a_restart_returns_only_once_a_new_process_is_serving() -> None:
    # The action returns as soon as the platform has patched the template,
    # which is before a single pod has rolled. A caller that trusted the POST
    # would re-read the metrics against the process that is still leaking,
    # watch memory stay where it was, and refute a hypothesis that was right.
    platform = a_platform_that_rolls_after(stale_readings=2)

    Scenario() \
        .given(platform) \
        .when(
            lambda: restart_service(
                DONT_CARE_SERVICE,
                settings=some_settings(),
                post=platform.post,
                observe=platform.observe,
                sleep=dont_care_sleep
            )
        ) \
        .then(all_of(
            _the_service_was_looked_at(times=4, platform=platform),
            _the_process_that_came_up_is(DONT_CARE_SERVICE, THE_PROCESS_THAT_CAME_UP)
        ))


@pytest.mark.unit
def test_a_restart_answers_with_the_process_that_came_up() -> None:
    # The whole reason this returns a value rather than an acknowledgement: a
    # restart that was accepted and never happened is indistinguishable, from
    # the symptoms alone, from one that happened and did not help.
    some_service = "kuki-service"
    platform = a_platform()

    Scenario() \
        .given(platform) \
        .when(
            lambda: restart_service(
                some_service,
                settings=some_settings(),
                post=platform.post,
                observe=platform.observe,
                sleep=dont_care_sleep
            )
        ) \
        .then(
            _the_process_that_came_up_is(some_service, THE_PROCESS_THAT_CAME_UP)
        )


@pytest.mark.unit
def test_a_platform_that_refuses_the_action_is_not_reported_as_restarted() -> None:
    platform = a_platform_that_refuses_the_action()

    Scenario() \
        .given(platform) \
        .when(
            attempting(
                lambda: restart_service(
                    DONT_CARE_SERVICE,
                    settings=some_settings(),
                    post=platform.post,
                    observe=platform.observe,
                    sleep=dont_care_sleep
                )
            )
        ) \
        .then(
            an_error_was_raised(ServiceNotRestarted)
        )


@pytest.mark.unit
def test_an_unreachable_platform_is_not_reported_as_restarted() -> None:
    platform = a_platform_that_cannot_be_reached()

    Scenario() \
        .given(platform) \
        .when(
            attempting(
                lambda: restart_service(
                    DONT_CARE_SERVICE,
                    settings=some_settings(),
                    post=platform.post,
                    observe=platform.observe,
                    sleep=dont_care_sleep
                )
            )
        ) \
        .then(
            an_error_was_raised(ServiceNotRestarted)
        )


@pytest.mark.unit
def test_a_service_still_served_by_the_same_process_is_not_reported_as_restarted() -> None:
    # The rollout that never completed, and the one failure this is really
    # guarding: the platform said yes, and nothing happened. Reported
    # optimistically it would have Mitigation read a leak still climbing as
    # evidence that restarting does not help.
    platform = a_platform_whose_process_never_changes()

    Scenario() \
        .given(platform) \
        .when(
            attempting(
                lambda: restart_service(
                    DONT_CARE_SERVICE,
                    settings=some_settings(),
                    post=platform.post,
                    observe=platform.observe,
                    sleep=dont_care_sleep
                )
            )
        ) \
        .then(
            an_error_was_raised(ServiceNotRestarted)
        )


@pytest.mark.unit
def test_a_service_that_reported_no_process_before_is_taken_at_its_first_reading_after() -> None:
    # Nothing to see a change against, so there is no change to wait for. A
    # service that was reporting no start time at all is one whose first
    # reading after the action is the only answer available - waiting for that
    # reading to differ from nothing would wait for ever.
    platform = a_platform_serving_nothing_before()

    Scenario() \
        .given(platform) \
        .when(
            lambda: restart_service(
                DONT_CARE_SERVICE,
                settings=some_settings(),
                post=platform.post,
                observe=platform.observe,
                sleep=dont_care_sleep
            )
        ) \
        .then(all_of(
            _the_service_was_looked_at(times=2, platform=platform),
            _the_process_that_came_up_is(DONT_CARE_SERVICE, THE_PROCESS_THAT_CAME_UP)
        ))


@pytest.mark.unit
def test_a_service_that_cannot_be_read_after_the_action_is_not_reported_as_restarted() -> None:
    # Unconfirmed is not confirmed. The action may well have landed, but
    # nothing here saw it land, and every caller above this treats the answer
    # as evidence that it did.
    platform = a_platform_whose_gauge_fails_after_the_action()

    Scenario() \
        .given(platform) \
        .when(
            attempting(
                lambda: restart_service(
                    DONT_CARE_SERVICE,
                    settings=some_settings(),
                    post=platform.post,
                    observe=platform.observe,
                    sleep=dont_care_sleep
                )
            )
        ) \
        .then(
            an_error_was_raised(ServiceNotRestarted)
        )


@pytest.mark.unit
def test_the_process_serving_now_is_read_from_the_latest_minute() -> None:
    # An older bucket describes the process that was, which is precisely the
    # reading a restart has to be told apart from.
    dont_care_earlier_minute = {"process_start_time_seconds": THE_PROCESS_THAT_WAS_SERVING}
    the_latest_minute = {"process_start_time_seconds": THE_PROCESS_THAT_CAME_UP}

    Scenario() \
        .given(a_service := a_service_reporting([dont_care_earlier_minute, the_latest_minute])) \
        .when(lambda: the_process_start_time(some_settings(), get=a_service)()) \
        .then(_the_start_time_read_is(THE_PROCESS_THAT_CAME_UP))


@pytest.mark.unit
def test_a_service_reporting_no_minutes_has_no_process_that_can_be_seen() -> None:
    # Different from a service that reports it has not restarted: one is a
    # reading, the other is the absence of one, and only the second leaves the
    # restart unconfirmable.
    Scenario() \
        .given(a_service_reporting_nothing := a_service_reporting([])) \
        .when(lambda: the_process_start_time(some_settings(), get=a_service_reporting_nothing)()) \
        .then(_the_start_time_read_is(None))


@pytest.mark.unit
def test_a_minute_that_does_not_carry_a_start_time_reports_none() -> None:
    a_minute_reporting_only_traffic = {"error_rate": 0.01}

    Scenario() \
        .given(a_service := a_service_reporting([a_minute_reporting_only_traffic])) \
        .when(lambda: the_process_start_time(some_settings(), get=a_service)()) \
        .then(_the_start_time_read_is(None))


def _the_action_asked_for_is(expected: dict[str, str],
                             platform: _Platform) -> Assertion[object]:
    def assertion(dont_care_result: object) -> bool:
        asked_for = platform.post.call_args.kwargs["json"]
        if asked_for != expected:
            raise AssertionError(
                f"Expected the restart to be asked for as {expected}, "
                f"and it was asked for as {asked_for}."
            )

        return True

    return assertion


def _the_application_addressed_is(expected: str, platform: _Platform) -> Assertion[object]:
    def assertion(dont_care_result: object) -> bool:
        addressed = platform.post.call_args.args[0]
        if addressed != expected:
            raise AssertionError(
                f"Expected the restart to be asked of [{expected}], "
                f"and it was asked of [{addressed}]."
            )

        return True

    return assertion


def _the_credential_sent_is(expected: str, platform: _Platform) -> Assertion[object]:
    def assertion(dont_care_result: object) -> bool:
        sent = platform.post.call_args.kwargs["headers"].get("Authorization")
        if sent != expected:
            raise AssertionError(
                f"Expected the restart to be asked for under [{expected}], "
                f"and it was asked for under [{sent}]."
            )

        return True

    return assertion


def _no_credential_was_sent(platform: _Platform) -> Assertion[object]:
    def assertion(dont_care_result: object) -> bool:
        headers = platform.post.call_args.kwargs["headers"]
        if "Authorization" in headers:
            raise AssertionError(
                f"Expected no credential to be sent at all, and "
                f"[{headers['Authorization']}] was."
            )

        return True

    return assertion


def _the_service_was_looked_at(times: int, platform: _Platform) -> Assertion[object]:
    def assertion(dont_care_result: object) -> bool:
        looks = platform.observe.call_count
        if looks != times:
            raise AssertionError(
                f"Expected the service to be looked at {times} times, "
                f"and it was looked at {looks}."
            )

        return True

    return assertion


def _the_process_that_came_up_is(service: str,
                                 started_at: float) -> Assertion[RestartedService]:
    def assertion(restarted: RestartedService) -> bool:
        expected = RestartedService(service=service, process_start_time_seconds=started_at)
        if restarted != expected:
            raise AssertionError(
                f"Expected the restart to answer with {expected}, "
                f"and it answered with {restarted}."
            )

        return True

    return assertion


def _the_start_time_read_is(expected: float | None) -> Assertion[float | None]:
    def assertion(started_at: float | None) -> bool:
        if started_at != expected:
            raise AssertionError(
                f"Expected the process serving now to be read as [{expected}], "
                f"and it was read as [{started_at}]."
            )

        return True

    return assertion


class _Platform:
    """The deployment platform, and the gauge that says what is serving.

    One stand-in rather than two, because no test here needs only one of them:
    a restart is asked of the platform and confirmed against the gauge, and a
    test that stood in only the first would be waiting on a real service.
    """

    def __init__(self) -> None:
        self.post: Any = create_autospec(httpx.post)
        # Spec'd against the port rather than `httpx.get`: what confirms the
        # restart is a reading, and where it is read from is bound once, where
        # the server is built.
        self.observe: Any = create_autospec(ObserveStartTime, instance=True)


def a_platform() -> _Platform:
    """A platform that accepts the action, serving a process that then rolls."""
    platform = _Platform()
    platform.post.return_value = httpx.Response(
        status_code=200,
        json={},
        request=httpx.Request("POST", DONT_CARE_URL)
    )
    platform.observe.side_effect = [
        THE_PROCESS_THAT_WAS_SERVING, THE_PROCESS_THAT_CAME_UP
    ]

    return platform


def a_platform_that_rolls_after(stale_readings: int) -> _Platform:
    """A rollout that takes a few looks to arrive, as every real one does."""
    platform = a_platform()
    platform.observe.side_effect = (
        [THE_PROCESS_THAT_WAS_SERVING] * (stale_readings + 1)
        + [THE_PROCESS_THAT_CAME_UP]
    )

    return platform


def a_platform_whose_process_never_changes() -> _Platform:
    platform = a_platform()
    platform.observe.side_effect = None
    platform.observe.return_value = THE_PROCESS_THAT_WAS_SERVING

    return platform


def a_platform_serving_nothing_before() -> _Platform:
    platform = a_platform()
    platform.observe.side_effect = [None, THE_PROCESS_THAT_CAME_UP]

    return platform


def a_platform_whose_gauge_fails_after_the_action() -> _Platform:
    platform = a_platform()
    platform.observe.side_effect = [
        THE_PROCESS_THAT_WAS_SERVING, httpx.ConnectError("connection refused")
    ]

    return platform


def a_platform_that_refuses_the_action() -> _Platform:
    platform = a_platform()
    platform.post.return_value = httpx.Response(
        status_code=403,
        json={"error": "permission denied"},
        request=httpx.Request("POST", DONT_CARE_URL)
    )

    return platform


def a_platform_that_cannot_be_reached() -> _Platform:
    platform = a_platform()
    platform.post.side_effect = httpx.ConnectError("connection refused")

    return platform


def a_service_reporting(minutes: list[dict[str, Any]]) -> Any:
    """The metrics endpoint, answering with the window it was asked for."""
    get: Any = create_autospec(httpx.get)
    get.return_value = httpx.Response(
        status_code=200,
        json=minutes,
        request=httpx.Request("GET", DONT_CARE_URL)
    )

    return get


def some_settings(namespace: str = "dont-care-namespace",
                  resource_name: str = "dont-care-resource",
                  auth_token: str = "dont-care-token",
                  base_url: str = "http://argocd.invalid") -> RestartSettings:
    """Where a restart is asked for, as this suite configures it.

    Each test names only the field it is about. The path is never one of them:
    it is a template in every deployment, and the test that cares about it
    spells the result out rather than the shape.
    """
    dont_care_service_url = "http://kuki-service.invalid"

    return RestartSettings(
        argocd_base_url=base_url,
        argocd_restart_action_path=SOME_ACTION_PATH,
        argocd_auth_token=auth_token,
        restart_namespace=namespace,
        restart_resource_name=resource_name,
        target_service_url=dont_care_service_url
    )
