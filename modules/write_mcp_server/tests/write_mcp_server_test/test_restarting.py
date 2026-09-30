from __future__ import annotations

from typing import Any
from unittest.mock import create_autospec

import httpx
import pytest
from argus_core.mcp_transport import UNREACHABLE_PLATFORM_MARKER
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
    the_pod_start_time,
)

DONT_CARE_SERVICE = "dont-care-service"
DONT_CARE_URL = "http://argocd.invalid/"
SOME_ACTION_PATH = "/api/v1/applications/{application}/resource/actions/v2"
SOME_RESOURCE_TREE_PATH = "/api/v1/applications/{application}/resource-tree"

# Two pod creation times that are unmistakably different processes, as the
# platform reports them and as seconds since the epoch. Both spellings, because
# the reading crosses that boundary: the platform answers in the vendor's own
# RFC 3339, and what a restart is confirmed by is a number that can be compared.
WHEN_THE_POD_THAT_WAS_SERVING_CAME_UP = "2026-08-20T11:00:00Z"
WHEN_THE_POD_THAT_CAME_UP_CAME_UP = "2026-08-20T11:10:00Z"
THE_PROCESS_THAT_WAS_SERVING = 1_787_223_600.0
THE_PROCESS_THAT_CAME_UP = 1_787_224_200.0


@pytest.mark.unit
def test_a_restart_is_asked_for_as_the_action_the_platform_registers_it_under() -> None:
    # A restart is not an endpoint. The platform runs a script registered
    # against a kind of resource, and what dispatches to it is the whole of
    # group, kind, namespace, name and action - a request missing one of them
    # is a request that reaches no script at all.
    some_namespace = "kuki-production"
    some_service = "kuki-pricing"
    platform = a_platform()

    Scenario() \
        .given(platform) \
        .when(
            lambda: restart_service(
                some_service,
                settings=some_settings(namespace=some_namespace),
                post=platform.post,
                observe=platform.observe,
                sleep=dont_care_sleep
            )
        ) \
        .then(
            _the_action_asked_for_is(
                {
                    "namespace": some_namespace,
                    "resourceName": some_service,
                    "group": RESTART_GROUP,
                    "kind": RESTART_KIND,
                    "action": RESTART_ACTION
                },
                platform
            )
        )


