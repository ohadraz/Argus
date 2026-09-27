"""Making a deployment larger through the platform's own scaling action.

What is worth pinning is where the count comes from and what bounds it, because
neither is this module's preference. The count it replaces is live state only the
platform holds - the repository says what it is asked to converge on, which is a
different number the moment anybody scales - so a target derived from anything
else would be derived from a fact nobody here has. And the ceiling is the estate's
rather than the incident's: it bounds how large one attempt may make a deployment,
where the gate's cap bounds how many attempts there are.

The order is the platform's rule, as the rollback's is. A platform reconciling the
application itself puts a live replica count straight back at its next sync, so
suspending that is part of scaling rather than a separate concern - and it is the
half a withdrawal has to put back.

The descriptor is the other half. Only this module ever knows what the count was
or whether reconciliation was on, so an undo hours later can put back exactly as
much as this records and no more.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import MagicMock, create_autospec

import httpx
import pytest
from argus_core.models import CapacityRestored, ReplicaUndo
from argus_testkit import Assertion, Scenario, all_of, an_error_was_raised, attempting
from write_mcp_server.scaling import (
    THE_MOST_REPLICAS_ARGUS_MAY_ASK_FOR,
    AlreadyAtItsLargest,
    ScaleRefused,
    ScaleSettings,
    restore_replica_count,
    scale_out,
)

SOME_APPLICATION = "io-shop"
DONT_CARE_URL = "http://argocd.invalid"
SOME_APPLICATION_PATH = "/api/v1/applications/{application}"
SOME_RESOURCE_PATH = "/api/v1/applications/{application}/resource"
SOME_ACTION_PATH = "/api/v1/applications/{application}/resource/actions/v2"
SOME_SPEC_PATH = "/api/v1/applications/{application}/spec"
SOME_NAMESPACE = "production"

# What the deployment is running when anybody looks, and what one doubling of it
# comes to. Three is the size the fixture's own values file asks for.
THE_COUNT_RUNNING = 3
TWICE_THAT = 6


@dataclass
class _Platform:
    """The four routes a scale-out touches, each answering as Argo CD does.

    One `get` for two different reads, dispatched on the url: the application
    carries the sync policy and the managed resource carries the replica count,
    and a double that answered one body to both would let a module read the count
    out of the wrong document.
    """

    get: MagicMock = field(default_factory=lambda: create_autospec(httpx.get))
    post: MagicMock = field(default_factory=lambda: create_autospec(httpx.post))
    put: MagicMock = field(default_factory=lambda: create_autospec(httpx.put))


def _settings() -> ScaleSettings:
    return ScaleSettings(
        argocd_base_url=DONT_CARE_URL,
        argocd_application_path=SOME_APPLICATION_PATH,
        argocd_resource_path=SOME_RESOURCE_PATH,
        argocd_resource_action_path=SOME_ACTION_PATH,
        argocd_spec_path=SOME_SPEC_PATH,
        argocd_auth_token="",
        scale_namespace=SOME_NAMESPACE
    )


def _an_application(reconciling_itself: bool) -> dict[str, Any]:
    policy: dict[str, Any] = {"automated": {}} if reconciling_itself else {}

    return {"spec": {"syncPolicy": policy}}


def _a_managed_deployment(replicas: int) -> dict[str, Any]:
    """The live Deployment as Argo CD reports it: a manifest carried as text.

    A string and not an object, because that is the vendor's shape - the caller
    parses it - and a double that answered a parsed object would be an easier
    endpoint to write against than the one the adapter will meet.
    """
    return {
        "manifest": json.dumps(
            {
                "apiVersion": "apps/v1",
                "kind": "Deployment",
                "metadata": {"name": SOME_APPLICATION, "namespace": SOME_NAMESPACE},
                "spec": {"replicas": replicas}
            }
        )
    }


def _an_ok(body: dict[str, Any] | None = None) -> httpx.Response:
    return httpx.Response(
        status_code=200,
        json=body if body is not None else {},
        request=httpx.Request("GET", DONT_CARE_URL)
    )


def a_platform(replicas: int = THE_COUNT_RUNNING,
               reconciling_itself: bool = True) -> _Platform:
    platform = _Platform()

    def answering(url: str, **dont_care_rest: Any) -> httpx.Response:
        if url.endswith("/resource"):
            return _an_ok(_a_managed_deployment(replicas))

        return _an_ok(_an_application(reconciling_itself))

    platform.get.side_effect = answering
    platform.post.return_value = _an_ok()
    platform.put.return_value = _an_ok()

    return platform


def _scaling_out(platform: _Platform) -> ReplicaUndo:
    return scale_out(
        SOME_APPLICATION,
        _settings(),
        get=platform.get,
        post=platform.post,
        put=platform.put
    )


@pytest.mark.unit
def test_a_scale_out_doubles_the_count_that_is_running() -> None:
    # Derived from what the platform says is running, not from what the
    # repository asks for: the two are the same number until somebody scales, and
    # a target derived from the file would undo the previous attempt.
    platform = a_platform(replicas=THE_COUNT_RUNNING)

    Scenario() \
        .given(platform) \
        .when(lambda: _scaling_out(platform)) \
        .then(_it_asked_for(platform, replicas=TWICE_THAT))


@pytest.mark.unit
def test_the_count_asked_for_is_carried_as_the_vendor_carries_it() -> None:
    # Every resource-action parameter is a string on the wire, and the action's
    # own script is what makes a number of it. A double sending an integer would
    # be a double a real server refuses.
    platform = a_platform()

    Scenario() \
        .given(platform) \
        .when(lambda: _scaling_out(platform)) \
        .then(_the_count_was_sent_as_text(platform))


@pytest.mark.unit
def test_reconciliation_is_suspended_before_the_count_is_changed() -> None:
    # The platform's rule rather than a preference: a reconciling application has
    # its live replica count set back to whatever the repository holds at the next
    # sync, so a scale-out taken under automated sync is a mitigation with a timer
    # on it.
    platform = a_platform(reconciling_itself=True)

    Scenario() \
        .given(platform) \
        .when(lambda: _scaling_out(platform)) \
        .then(_reconciliation_was_turned(platform, off=True))


@pytest.mark.unit
def test_an_application_nobody_was_reconciling_is_left_alone() -> None:
    platform = a_platform(reconciling_itself=False)

    Scenario() \
        .given(platform) \
        .when(lambda: _scaling_out(platform)) \
        .then(_the_sync_policy_was_not_touched(platform))


@pytest.mark.unit
def test_the_descriptor_records_the_count_and_the_policy_it_found() -> None:
    platform = a_platform(replicas=THE_COUNT_RUNNING, reconciling_itself=True)

    Scenario() \
        .given(platform) \
        .when(lambda: _scaling_out(platform)) \
        .then(all_of(
            _the_descriptor_records_the_count(THE_COUNT_RUNNING),
            _the_descriptor_records_sync_was(True)
        ))


@pytest.mark.unit
def test_a_descriptor_records_sync_as_it_was_found_off() -> None:
    # Never a default. An application somebody had already stopped reconciling
    # must be left stopped, and a descriptor that recorded the usual arrangement
    # would have a withdrawal start something Argus did not stop.
    platform = a_platform(reconciling_itself=False)

    Scenario() \
        .given(platform) \
        .when(lambda: _scaling_out(platform)) \
        .then(_the_descriptor_records_sync_was(False))


@pytest.mark.unit
def test_a_double_that_would_pass_the_ceiling_stops_at_it() -> None:
    # The bound is the estate's, and it binds the size of one attempt rather than
    # the number of them - which is the cap's job, at the gate.
    just_under = THE_MOST_REPLICAS_ARGUS_MAY_ASK_FOR - 1
    platform = a_platform(replicas=just_under)

    Scenario() \
        .given(platform) \
        .when(lambda: _scaling_out(platform)) \
        .then(_it_asked_for(platform, replicas=THE_MOST_REPLICAS_ARGUS_MAY_ASK_FOR))


@pytest.mark.unit
def test_a_deployment_already_at_the_ceiling_is_refused_before_anything_changes() -> None:
    # Refused rather than answered with a no-op, and refused before the sync
    # policy is touched: a caller told "done" would record a mitigation that never
    # happened and then judge the service against it.
    platform = a_platform(replicas=THE_MOST_REPLICAS_ARGUS_MAY_ASK_FOR)

    Scenario() \
        .given(platform) \
        .when(attempting(lambda: _scaling_out(platform))) \
        .then(all_of(
            an_error_was_raised(AlreadyAtItsLargest),
            _nothing_was_changed(platform)
        ))


@pytest.mark.unit
def test_a_platform_that_will_not_answer_is_not_reported_as_scaled() -> None:
    platform = a_platform()
    platform.get.side_effect = httpx.ConnectError("no route to the platform")

    Scenario() \
        .given(platform) \
        .when(attempting(lambda: _scaling_out(platform))) \
        .then(all_of(
            an_error_was_raised(ScaleRefused),
            _nothing_was_changed(platform)
        ))


@pytest.mark.unit
def test_a_manifest_that_says_nothing_about_replicas_is_refused() -> None:
    # A Deployment with no count in its manifest is one this cannot double, and a
    # guess of one would halve a shop serving three.
    platform = a_platform()
    platform.get.side_effect = lambda url, **dont_care_rest: _an_ok(
        {"manifest": json.dumps({"spec": {}})}
    )

    Scenario() \
        .given(platform) \
        .when(attempting(lambda: _scaling_out(platform))) \
        .then(all_of(
            an_error_was_raised(ScaleRefused),
            _nothing_was_changed(platform)
        ))


@pytest.mark.unit
def test_restoring_puts_back_the_count_that_was_running() -> None:
    platform = a_platform()

    Scenario() \
        .given(a_descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: _restoring(a_descriptor, platform)) \
        .then(all_of(
            _it_asked_for(platform, replicas=THE_COUNT_RUNNING),
            _it_reports_restored(count=True, automated_sync=True)
        ))


@pytest.mark.unit
def test_restoring_turns_reconciliation_back_on_where_it_was_on() -> None:
    platform = a_platform()

    Scenario() \
        .given(a_descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: _restoring(a_descriptor, platform)) \
        .then(_reconciliation_was_turned(platform, off=False))


@pytest.mark.unit
def test_restoring_leaves_reconciliation_off_where_argus_found_it_off() -> None:
    platform = a_platform()

    Scenario() \
        .given(a_descriptor := _a_descriptor(was_syncing_itself=False)) \
        .when(lambda: _restoring(a_descriptor, platform)) \
        .then(all_of(
            _the_sync_policy_was_not_touched(platform),
            _it_reports_restored(count=True, automated_sync=True)
        ))


@pytest.mark.unit
def test_a_restore_that_only_managed_the_count_says_so() -> None:
    # The half that fails is the quiet one: a deployment back at its declared size
    # looks right from every angle a reader has, while receiving nothing anybody
    # ships to it.
    platform = a_platform()
    platform.put.side_effect = httpx.ConnectError("no route to the platform")

    Scenario() \
        .given(a_descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: _restoring(a_descriptor, platform)) \
        .then(_it_reports_restored(count=True, automated_sync=False))


@pytest.mark.unit
def test_a_restore_that_could_not_reach_the_platform_at_all_says_so() -> None:
    platform = a_platform()
    platform.post.side_effect = httpx.ConnectError("no route to the platform")
    platform.put.side_effect = httpx.ConnectError("no route to the platform")

    Scenario() \
        .given(a_descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: _restoring(a_descriptor, platform)) \
        .then(_it_reports_restored(count=False, automated_sync=False))


def _restoring(descriptor: ReplicaUndo, platform: _Platform) -> CapacityRestored:
    return restore_replica_count(
        descriptor, _settings(), post=platform.post, put=platform.put
    )


def _a_descriptor(was_syncing_itself: bool) -> ReplicaUndo:
    return ReplicaUndo(
        application=SOME_APPLICATION,
        was_replicas=THE_COUNT_RUNNING,
        was_syncing_itself=was_syncing_itself
    )


def _the_action_body(platform: _Platform) -> dict[str, Any]:
    return dict(platform.post.call_args.kwargs["json"])


def _the_count_asked_for(platform: _Platform) -> str | None:
    parameters = _the_action_body(platform).get("resourceActionParameters", [])
    counts = [
        parameter["value"] for parameter in parameters
        if parameter["name"] == "replicas"
    ]

    return counts[-1] if counts else None


def _it_asked_for(platform: _Platform, replicas: int) -> Assertion[object]:
    def assertion(dont_care_result: object) -> bool:
        if not platform.post.called:
            raise AssertionError(
                f"Expected the platform to be asked for [{replicas}] replicas, "
                f"and no action was run at all."
            )

        asked = _the_count_asked_for(platform)

        if asked != str(replicas):
            raise AssertionError(
                f"Expected the platform to be asked for [{replicas}] replicas, "
                f"and it was asked for [{asked}]."
            )

        return True

    return assertion


def _the_count_was_sent_as_text(platform: _Platform) -> Assertion[object]:
    def assertion(dont_care_result: object) -> bool:
        parameters = _the_action_body(platform).get("resourceActionParameters", [])
        wrongly_typed = [
            parameter for parameter in parameters
            if not isinstance(parameter["value"], str)
        ]

        if wrongly_typed:
            raise AssertionError(
                f"Expected every action parameter to be carried as text, as the "
                f"platform carries them, and {wrongly_typed} are not."
            )

        return True

    return assertion


def _reconciliation_was_turned(platform: _Platform, off: bool) -> Assertion[object]:
    def assertion(dont_care_result: object) -> bool:
        if not platform.put.called:
            raise AssertionError(
                "Expected the sync policy to be written, and it was not written "
                "at all."
            )

        policy = platform.put.call_args.kwargs["json"]["syncPolicy"]
        suspended = policy.get("automated") is None

        if suspended != off:
            raise AssertionError(
                f"Expected automated sync to be turned {'off' if off else 'on'}, "
                f"and the policy written was [{policy}]."
            )

        return True

    return assertion


def _the_sync_policy_was_not_touched(platform: _Platform) -> Assertion[object]:
    def assertion(dont_care_result: object) -> bool:
        if platform.put.called:
            raise AssertionError(
                f"Expected the sync policy to be left as it was found, and it "
                f"was written with [{platform.put.call_args.kwargs['json']}]."
            )

        return True

    return assertion


def _nothing_was_changed(platform: _Platform) -> Assertion[Exception | None]:
    def assertion(dont_care_error: Exception | None) -> bool:
        changed = [
            name for name, route in (("the action", platform.post),
                                     ("the sync policy", platform.put))
            if route.called
        ]

        if changed:
            raise AssertionError(
                f"Expected a refusal to change nothing, and it wrote "
                f"{sorted(changed)}."
            )

        return True

    return assertion


def _the_descriptor_records_the_count(replicas: int) -> Assertion[ReplicaUndo]:
    def assertion(descriptor: ReplicaUndo) -> bool:
        if descriptor.was_replicas != replicas:
            raise AssertionError(
                f"Expected the descriptor to record [{replicas}] replicas as "
                f"the count that was running, and it records "
                f"[{descriptor.was_replicas}]."
            )

        return True

    return assertion


def _the_descriptor_records_sync_was(syncing: bool) -> Assertion[ReplicaUndo]:
    def assertion(descriptor: ReplicaUndo) -> bool:
        if descriptor.was_syncing_itself != syncing:
            raise AssertionError(
                f"Expected the descriptor to record automated sync as "
                f"[{syncing}] when Argus found it, and it records "
                f"[{descriptor.was_syncing_itself}]."
            )

        return True

    return assertion


def _it_reports_restored(count: bool,
                         automated_sync: bool) -> Assertion[CapacityRestored]:
    def assertion(restored: CapacityRestored) -> bool:
        reported = (restored.count_put_back, restored.automated_sync_put_back)

        if reported != (count, automated_sync):
            raise AssertionError(
                f"Expected the count put back to be [{count}] and automated "
                f"sync to be [{automated_sync}], and it reported {reported}."
            )

        return True

    return assertion
