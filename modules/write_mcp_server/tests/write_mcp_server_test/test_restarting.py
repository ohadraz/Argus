"""Restarting a service through the platform, and confirming a new process serves.

What is worth pinning is the confirmation. The platform accepts a restart before a
single pod has rolled, so a restart is reported only once the start time of the
process serving the service has moved - and read for the service restarted, never
the one that was paged. Every way that confirmation can fail is a restart that did
not happen, as far as anything downstream may assume.

How Argo CD is asked - the action body, the tree, which pod is newest, the
credential - is the adapter's, and pinned in its own suite.
"""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import create_autospec

import pytest
from argus_core.mcp_transport import UNREACHABLE_PLATFORM_MARKER
from argus_core.models import RestartedService
from argus_testkit import (
    Assertion,
    Scenario,
    all_of,
    an_error_was_raised,
    attempting,
    calling,
    dont_care_sleep,
    one_record_was_logged,
)
from deployment_platform import (
    DeploymentPlatformWrites,
    PlatformRefused,
    PlatformUnreachable,
)
from write_mcp_server.restarting import ServiceNotRestarted, restart_service

DONT_CARE_SERVICE = "dont-care-service"

# Two start times that are unmistakably different processes, as seconds since the
# epoch - what a restart is confirmed by is a number that can be compared.
THE_PROCESS_THAT_WAS_SERVING = 1_787_223_600.0
THE_PROCESS_THAT_CAME_UP = 1_787_224_200.0


@pytest.mark.unit
def test_the_service_restarted_is_the_one_asked_about_not_a_configured_one() -> None:
    # The resource name used to be configuration, which was true for as long as
    # the only service Argus could restart was the one it was paged about. A
    # mitigation addressed at a dependency makes a fixed name actively wrong: the
    # platform would restart the wrong thing and report success.
    a_dependency_of_the_alerting_service = "kuki-pricing"
    platform = a_platform()

    Scenario() \
        .given(platform) \
        .when(lambda: restart_service(
            a_dependency_of_the_alerting_service, platform, sleep=dont_care_sleep
        )) \
        .then(_the_restart_was_asked_of(a_dependency_of_the_alerting_service, platform))


@pytest.mark.unit
def test_what_is_serving_is_read_before_the_restart_is_asked_for() -> None:
    # The reading before is what the reading after is compared against. Taken
    # after the action, it could already be the new process, and a restart that
    # landed would be waited on until it timed out.
    platform = a_platform()

    Scenario() \
        .given(platform) \
        .when(lambda: _restarting(platform)) \
        .then(_it_was_asked_in_order(
            platform, "newest_pod_started_at", "restart", "newest_pod_started_at"
        ))


@pytest.mark.unit
def test_a_restart_returns_only_once_a_new_process_is_serving() -> None:
    # The action returns as soon as the platform has patched the template,
    # which is before a single pod has rolled. A caller that trusted the action
    # would re-read the metrics against the process that is still leaking,
    # watch memory stay where it was, and refute a hypothesis that was right.
    platform = a_platform_that_rolls_after(stale_readings=2)

    Scenario() \
        .given(platform) \
        .when(lambda: _restarting(platform)) \
        .then(all_of(
            _the_service_was_looked_at(times=4, platform=platform),
            _the_process_that_came_up_is(DONT_CARE_SERVICE, THE_PROCESS_THAT_CAME_UP)
        ))


@pytest.mark.unit
def test_the_pod_looked_at_is_the_one_belonging_to_the_service_restarted() -> None:
    # The whole reason the confirmation moved off the metrics. A restart
    # addressed at a dependency has to be confirmed against that dependency's
    # pod: asked about the shop instead, the reading never moves, and a restart
    # that landed perfectly well is reported as one that never happened.
    a_dependency_of_the_alerting_service = "kuki-pricing"
    platform = a_platform()

    Scenario() \
        .given(platform) \
        .when(lambda: restart_service(
            a_dependency_of_the_alerting_service, platform, sleep=dont_care_sleep
        )) \
        .then(_every_look_was_at(a_dependency_of_the_alerting_service, platform))