@pytest.mark.unit
def test_the_resource_restarted_is_the_service_asked_about_not_a_configured_one() -> None:
    # The resource name used to be configuration, which was true for as long as
    # the only service Argus could restart was the one it was paged about. A
    # mitigation addressed at a dependency makes a fixed name actively wrong:
    # the request would be aimed at the shop's application and carry the shop's
    # deployment, so the platform would restart the wrong thing and report
    # success.
    a_dependency_of_the_alerting_service = "kuki-pricing"
    platform = a_platform()

    Scenario() \
        .given(platform) \
        .when(
            lambda: restart_service(
                a_dependency_of_the_alerting_service,
                settings=some_settings(),
                post=platform.post,
                observe=platform.observe,
                sleep=dont_care_sleep
            )
        ) \
        .then(
            _the_resource_named_is(a_dependency_of_the_alerting_service, platform)
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
def test_the_pod_looked_at_is_the_one_belonging_to_the_service_restarted() -> None:
    # The whole reason the confirmation moved off the metrics. A restart
    # addressed at a dependency has to be confirmed against that dependency's
    # pod: asked about the shop instead, the reading never moves, and a restart
    # that landed perfectly well is reported as one that never happened.
    a_dependency_of_the_alerting_service = "kuki-pricing"
    platform = a_platform()

    Scenario() \
        .given(platform) \
        .when(
            lambda: restart_service(
                a_dependency_of_the_alerting_service,
                settings=some_settings(),
                post=platform.post,
                observe=platform.observe,
                sleep=dont_care_sleep
            )
        ) \
        .then(
            _every_look_was_at(a_dependency_of_the_alerting_service, platform)
        )


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
def test_the_process_serving_now_is_read_from_the_pod_that_came_up_last() -> None:
    # A rollout has two pods in it for a while, and the older one is precisely
    # the process a restart has to be told apart from. The newest is what is
    # serving as far as anything downstream is concerned.
    dont_care_older_pod = a_pod(came_up=WHEN_THE_POD_THAT_WAS_SERVING_CAME_UP)
    the_pod_that_came_up = a_pod(came_up=WHEN_THE_POD_THAT_CAME_UP_CAME_UP)

    Scenario() \
        .given(
            a_platform_reporting := a_platform_whose_tree_holds(
                [dont_care_older_pod, the_pod_that_came_up]
            )
        ) \
        .when(
            lambda: the_pod_start_time(
                some_settings(), get=a_platform_reporting
            )(DONT_CARE_SERVICE)
        ) \
        .then(_the_start_time_read_is(THE_PROCESS_THAT_CAME_UP))


@pytest.mark.unit
def test_the_resource_tree_is_asked_about_the_service_being_confirmed() -> None:
    # Per application, which is the whole point: restarting the pricing service
    # moves its pod's creation time and leaves the shop's exactly where it was.
    some_service = "kuki-pricing"
    some_base_url = "http://argocd.kuki.com"

    Scenario() \
        .given(
            a_platform_reporting := a_platform_whose_tree_holds(
                [a_pod(came_up=WHEN_THE_POD_THAT_CAME_UP_CAME_UP)]
            )
        ) \
        .when(
            lambda: the_pod_start_time(
                some_settings(base_url=some_base_url), get=a_platform_reporting
            )(some_service)
        ) \
        .then(
            _the_tree_read_is(
                f"{some_base_url}/api/v1/applications/{some_service}/resource-tree",
                a_platform_reporting
            )
        )


@pytest.mark.unit
def test_an_application_with_nothing_running_has_no_process_that_can_be_seen() -> None:
    # Different from an application reporting a pod that has not restarted: one
    # is a reading, the other is the absence of one, and only the second leaves
    # the restart unconfirmable.
    Scenario() \
        .given(a_platform_running_nothing := a_platform_whose_tree_holds([])) \
        .when(
            lambda: the_pod_start_time(
                some_settings(), get=a_platform_running_nothing
            )(DONT_CARE_SERVICE)
        ) \
        .then(_the_start_time_read_is(None))


@pytest.mark.unit
def test_a_tree_holding_no_pod_at_all_reports_none() -> None:
    # A real resource tree carries the whole application - the Deployment, the
    # ReplicaSet, the Service - and only a pod is a process that came up. Taken
    # from whatever node happens to be first, the answer would be the creation
    # time of an object that has not restarted since it was declared.
    a_deployment = {
        "kind": "Deployment",
        "name": "kuki-shop",
        "namespace": "production",
        "createdAt": WHEN_THE_POD_THAT_WAS_SERVING_CAME_UP
    }

    Scenario() \
        .given(a_platform_reporting := a_platform_whose_tree_holds([a_deployment])) \
        .when(
            lambda: the_pod_start_time(
                some_settings(), get=a_platform_reporting
            )(DONT_CARE_SERVICE)
        ) \
        .then(_the_start_time_read_is(None))


@pytest.mark.unit
def test_a_pod_whose_creation_time_cannot_be_read_reports_none() -> None:
    # Unreadable is not absent, but it leads to the same place: nothing here
    # can say what is serving, so nothing above may proceed as though it had
    # been told. A crash would report an unconfirmable restart as a broken one.
    a_pod_with_a_creation_time_nobody_can_parse = {
        "kind": "Pod",
        "name": "kuki-shop-7d4f",
        "namespace": "production",
        "createdAt": "whenever it was"
    }

    Scenario() \
        .given(
            a_platform_reporting := a_platform_whose_tree_holds(
                [a_pod_with_a_creation_time_nobody_can_parse]
            )
        ) \
        .when(
            lambda: the_pod_start_time(
                some_settings(), get=a_platform_reporting
            )(DONT_CARE_SERVICE)
        ) \
        .then(_the_start_time_read_is(None))


@pytest.mark.unit
def test_a_platform_that_could_not_be_read_before_the_action_is_unreachable() -> None:
    # The first thing a restart does is ask what is serving, so on a platform
    # that is down this is where it finds out. Nothing has been asked for yet,
    # which is what makes the report honest.
    platform = a_platform_that_cannot_say_what_is_running()

    Scenario() \
        .given(platform) \
        .when(attempting(lambda: _restarting(platform))) \
        .then(all_of(_it_is_reported_as_an_unreachable_platform()))


@pytest.mark.unit
def test_a_platform_that_never_received_the_action_is_unreachable() -> None:
    platform = a_platform_that_cannot_be_reached()

    Scenario() \
        .given(platform) \
        .when(attempting(lambda: _restarting(platform))) \
        .then(all_of(_it_is_reported_as_an_unreachable_platform()))


@pytest.mark.unit
def test_a_platform_reporting_its_own_api_unavailable_is_unreachable() -> None:
    platform = a_platform_answering_that_it_is_unavailable()

    Scenario() \
        .given(platform) \
        .when(attempting(lambda: _restarting(platform))) \
        .then(all_of(_it_is_reported_as_an_unreachable_platform()))


@pytest.mark.unit
def test_a_platform_that_refused_the_action_is_not_reported_as_unreachable() -> None:
    # A credential this platform will not accept for this action. It is
    # answering, so the scale-out and the pin are still worth reaching for, and
    # what a person has to look at is this refusal rather than the platform.
    platform = a_platform_that_refuses_the_action()

    Scenario() \
        .given(platform) \
        .when(attempting(lambda: _restarting(platform))) \
        .then(all_of(_it_is_not_reported_as_an_unreachable_platform()))


@pytest.mark.unit
def test_a_restart_that_could_not_be_confirmed_is_not_reported_as_unreachable() -> None:
    # The restriction the marker carries. The platform took the action and then
    # stopped answering, so a restart may well be rolling right now - and a walk
    # told only that the platform is unavailable would pass over the remaining
    # actions believing the estate untouched.
    platform = a_platform_whose_gauge_fails_after_the_action()

    Scenario() \
        .given(platform) \
        .when(attempting(lambda: _restarting(platform))) \
        .then(all_of(_it_is_not_reported_as_an_unreachable_platform()))


@pytest.mark.unit
def test_a_process_that_never_changed_is_not_reported_as_unreachable() -> None:
    # The platform answered everything it was asked and the rollout did not
    # arrive. Nothing here is evidence about reachability, and reporting it as
    # such would take three other actions away over a restart that stalled.
    platform = a_platform_whose_process_never_changes()

    Scenario() \
        .given(platform) \
        .when(attempting(lambda: _restarting(platform))) \
        .then(all_of(_it_is_not_reported_as_an_unreachable_platform()))


def _restarting(platform: _Platform) -> RestartedService:
    return restart_service(
        DONT_CARE_SERVICE,
        settings=some_settings(),
        post=platform.post,
        observe=platform.observe,
        sleep=dont_care_sleep
    )


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


def _the_resource_named_is(expected: str, platform: _Platform) -> Assertion[object]:
    def assertion(dont_care_result: object) -> bool:
        named = platform.post.call_args.kwargs["json"]["resourceName"]
        if named != expected:
            raise AssertionError(
                f"Expected the deployment restarted to be [{expected}], "
                f"and it was [{named}]."
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


def _every_look_was_at(expected: str, platform: _Platform) -> Assertion[object]:
    """Every reading taken about the service being restarted, not only the last.

    The look before the action is the one that matters most: it is what the
    reading afterwards is compared against, and a pair of readings taken about
    two different applications would report a restart whenever either of them
    happened to roll.
    """
    def assertion(dont_care_result: object) -> bool:
        looked_at = [call.args[0] for call in platform.observe.call_args_list]

        if set(looked_at) != {expected}:
            raise AssertionError(
                f"Expected every look to be at [{expected}], and they were at "
                f"{looked_at}."
            )

        return True

    return assertion


def _the_tree_read_is(expected: str, get: Any) -> Assertion[object]:
    def assertion(dont_care_result: object) -> bool:
        read = get.call_args.args[0]
        if read != expected:
            raise AssertionError(
                f"Expected the resource tree to be read from [{expected}], "
                f"and it was read from [{read}]."
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
    """The deployment platform, asked for a restart and then asked what is up.

    One stand-in rather than two, because no test here needs only one of them:
    a restart is asked of the platform and confirmed against the platform's own
    view of what is running, and a test that stood in only the first would be
    waiting on a real server.
    """

    def __init__(self) -> None:
        self.post: Any = create_autospec(httpx.post)
        # Spec'd against the port rather than `httpx.get`: what confirms the
        # restart is a reading about one application, and where it is read
        # from is bound once, where the server is built.
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


def a_platform_answering_that_it_is_unavailable() -> _Platform:
    """A platform whose API server is not serving, as its ingress reports it."""
    platform = a_platform()
    platform.post.return_value = httpx.Response(
        status_code=503,
        json={"error": "upstream connect error"},
        request=httpx.Request("POST", DONT_CARE_URL)
    )

    return platform


def a_platform_that_cannot_say_what_is_running() -> _Platform:
    """A platform that is already gone when the first reading is taken.

    The one that matters most and is easiest to miss. A restart begins by asking
    what is serving now, so on a platform that is down this is what fails - and
    an action that never reached the request would report nothing about the
    platform at all unless this reading says so.
    """
    platform = a_platform()
    platform.observe.side_effect = httpx.ConnectError("connection refused")

    return platform


def a_pod(came_up: str) -> dict[str, Any]:
    """One live pod, in the shape the platform's resource tree reports it."""
    return {
        "kind": "Pod",
        "name": "kuki-shop-7d4f",
        "namespace": "production",
        "createdAt": came_up
    }


def a_platform_whose_tree_holds(nodes: list[dict[str, Any]]) -> Any:
    """The resource-tree route, answering with the objects it was given."""
    get: Any = create_autospec(httpx.get)
    get.return_value = httpx.Response(
        status_code=200,
        json={"nodes": nodes},
        request=httpx.Request("GET", DONT_CARE_URL)
    )

    return get


def some_settings(namespace: str = "dont-care-namespace",
                  auth_token: str = "dont-care-token",
                  base_url: str = "http://argocd.invalid") -> RestartSettings:
    """Where a restart is asked for, as this suite configures it.

    Each test names only the field it is about. The paths are never among them
    except in the two cases that spell a whole URL out: they are templates in
    every deployment, and a test asserting the shape would be asserting the
    default.
    """
    return RestartSettings(
        argocd_base_url=base_url,
        argocd_resource_action_path=SOME_ACTION_PATH,
        argocd_auth_token=auth_token,
        restart_namespace=namespace,
        argocd_resource_tree_path=SOME_RESOURCE_TREE_PATH
    )
