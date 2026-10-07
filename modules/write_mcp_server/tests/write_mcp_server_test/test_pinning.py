"""Holding an autoscaler still through the platform, and letting it move again.

The first action here that stops something rather than adding or restoring
something, and what is worth pinning is that it stops it by *raising a floor* -
the controller is left running, with nowhere left to scale down to. Nothing is
removed, nothing is deleted, and the ceiling a human declared is never moved.

Where the autoscaler is is discovered rather than configured, which is what
separates this from the restart and the scale-out beside it. Argo CD's resource
tree names every resource an application has, with its kind, its own name and its
namespace, so a pin asks the platform where to write instead of being told - and
an autoscaler named something other than its application is then addressed
correctly rather than plausibly.

The bounds are live state only the platform holds, as the scale-out's count is.
The repository says what the autoscaler is asked to converge on, which is a
different pair of numbers the moment anybody pins - so a floor derived from
anything else would be derived from a fact nobody here has.

The order is the platform's rule, as it is for the other two actions that change
live state under a GitOps controller: a reconciling application has the
autoscaler's whole manifest re-applied at its next sync, floor included. The
restore's order is the same rule read backwards - reconciliation last, because
turning it on first would have the platform put the floor back on its own,
unverifiably, at a moment nothing here chose.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import MagicMock, create_autospec

import httpx2
import pytest
from argus_core.mcp_transport import (
    EXHAUSTED_ACTION_MARKER,
    LEFT_BEHIND_MARKER,
    UNREACHABLE_PLATFORM_MARKER,
    what_was_left_behind,
)
from argus_core.models import AutoscalerUndo, AutoscalingRestored
from argus_testkit import Assertion, Scenario, all_of, an_error_was_raised, attempting
from write_mcp_server.argocd import (
    APPLICATION_MERGE_PATCH,
    AUTOMATED,
    ENABLED,
    PATCH_REQUEST_PATCH,
    PATCH_REQUEST_TYPE,
    SPEC,
    SYNC_POLICY,
)
from write_mcp_server.pinning import (
    AUTOSCALER_GROUP,
    AUTOSCALER_KIND,
    AUTOSCALER_VERSION,
    MERGE_PATCH_TYPE,
    AlreadyHeldStill,
    PinRefused,
    PinSettings,
    pin_autoscaler,
    restore_autoscaler_floor,
)
from write_mcp_server.scaling import THE_MOST_REPLICAS_ARGUS_MAY_ASK_FOR

SOME_APPLICATION = "io-shop"
DONT_CARE_URL = "http://argocd.invalid"
SOME_APPLICATION_PATH = "/api/v1/applications/{application}"
SOME_RESOURCE_TREE_PATH = "/api/v1/applications/{application}/resource-tree"
SOME_RESOURCE_PATH = "/api/v1/applications/{application}/resource"
# Where the application itself is, which is where a patch to it goes.
THE_APPLICATIONS_ROUTE = f"{DONT_CARE_URL}/api/v1/applications/{SOME_APPLICATION}"

# What the autoscaler is called and where it lives, as the platform's own tree
# reports them. Deliberately not the application's name: an autoscaler named after
# its application is the common case and not the contract, and a module that sent
# the application's name would pass every test that used one name for both.
SOME_AUTOSCALER_NAME = "io-shop-cpu"
SOME_NAMESPACE = "shopping"

# The bounds the fixture's own values file declares: a controller free to move
# between three replicas and six, which is what makes a flap possible at all.
THE_FLOOR = 3
THE_CEILING = 6

# What the two writes are called when the order they happened in is the thing
# being asserted. Neither mock knows about the other, so the platform records it.
THE_PATCH = "the patch"
THE_SYNC_POLICY = "the sync policy"


@dataclass
class _Platform:
    """The four routes a pin touches, each answering as Argo CD does.

    One `get` for three different reads, dispatched on the url: the tree says
    where the autoscaler is, the managed resource carries its bounds, and the
    application carries the sync policy. A double that answered one body to all
    three would let a module read a floor out of the wrong document.

    `wrote` is which of the two writes happened, in the order they happened. Both
    halves of a pin and both halves of its undo have to land in one order and not
    the other, and the reason is the platform's own behaviour rather than
    tidiness - so the order is asserted rather than assumed.
    """

    get: MagicMock = field(default_factory=lambda: create_autospec(httpx2.get))
    post: MagicMock = field(default_factory=lambda: create_autospec(httpx2.post))
    patch: MagicMock = field(default_factory=lambda: create_autospec(httpx2.patch))
    wrote: list[str] = field(default_factory=list)


def _settings() -> PinSettings:
    """The four paths a pin and its undo reach between them.

    No namespace among them, which is the whole of what the tree buys: where the
    autoscaler lives is a fact the platform holds, and a second copy of it in
    configuration is a copy that comes to disagree with the cluster.

    No resource-action path either, which is what separates this from the
    scale-out: a floor is a field on a manifest and is written by patching the
    resource, where a count is changed by running the platform's own registered
    action. So the resource path is read *and* written here, which is Argo CD's
    own arrangement - `GET` is `GetResource` and `POST` is `PatchResource` on the
    one route.
    """
    return PinSettings(
        argocd_base_url=DONT_CARE_URL,
        argocd_application_path=SOME_APPLICATION_PATH,
        argocd_resource_tree_path=SOME_RESOURCE_TREE_PATH,
        argocd_resource_path=SOME_RESOURCE_PATH,
        argocd_auth_token=""
    )


def _an_application(reconciling_itself: bool) -> dict[str, Any]:
    """Automated sync as an operator declares it, `selfHeal` and all, or none."""
    policy: dict[str, Any] = (
        {AUTOMATED: {"selfHeal": True}} if reconciling_itself else {}
    )

    return {SPEC: {SYNC_POLICY: policy}}


def _a_resource_tree(holding_an_autoscaler: bool) -> dict[str, Any]:
    """Every resource the application has, as Argo CD's tree reports them.

    More than one node, and the autoscaler is not the first: a module that took
    whatever the tree listed first would be a module that patched a Pod on a
    cluster that had listed one.
    """
    nodes: list[dict[str, Any]] = [
        {
            "group": "apps",
            "version": "v1",
            "kind": "Deployment",
            "name": SOME_APPLICATION,
            "namespace": SOME_NAMESPACE
        },
        {
            "version": "v1",
            "kind": "Pod",
            "name": f"{SOME_APPLICATION}-7d4f",
            "namespace": SOME_NAMESPACE
        }
    ]

    if holding_an_autoscaler:
        nodes.append(
            {
                "group": AUTOSCALER_GROUP,
                "version": AUTOSCALER_VERSION,
                "kind": AUTOSCALER_KIND,
                "name": SOME_AUTOSCALER_NAME,
                "namespace": SOME_NAMESPACE
            }
        )

    return {"nodes": nodes}


def _a_managed_autoscaler(floor: int, ceiling: int) -> dict[str, Any]:
    """The live autoscaler as Argo CD reports it: a manifest carried as text.

    A string and not an object, because that is the vendor's shape - the caller
    parses it - and a double that answered a parsed object would be an easier
    endpoint to write against than the one the adapter will meet.

    The whole resource rather than the two fields a pin reads. What makes this
    controller misbehave is the stabilisation window of zero, and a double that
    carried only the bounds would let a module be written against a manifest no
    platform sends.
    """
    return {
        "manifest": json.dumps(
            {
                "apiVersion": f"{AUTOSCALER_GROUP}/{AUTOSCALER_VERSION}",
                "kind": AUTOSCALER_KIND,
                "metadata": {"name": SOME_AUTOSCALER_NAME,
                             "namespace": SOME_NAMESPACE},
                "spec": {
                    "minReplicas": floor,
                    "maxReplicas": ceiling,
                    "behavior": {"scaleDown": {"stabilizationWindowSeconds": 0}}
                }
            }
        )
    }


def _an_ok(body: dict[str, Any] | None = None) -> httpx2.Response:
    return httpx2.Response(
        status_code=200,
        json=body if body is not None else {},
        request=httpx2.Request("GET", DONT_CARE_URL)
    )


def a_platform(floor: int = THE_FLOOR,
               ceiling: int = THE_CEILING,
               reconciling_itself: bool = True,
               holding_an_autoscaler: bool = True) -> _Platform:
    platform = _Platform()

    def answering(url: str, **dont_care_rest: Any) -> httpx2.Response:
        if url.endswith("/resource-tree"):
            return _an_ok(_a_resource_tree(holding_an_autoscaler))

        if url.endswith("/resource"):
            return _an_ok(_a_managed_autoscaler(floor, ceiling))

        return _an_ok(_an_application(reconciling_itself))

    def patching(dont_care_url: str, **dont_care_rest: Any) -> httpx2.Response:
        platform.wrote.append(THE_PATCH)

        return _an_ok()

    def writing_the_policy(dont_care_url: str,
                           **dont_care_rest: Any) -> httpx2.Response:
        platform.wrote.append(THE_SYNC_POLICY)

        return _an_ok()

    platform.get.side_effect = answering
    platform.post.side_effect = patching
    platform.patch.side_effect = writing_the_policy

    return platform


def _pinning(platform: _Platform) -> AutoscalerUndo:
    return pin_autoscaler(
        SOME_APPLICATION,
        _settings(),
        get=platform.get,
        post=platform.post,
        patch=platform.patch
    )


@pytest.mark.unit
def test_a_pin_raises_the_floor_to_the_ceiling() -> None:
    # To the ceiling and no further, because the ceiling is a bound a human
    # declared. The count is not Argus's to choose even in principle: what it is
    # choosing is that the count should stop moving.
    platform = a_platform(floor=THE_FLOOR, ceiling=THE_CEILING)

    Scenario() \
        .given(platform) \
        .when(lambda: _pinning(platform)) \
        .then(_it_asked_for_a_floor_of(platform, THE_CEILING))


@pytest.mark.unit
def test_the_autoscaler_is_found_in_the_platforms_own_tree() -> None:
    # Discovered rather than configured, and not assumed to be named after its
    # application: the tree says what the resource is called and which namespace
    # it is in, and both travel into the read that follows.
    platform = a_platform()

    Scenario() \
        .given(platform) \
        .when(lambda: _pinning(platform)) \
        .then(_the_resource_it_read_was_the_autoscaler(platform))


@pytest.mark.unit
def test_the_patch_goes_where_the_tree_said_the_autoscaler_is() -> None:
    # The write is addressed by what the platform reported rather than by
    # configuration, which is the point of asking: a namespace held in a setting
    # is a second copy of a fact the cluster already holds, and the patch is the
    # request where being wrong about it changes something.
    platform = a_platform()

    Scenario() \
        .given(platform) \
        .when(lambda: _pinning(platform)) \
        .then(_the_patch_was_addressed_to_the_autoscaler(platform))


@pytest.mark.unit
def test_an_application_with_no_autoscaler_in_its_tree_is_refused() -> None:
    # Nothing to pin, and the one thing a caller reading this cannot check for
    # itself: a pin performed against a controller that does not exist would be
    # confirmed against a world that does not exist either.
    platform = a_platform(holding_an_autoscaler=False)

    Scenario() \
        .given(platform) \
        .when(attempting(lambda: _pinning(platform))) \
        .then(all_of(
            an_error_was_raised(PinRefused),
            _nothing_was_changed(platform)
        ))


@pytest.mark.unit
def test_the_patch_is_carried_as_the_vendor_carries_it() -> None:
    # A JSON-encoded *string* rather than an object, which is the vendor's own
    # shape for this body and the mirror of the manifest arriving as text. And the
    # patch type is the merge patch's, because a patch sent as any other kind is
    # applied differently or not at all.
    platform = a_platform()

    Scenario() \
        .given(platform) \
        .when(lambda: _pinning(platform)) \
        .then(all_of(
            _the_patch_was_sent_as_text(platform),
            _it_was_sent_as_a_merge_patch(platform)
        ))


@pytest.mark.unit
def test_a_ceiling_past_what_argus_may_ask_for_is_clamped_to_it() -> None:
    # One estate, one bound on its capacity. The ceiling is a human's declaration
    # and this is Argus's own limit on what it may hold a deployment at, and where
    # the two disagree the smaller wins.
    platform = a_platform(
        floor=THE_FLOOR, ceiling=THE_MOST_REPLICAS_ARGUS_MAY_ASK_FOR + 1
    )

    Scenario() \
        .given(platform) \
        .when(lambda: _pinning(platform)) \
        .then(_it_asked_for_a_floor_of(platform, THE_MOST_REPLICAS_ARGUS_MAY_ASK_FOR))


@pytest.mark.unit
def test_reconciliation_is_suspended_before_the_floor_is_raised() -> None:
    # The platform's rule rather than a preference: a reconciling application has
    # the autoscaler's manifest re-applied at its next sync, floor and all, so a
    # pin taken under automated sync is a mitigation with a timer on it.
    platform = a_platform(reconciling_itself=True)

    Scenario() \
        .given(platform) \
        .when(lambda: _pinning(platform)) \
        .then(all_of(
            _reconciliation_was_turned(platform, off=True),
            _it_wrote(platform, THE_SYNC_POLICY, THE_PATCH)
        ))


@pytest.mark.unit
def test_an_application_nobody_was_reconciling_is_left_alone() -> None:
    platform = a_platform(reconciling_itself=False)

    Scenario() \
        .given(platform) \
        .when(lambda: _pinning(platform)) \
        .then(_the_sync_policy_was_not_touched(platform))


@pytest.mark.unit
def test_the_descriptor_records_the_floor_and_the_policy_it_found() -> None:
    platform = a_platform(floor=THE_FLOOR, reconciling_itself=True)

    Scenario() \
        .given(platform) \
        .when(lambda: _pinning(platform)) \
        .then(all_of(
            _the_descriptor_records_the_floor(THE_FLOOR),
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
        .when(lambda: _pinning(platform)) \
        .then(_the_descriptor_records_sync_was(False))


@pytest.mark.unit
def test_the_descriptor_records_the_floor_this_pin_asked_for() -> None:
    # Both floors, because the account of a pin is a transition and one number is
    # half of it. The floor it came from is what a withdrawal puts back; the floor
    # it went to is what a reader has to have in order to tell a controller that
    # was stopped from one that was merely nudged - and it is also the number a
    # withdrawal can compare against the live floor before writing, to find out
    # whether anybody has been in there since.
    platform = a_platform(floor=THE_FLOOR, ceiling=THE_CEILING)

    Scenario() \
        .given(platform) \
        .when(lambda: _pinning(platform)) \
        .then(all_of(
            _the_descriptor_records_the_floor(THE_FLOOR),
            _the_descriptor_records_the_floor_it_set(THE_CEILING)
        ))


@pytest.mark.unit
def test_the_floor_recorded_is_argus_own_cap_where_that_is_the_lower() -> None:
    # The case that makes this field worth having rather than a convenience. The
    # tier raises the floor to whichever of the two bounds is smaller, so a
    # sentence naming the destination as "its ceiling" is false exactly here - the
    # floor went to Argus's own cap and the ceiling is somewhere above it. A reader
    # told the ceiling would be told a number nothing wrote.
    platform = a_platform(
        floor=THE_FLOOR, ceiling=THE_MOST_REPLICAS_ARGUS_MAY_ASK_FOR + 1
    )

    Scenario() \
        .given(platform) \
        .when(lambda: _pinning(platform)) \
        .then(
            _the_descriptor_records_the_floor_it_set(
                THE_MOST_REPLICAS_ARGUS_MAY_ASK_FOR
            )
        )


@pytest.mark.unit
def test_an_autoscaler_already_held_still_is_refused_before_anything_changes() -> None:
    # A floor already at the ceiling is a count that is not moving, so there is
    # nothing here to stop. Refused rather than answered with a no-op: a caller
    # told "done" would record a mitigation that never happened and then judge the
    # service against it.
    platform = a_platform(floor=THE_CEILING, ceiling=THE_CEILING)

    Scenario() \
        .given(platform) \
        .when(attempting(lambda: _pinning(platform))) \
        .then(all_of(
            an_error_was_raised(AlreadyHeldStill),
            _nothing_was_changed(platform)
        ))


@pytest.mark.unit
def test_a_floor_already_past_what_argus_may_ask_for_is_refused() -> None:
    # The clamp and the refusal are one question asked once: where the floor is
    # already at or above the most Argus may pin it at, a pin would lower it - and
    # reducing a deployment's capacity is the thing nothing here does on its own.
    platform = a_platform(
        floor=THE_MOST_REPLICAS_ARGUS_MAY_ASK_FOR + 2,
        ceiling=THE_MOST_REPLICAS_ARGUS_MAY_ASK_FOR + 4
    )

    Scenario() \
        .given(platform) \
        .when(attempting(lambda: _pinning(platform))) \
        .then(all_of(
            an_error_was_raised(AlreadyHeldStill),
            _nothing_was_changed(platform)
        ))


@pytest.mark.unit
def test_a_platform_that_will_not_answer_is_not_reported_as_pinned() -> None:
    platform = a_platform()
    platform.get.side_effect = httpx2.ConnectError("no route to the platform")

    Scenario() \
        .given(platform) \
        .when(attempting(lambda: _pinning(platform))) \
        .then(all_of(
            an_error_was_raised(PinRefused),
            _nothing_was_changed(platform)
        ))


@pytest.mark.unit
def test_a_resource_the_platform_will_not_report_is_not_reported_as_pinned() -> None:
    # The tree named it and the read of it answered a refusal, which is a
    # different failure from an application that has no autoscaler at all - and
    # both have to leave the deployment untouched.
    platform = a_platform()
    platform.get.side_effect = lambda url, **dont_care_rest: (
        _an_ok(_a_resource_tree(holding_an_autoscaler=True))
        if url.endswith("/resource-tree")
        else httpx2.Response(
            status_code=404,
            json={"detail": "not found"},
            request=httpx2.Request("GET", DONT_CARE_URL)
        )
    )

    Scenario() \
        .given(platform) \
        .when(attempting(lambda: _pinning(platform))) \
        .then(all_of(
            an_error_was_raised(PinRefused),
            _nothing_was_changed(platform)
        ))


@pytest.mark.unit
def test_a_manifest_that_says_nothing_about_its_bounds_is_refused() -> None:
    # An autoscaler with no bounds in its manifest is one this cannot pin, and a
    # guessed ceiling would hold a shop at a size nobody declared.
    platform = a_platform()
    platform.get.side_effect = lambda url, **dont_care_rest: (
        _an_ok(_a_resource_tree(holding_an_autoscaler=True))
        if url.endswith("/resource-tree")
        else _an_ok({"manifest": json.dumps({"spec": {}})})
    )

    Scenario() \
        .given(platform) \
        .when(attempting(lambda: _pinning(platform))) \
        .then(all_of(
            an_error_was_raised(PinRefused),
            _nothing_was_changed(platform)
        ))


@pytest.mark.unit
def test_restoring_puts_back_the_floor_the_autoscaler_had() -> None:
    platform = a_platform()

    Scenario() \
        .given(a_descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: _restoring(a_descriptor, platform)) \
        .then(all_of(
            _it_asked_for_a_floor_of(platform, THE_FLOOR),
            _it_reports_restored(floor=True, automated_sync=True)
        ))


@pytest.mark.unit
def test_a_restore_asks_again_where_the_autoscaler_is() -> None:
    # Hours later, and nothing in the descriptor says where the resource lives -
    # deliberately, because where it lives is the platform's to say at the moment
    # the question is asked. A record of it taken when the pin was performed would
    # be a record that can have gone stale.
    platform = a_platform()

    Scenario() \
        .given(a_descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: _restoring(a_descriptor, platform)) \
        .then(_the_patch_was_addressed_to_the_autoscaler(platform))


@pytest.mark.unit
def test_a_restore_that_cannot_find_the_autoscaler_says_the_floor_is_not_back() -> None:
    # Reported rather than raised, for the reason the other half is: a withdrawal
    # has to be able to say which of the two things it managed, and a floor it
    # could not reach is one it did not put back.
    platform = a_platform(holding_an_autoscaler=False)

    Scenario() \
        .given(a_descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: _restoring(a_descriptor, platform)) \
        .then(_it_reports_restored(floor=False, automated_sync=True))


@pytest.mark.unit
def test_the_floor_is_put_back_before_reconciliation_is() -> None:
    # The order that leaves nothing to chance. Turning sync on first would have the
    # platform re-apply the manifest itself - to the same floor, and unverifiably,
    # at a moment nothing here chose.
    platform = a_platform()

    Scenario() \
        .given(a_descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: _restoring(a_descriptor, platform)) \
        .then(_it_wrote(platform, THE_PATCH, THE_SYNC_POLICY))


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
            _it_reports_restored(floor=True, automated_sync=True)
        ))


@pytest.mark.unit
def test_a_restore_that_only_managed_the_floor_says_so() -> None:
    # The half that fails is the quiet one: an autoscaler back at its declared
    # floor looks right from every angle a reader has, while the application
    # receives nothing anybody ships to it.
    platform = a_platform()
    platform.patch.side_effect = httpx2.ConnectError("no route to the platform")

    Scenario() \
        .given(a_descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: _restoring(a_descriptor, platform)) \
        .then(_it_reports_restored(floor=True, automated_sync=False))


@pytest.mark.unit
def test_a_restore_that_could_not_reach_the_platform_at_all_says_so() -> None:
    platform = a_platform()
    platform.post.side_effect = httpx2.ConnectError("no route to the platform")
    platform.patch.side_effect = httpx2.ConnectError("no route to the platform")

    Scenario() \
        .given(a_descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: _restoring(a_descriptor, platform)) \
        .then(_it_reports_restored(floor=False, automated_sync=False))


@pytest.mark.unit
def test_an_autoscaler_with_no_room_refuses_in_a_way_a_caller_can_recognise() -> None:
    # The pin's half of the same claim. Both of this tier's exhaustion refusals
    # have to be recognisable, and they are two exceptions in two modules - so a
    # marker applied to one and forgotten on the other is exactly the shape this
    # catches.
    platform = a_platform(floor=THE_CEILING, ceiling=THE_CEILING)

    Scenario() \
        .given(platform) \
        .when(attempting(lambda: _pinning(platform))) \
        .then(_the_refusal_says_the_action_is_exhausted())


@pytest.mark.unit
def test_a_platform_that_never_answered_the_read_is_reported_as_unreachable() -> None:
    # A pin begins by asking the platform what the application is made of, so on
    # a platform that is down this is where it finds out. Nothing has been
    # touched, which is what makes the report honest.
    platform = a_platform()
    platform.get.side_effect = httpx2.ConnectError("no route to host")

    Scenario() \
        .given(platform) \
        .when(attempting(lambda: _pinning(platform))) \
        .then(all_of(_it_is_reported_as_an_unreachable_platform()))


@pytest.mark.unit
def test_a_platform_unavailable_when_sync_is_suspended_is_reported_as_unreachable() -> None:
    # The suspension is the first thing a pin changes, so a platform that will
    # not take it has left the estate as it found it.
    platform = a_platform()
    platform.patch.side_effect = None
    platform.patch.return_value = _answering(503)

    Scenario() \
        .given(platform) \
        .when(attempting(lambda: _pinning(platform))) \
        .then(all_of(_it_is_reported_as_an_unreachable_platform()))


@pytest.mark.unit
def test_a_platform_that_died_before_a_pin_that_changed_nothing_is_unreachable() -> None:
    # An application nobody was reconciling needs no suspension, so the patch is
    # the first write - and a platform that stopped answering before it took
    # nothing with it.
    platform = a_platform(reconciling_itself=False)
    platform.post.side_effect = httpx2.ConnectError("no route to host")

    Scenario() \
        .given(platform) \
        .when(attempting(lambda: _pinning(platform))) \
        .then(all_of(_it_is_reported_as_an_unreachable_platform()))


@pytest.mark.unit
def test_a_pin_that_left_sync_suspended_says_so_and_still_reports_the_platform() -> None:
    # The last of the three. The platform is gone and the floor never moved, so
    # what is left behind is the suspension alone - and it travels on the
    # failure, so the walk can narrow itself and still know an application is
    # sitting un-reconciled.
    #
    # `min_replicas_asked_for` is the ceiling only while the arrangement's
    # ceiling is at or below the most replicas Argus may ask for. It is six here,
    # so the two coincide; a case that raised the ceiling past that cap would
    # have to name the cap instead.
    platform = a_platform(reconciling_itself=True)
    platform.post.side_effect = httpx2.ConnectError("no route to host")

    Scenario() \
        .given(platform) \
        .when(attempting(lambda: _pinning(platform))) \
        .then(all_of(
            _it_is_reported_as_an_unreachable_platform(),
            _it_says_what_it_left_behind(AutoscalerUndo(
                application=SOME_APPLICATION,
                was_min_replicas=THE_FLOOR,
                min_replicas_asked_for=THE_CEILING,
                was_syncing_itself=True
            ))
        ))


@pytest.mark.unit
def test_a_platform_that_answered_and_refused_is_not_reported_as_unreachable() -> None:
    # Reachable, and this patch is what it would not take. The restart and the
    # scale-out are still worth reaching for, and what a person has to look at
    # is the refusal rather than the platform.
    platform = a_platform(reconciling_itself=False)
    platform.post.side_effect = None
    platform.post.return_value = _answering(400)

    Scenario() \
        .given(platform) \
        .when(attempting(lambda: _pinning(platform))) \
        .then(all_of(_it_is_not_reported_as_an_unreachable_platform()))


def _answering(status: int) -> httpx2.Response:
    """One of the platform's own answers, as `raise_for_status` will read it."""
    return httpx2.Response(
        status_code=status,
        json={},
        request=httpx2.Request("PATCH", DONT_CARE_URL)
    )