@pytest.mark.unit
def test_a_restart_answers_with_the_process_that_came_up() -> None:
    # The whole reason this returns a value rather than an acknowledgement: a
    # restart that was accepted and never happened is indistinguishable, from
    # the symptoms alone, from one that happened and did not help.
    some_service = "kuki-service"
    platform = a_platform()

    Scenario() \
        .given(platform) \
        .when(lambda: restart_service(some_service, platform, sleep=dont_care_sleep)) \
        .then(_the_process_that_came_up_is(some_service, THE_PROCESS_THAT_CAME_UP))


@pytest.mark.unit
def test_a_platform_that_refuses_the_action_is_not_reported_as_restarted() -> None:
    platform = a_platform()
    platform.restart.side_effect = PlatformRefused("permission denied")

    Scenario() \
        .given(platform) \
        .when(attempting(lambda: _restarting(platform))) \
        .then(an_error_was_raised(ServiceNotRestarted))


@pytest.mark.unit
def test_an_unreachable_platform_is_not_reported_as_restarted() -> None:
    platform = a_platform()
    platform.restart.side_effect = PlatformUnreachable("connection refused")

    Scenario() \
        .given(platform) \
        .when(attempting(lambda: _restarting(platform))) \
        .then(an_error_was_raised(ServiceNotRestarted))


@pytest.mark.unit
def test_a_service_still_served_by_the_same_process_is_not_reported_as_restarted() -> None:
    # The rollout that never completed, and the one failure this is really
    # guarding: the platform said yes, and nothing happened. Reported
    # optimistically it would have Mitigation read a leak still climbing as
    # evidence that restarting does not help.
    platform = a_platform_whose_process_never_changes()

    Scenario() \
        .given(platform) \
        .when(attempting(lambda: _restarting(platform))) \
        .then(an_error_was_raised(ServiceNotRestarted))


@pytest.mark.unit
def test_a_service_that_reported_no_process_before_is_taken_at_its_first_reading_after() -> None:
    # Nothing to see a change against, so there is no change to wait for. A
    # service that was reporting no start time at all is one whose first
    # reading after the action is the only answer available - waiting for that
    # reading to differ from nothing would wait for ever.
    platform = a_platform()
    platform.newest_pod_started_at.side_effect = [None, THE_PROCESS_THAT_CAME_UP]

    Scenario() \
        .given(platform) \
        .when(lambda: _restarting(platform)) \
        .then(all_of(
            _the_service_was_looked_at(times=2, platform=platform),
            _the_process_that_came_up_is(DONT_CARE_SERVICE, THE_PROCESS_THAT_CAME_UP)
        ))


@pytest.mark.unit
def test_a_service_that_cannot_be_read_after_the_action_is_not_reported_as_restarted() -> None:
    # Unconfirmed is not confirmed. The action may well have landed, but
    # nothing here saw it land, and every caller above this treats the answer
    # as evidence that it did.
    platform = a_platform_whose_reading_fails_after_the_action()

    Scenario() \
        .given(platform) \
        .when(attempting(lambda: _restarting(platform))) \
        .then(an_error_was_raised(ServiceNotRestarted))


@pytest.mark.unit
def test_a_platform_that_could_not_be_read_before_the_action_is_unreachable() -> None:
    # The first thing a restart does is ask what is serving, so on a platform
    # that is down this is where it finds out. Nothing has been asked for yet,
    # which is what makes the report honest.
    platform = a_platform()
    platform.newest_pod_started_at.side_effect = PlatformUnreachable("connection refused")

    Scenario() \
        .given(platform) \
        .when(attempting(lambda: _restarting(platform))) \
        .then(all_of(
            _it_is_reported_as_an_unreachable_platform(),
            _no_restart_was_asked_for(platform)
        ))