def _it_is_reported_as_an_unreachable_platform() -> Assertion[Exception | None]:
    def assertion(raised: Exception | None) -> bool:
        if not isinstance(raised, PinRefused):
            raise AssertionError(
                f"Expected the pin to be refused, and what was raised was "
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
        if not isinstance(raised, PinRefused):
            raise AssertionError(
                f"Expected the pin to be refused, and what was raised was "
                f"{raised!r}."
            )

        if UNREACHABLE_PLATFORM_MARKER in str(raised):
            raise AssertionError(
                f"Expected the refusal to be reported as this action's own, and "
                f"it reported a platform that could not be reached: [{raised}]."
            )

        return True

    return assertion


def _the_refusal_says_the_action_is_exhausted() -> Assertion[Exception | None]:
    """The refusal carries the marker the transport turns into a type.

    Asserted against the marker rather than the sentence, because the sentence is
    allowed to change and the marker is not. The kernel's suite proves a marked
    refusal arrives as `ActionExhausted`; this proves this refusal is marked, and
    this is the end that has to remember to apply it.
    """
    def assertion(refusal: Exception | None) -> bool:
        if refusal is None or EXHAUSTED_ACTION_MARKER not in str(refusal):
            raise AssertionError(
                f"Expected the refusal to carry [{EXHAUSTED_ACTION_MARKER}], so "
                f"that a caller can tell an exhausted action from a broken "
                f"platform, and it said [{refusal}]."
            )

        return True

    return assertion


def _restoring(descriptor: AutoscalerUndo,
               platform: _Platform) -> AutoscalingRestored:
    return restore_autoscaler_floor(
        descriptor,
        _settings(),
        get=platform.get,
        post=platform.post,
        patch=platform.patch
    )


def _a_descriptor(was_syncing_itself: bool) -> AutoscalerUndo:
    return AutoscalerUndo(
        application=SOME_APPLICATION,
        was_min_replicas=THE_FLOOR,
        min_replicas_asked_for=THE_CEILING,
        was_syncing_itself=was_syncing_itself
    )


def _the_patch_sent(platform: _Platform) -> str | None:
    """The patch body as it went onto the wire, which is a string or nothing."""
    if not platform.post.called:
        return None

    body = platform.post.call_args.kwargs.get("json")

    return body if isinstance(body, str) else None


def _the_selectors_of(call: Any) -> dict[str, Any]:
    return dict(call.kwargs.get("params") or {})


def _addresses_the_autoscaler(selectors: dict[str, Any]) -> bool:
    return (
        selectors.get("kind") == AUTOSCALER_KIND
        and selectors.get("group") == AUTOSCALER_GROUP
        and selectors.get("version") == AUTOSCALER_VERSION
        and selectors.get("resourceName") == SOME_AUTOSCALER_NAME
        and selectors.get("namespace") == SOME_NAMESPACE
    )


def _it_asked_for_a_floor_of(platform: _Platform, floor: int) -> Assertion[object]:
    def assertion(dont_care_result: object) -> bool:
        if not platform.post.called:
            raise AssertionError(
                f"Expected the platform to be asked for a floor of [{floor}] "
                f"replicas, and no patch was sent at all."
            )

        patch = _the_patch_sent(platform)
        asked = json.loads(patch).get("spec", {}).get("minReplicas") if patch else None

        if asked != floor:
            raise AssertionError(
                f"Expected the platform to be asked for a floor of [{floor}] "
                f"replicas, and it was asked for [{asked}]."
            )

        return True

    return assertion


def _the_resource_it_read_was_the_autoscaler(
    platform: _Platform
) -> Assertion[object]:
    def assertion(dont_care_result: object) -> bool:
        read = [
            _the_selectors_of(call) for call in platform.get.call_args_list
            if str(call.args[0] if call.args else "").endswith("/resource")
        ]

        if not read:
            raise AssertionError(
                "Expected the live autoscaler to be read, and no resource was "
                "read at all."
            )

        if not any(_addresses_the_autoscaler(selectors) for selectors in read):
            raise AssertionError(
                f"Expected the resource read to be addressed at "
                f"[{AUTOSCALER_GROUP}/{AUTOSCALER_VERSION} {AUTOSCALER_KIND}] "
                f"named [{SOME_AUTOSCALER_NAME}] in [{SOME_NAMESPACE}], as the "
                f"tree reported it, and it was addressed as {read}."
            )

        return True

    return assertion


def _the_patch_was_addressed_to_the_autoscaler(
    platform: _Platform
) -> Assertion[object]:
    def assertion(dont_care_result: object) -> bool:
        if not platform.post.called:
            raise AssertionError(
                "Expected the autoscaler to be patched, and no patch was sent at "
                "all."
            )

        sent = _the_selectors_of(platform.post.call_args)

        if not _addresses_the_autoscaler(sent):
            raise AssertionError(
                f"Expected the patch to be addressed at "
                f"[{AUTOSCALER_KIND}] named [{SOME_AUTOSCALER_NAME}] in "
                f"[{SOME_NAMESPACE}], as the tree reported it, and it was "
                f"addressed as {sent}."
            )

        return True

    return assertion


def _the_patch_was_sent_as_text(platform: _Platform) -> Assertion[object]:
    def assertion(dont_care_result: object) -> bool:
        body = platform.post.call_args.kwargs.get("json")

        if not isinstance(body, str):
            raise AssertionError(
                f"Expected the patch to be carried as a JSON-encoded string, as "
                f"the platform carries it, and it was sent as [{type(body)}]."
            )

        return True

    return assertion


def _it_was_sent_as_a_merge_patch(platform: _Platform) -> Assertion[object]:
    def assertion(dont_care_result: object) -> bool:
        sent = _the_selectors_of(platform.post.call_args).get("patchType")

        if sent != MERGE_PATCH_TYPE:
            raise AssertionError(
                f"Expected the patch to be sent as [{MERGE_PATCH_TYPE}], and it "
                f"was sent as [{sent}]."
            )

        return True

    return assertion


def _it_wrote(platform: _Platform, *in_order: str) -> Assertion[object]:
    def assertion(dont_care_result: object) -> bool:
        if platform.wrote != list(in_order):
            raise AssertionError(
                f"Expected the platform to be written in the order "
                f"{list(in_order)}, and it was written {platform.wrote}."
            )

        return True

    return assertion


def _reconciliation_was_turned(platform: _Platform, off: bool) -> Assertion[object]:
    """One merge patch to the application's own route, of the switch alone.

    `enabled: false` to suspend and a removed `enabled` to restore - never an
    `automated` object of Argus's own, which would replace the one the operator
    declared, and never the spec route, which takes its body as the whole spec.
    """
    def assertion(dont_care_result: object) -> bool:
        if not platform.patch.called:
            raise AssertionError(
                "Expected the sync policy to be written, and it was not written "
                "at all."
            )

        expected = _the_switch_set_to(False if off else None)
        url = platform.patch.call_args.args[0]
        body = platform.patch.call_args.kwargs["json"]

        if url != THE_APPLICATIONS_ROUTE:
            raise AssertionError(
                f"Expected the sync policy to be patched at "
                f"[{THE_APPLICATIONS_ROUTE}], and it was patched at [{url}]."
            )

        if body[PATCH_REQUEST_TYPE] != APPLICATION_MERGE_PATCH:
            raise AssertionError(
                f"Expected a [{APPLICATION_MERGE_PATCH}] patch, and it was sent "
                f"as [{body[PATCH_REQUEST_TYPE]}]."
            )

        if _the_sync_patches(platform) != [expected]:
            raise AssertionError(
                f"Expected automated sync to be turned {'off' if off else 'on'} "
                f"by one patch of {expected}, and it was sent "
                f"{_the_sync_patches(platform)}."
            )

        return True

    return assertion

def _the_sync_patches(platform: _Platform) -> list[dict[str, Any]]:
    """Every merge patch the application route was sent, parsed, in order.

    Parsed rather than compared as text, because the vendor carries the patch
    as a JSON-encoded string and the order of its keys is nobody's contract.
    """
    return [
        json.loads(call.kwargs["json"][PATCH_REQUEST_PATCH])
        for call in platform.patch.call_args_list
    ]


def _the_switch_set_to(enabled: bool | None) -> dict[str, Any]:
    return {SPEC: {SYNC_POLICY: {AUTOMATED: {ENABLED: enabled}}}}


def _the_sync_policy_was_not_touched(platform: _Platform) -> Assertion[object]:
    def assertion(dont_care_result: object) -> bool:
        if platform.patch.called:
            raise AssertionError(
                f"Expected the sync policy to be left as it was found, and it "
                f"was patched with [{platform.patch.call_args.kwargs['json']}]."
            )

        return True

    return assertion


def _nothing_was_changed(platform: _Platform) -> Assertion[Exception | None]:
    def assertion(dont_care_error: Exception | None) -> bool:
        changed = [
            name for name, route in ((THE_PATCH, platform.post),
                                     (THE_SYNC_POLICY, platform.patch))
            if route.called
        ]

        if changed:
            raise AssertionError(
                f"Expected a refusal to change nothing, and it wrote "
                f"{sorted(changed)}."
            )

        return True

    return assertion


def _the_descriptor_records_the_floor(floor: int) -> Assertion[AutoscalerUndo]:
    def assertion(descriptor: AutoscalerUndo) -> bool:
        if descriptor.was_min_replicas != floor:
            raise AssertionError(
                f"Expected the descriptor to record [{floor}] replicas as the "
                f"floor the autoscaler had, and it records "
                f"[{descriptor.was_min_replicas}]."
            )

        return True

    return assertion


def _the_descriptor_records_the_floor_it_set(floor: int) -> Assertion[AutoscalerUndo]:
    def assertion(descriptor: AutoscalerUndo) -> bool:
        if descriptor.min_replicas_asked_for != floor:
            raise AssertionError(
                f"Expected the descriptor to record [{floor}] replicas as the "
                f"floor this pin asked for, and it records "
                f"[{descriptor.min_replicas_asked_for}]."
            )

        return True

    return assertion


def _the_descriptor_records_sync_was(syncing: bool) -> Assertion[AutoscalerUndo]:
    def assertion(descriptor: AutoscalerUndo) -> bool:
        if descriptor.was_syncing_itself != syncing:
            raise AssertionError(
                f"Expected the descriptor to record automated sync as "
                f"[{syncing}] when Argus found it, and it records "
                f"[{descriptor.was_syncing_itself}]."
            )

        return True

    return assertion


def _it_reports_restored(floor: bool,
                         automated_sync: bool) -> Assertion[AutoscalingRestored]:
    def assertion(restored: AutoscalingRestored) -> bool:
        reported = (restored.floor_put_back, restored.automated_sync_put_back)

        if reported != (floor, automated_sync):
            raise AssertionError(
                f"Expected the floor put back to be [{floor}] and automated "
                f"sync to be [{automated_sync}], and it reported {reported}."
            )

        return True

    return assertion


def _it_says_what_it_left_behind(
    expected: AutoscalerUndo
) -> Assertion[Exception | None]:
    """The refusal carries the descriptor, and carries the right one.

    The third of the three, for the same reason and with the same shape. Not
    lifted anywhere shared: each compares a different descriptor type, and one
    version would take the union and stop telling a pin's from a scale-out's.
    """
    def assertion(raised: Exception | None) -> bool:
        if LEFT_BEHIND_MARKER not in str(raised):
            raise AssertionError(
                f"Expected the refusal to say what it left behind, and it said "
                f"[{raised}]."
            )

        carried = what_was_left_behind(str(raised))

        if carried != expected:
            raise AssertionError(
                f"Expected the refusal to leave {expected!r} to be put back, it "
                f"left {carried!r}."
            )

        return True

    return assertion