@pytest.mark.unit
def test_a_platform_that_never_received_the_action_is_unreachable() -> None:
    platform = a_platform()
    platform.restart.side_effect = PlatformUnreachable("connection refused")

    Scenario() \
        .given(platform) \
        .when(attempting(lambda: _restarting(platform))) \
        .then(_it_is_reported_as_an_unreachable_platform())


@pytest.mark.unit
def test_a_platform_that_refused_the_action_is_not_reported_as_unreachable() -> None:
    # A credential this platform will not accept for this action. It is
    # answering, so the scale-out and the pin are still worth reaching for, and
    # what a person has to look at is this refusal rather than the platform.
    platform = a_platform()
    platform.restart.side_effect = PlatformRefused("permission denied")

    Scenario() \
        .given(platform) \
        .when(attempting(lambda: _restarting(platform))) \
        .then(_it_is_not_reported_as_an_unreachable_platform())


@pytest.mark.unit
def test_a_restart_that_could_not_be_confirmed_is_not_reported_as_unreachable() -> None:
    # The restriction the marker carries. The platform took the action and then
    # stopped answering, so a restart may well be rolling right now - and a walk
    # told only that the platform is unavailable would pass over the remaining
    # actions believing the estate untouched.
    platform = a_platform_whose_reading_fails_after_the_action()

    Scenario() \
        .given(platform) \
        .when(attempting(lambda: _restarting(platform))) \
        .then(_it_is_not_reported_as_an_unreachable_platform())


@pytest.mark.unit
def test_a_process_that_never_changed_is_not_reported_as_unreachable() -> None:
    # The platform answered everything it was asked and the rollout did not
    # arrive. Nothing here is evidence about reachability, and reporting it as
    # such would take three other actions away over a restart that stalled.
    platform = a_platform_whose_process_never_changes()

    Scenario() \
        .given(platform) \
        .when(attempting(lambda: _restarting(platform))) \
        .then(_it_is_not_reported_as_an_unreachable_platform())


@pytest.mark.unit
def test_a_restart_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    # A change to production. The process it brought up is in the answer; the
    # log is where a person finds that it happened at all.
    some_service = "kuki-service"

    Scenario() \
        .given(
            calling(lambda: caplog.set_level(logging.INFO)),
            platform := a_platform()
        ) \
        .when(lambda: restart_service(some_service, platform, sleep=dont_care_sleep)) \
        .then(
            one_record_was_logged(caplog, "write_mcp_server.restarting", logging.INFO,
                                  "service restarted",
                                  values={"service": some_service})
        )


@pytest.mark.unit
def test_a_restart_never_confirmed_is_logged_as_a_warning(
    caplog: pytest.LogCaptureFixture
) -> None:
    # The platform said yes and nothing rolled. Pods may still be on their
    # way, and nothing in Argus will look again.
    some_service = "kuki-service"

    Scenario() \
        .given(
            platform := a_platform_whose_process_never_changes()
        ) \
        .when(
            attempting(lambda: restart_service(some_service, platform, sleep=dont_care_sleep))
        ) \
        .then(
            one_record_was_logged(caplog, "write_mcp_server.restarting", logging.WARNING,
                                  "restart not confirmed in time",
                                  values={"service": some_service})
        )


def _restarting(platform: Any) -> RestartedService:
    return restart_service(DONT_CARE_SERVICE, platform, sleep=dont_care_sleep)


def a_platform() -> Any:
    """A platform that accepts the action, serving a process that then rolls."""
    platform = create_autospec(DeploymentPlatformWrites, instance=True)
    platform.newest_pod_started_at.side_effect = [
        THE_PROCESS_THAT_WAS_SERVING, THE_PROCESS_THAT_CAME_UP
    ]

    return platform


def a_platform_that_rolls_after(stale_readings: int) -> Any:
    """A rollout that takes a few looks to arrive, as every real one does."""
    platform = a_platform()
    platform.newest_pod_started_at.side_effect = (
        [THE_PROCESS_THAT_WAS_SERVING] * (stale_readings + 1)
        + [THE_PROCESS_THAT_CAME_UP]
    )

    return platform


def a_platform_whose_process_never_changes() -> Any:
    platform = a_platform()
    platform.newest_pod_started_at.side_effect = None
    platform.newest_pod_started_at.return_value = THE_PROCESS_THAT_WAS_SERVING

    return platform


def a_platform_whose_reading_fails_after_the_action() -> Any:
    platform = a_platform()
    platform.newest_pod_started_at.side_effect = [
        THE_PROCESS_THAT_WAS_SERVING, PlatformUnreachable("connection refused")
    ]

    return platform


def _it_is_reported_as_an_unreachable_platform() -> Assertion[Exception | None]:
    def assertion(raised: Exception | None) -> bool:
        if not isinstance(raised, ServiceNotRestarted):
            raise AssertionError(
                f"Expected the restart to be refused, and what was raised was "
                f"{raised!r}."
            )

        if UNREACHABLE_PLATFORM_MARKER not in str(raised):
            raise AssertionError(
                f"Expected the refusal to report a platform that could not be "
                f"reached, and it reported [{raised}]."
            )

        return True

    return assertion


def _it_is_not_reported_as_an_unreachable_platform() -> Assertion[Exception | None]:
    def assertion(raised: Exception | None) -> bool:
        if not isinstance(raised, ServiceNotRestarted):
            raise AssertionError(
                f"Expected the restart to be refused, and what was raised was "
                f"{raised!r}."
            )

        if UNREACHABLE_PLATFORM_MARKER in str(raised):
            raise AssertionError(
                f"Expected the refusal to be reported as this action's own, and "
                f"it reported a platform that could not be reached: [{raised}]."
            )

        return True

    return assertion


def _the_restart_was_asked_of(service: str, platform: Any) -> Assertion[object]:
    def assertion(dont_care_result: object) -> bool:
        asked = [call.args for call in platform.restart.call_args_list]

        if asked != [(service,)]:
            raise AssertionError(
                f"Expected one restart of [{service}], and the platform was "
                f"asked {asked}."
            )

        return True

    return assertion


def _no_restart_was_asked_for(platform: Any) -> Assertion[object]:
    def assertion(dont_care_result: object) -> bool:
        if platform.restart.called:
            raise AssertionError(
                f"Expected no restart to be asked for, and the platform was asked "
                f"{platform.restart.call_args_list}."
            )

        return True

    return assertion


def _it_was_asked_in_order(platform: Any, *expected: str) -> Assertion[object]:
    def assertion(dont_care_result: object) -> bool:
        asked = [name for name, _args, _kwargs in platform.method_calls]

        if asked != list(expected):
            raise AssertionError(
                f"Expected the platform to be asked {list(expected)} in that "
                f"order, and it was asked {asked}."
            )

        return True

    return assertion


def _the_service_was_looked_at(times: int, platform: Any) -> Assertion[object]:
    def assertion(dont_care_result: object) -> bool:
        looks = platform.newest_pod_started_at.call_count

        if looks != times:
            raise AssertionError(
                f"Expected the service to be looked at {times} times, "
                f"and it was looked at {looks}."
            )

        return True

    return assertion


def _every_look_was_at(expected: str, platform: Any) -> Assertion[object]:
    """Every reading taken about the service being restarted, not only the last.

    The look before the action is the one that matters most: it is what the
    reading afterwards is compared against, and a pair of readings taken about
    two different applications would report a restart whenever either of them
    happened to roll.
    """
    def assertion(dont_care_result: object) -> bool:
        looked_at = [
            call.args[0] for call in platform.newest_pod_started_at.call_args_list
        ]

        if set(looked_at) != {expected}:
            raise AssertionError(
                f"Expected every look to be at [{expected}], and they were at "
                f"{looked_at}."
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
