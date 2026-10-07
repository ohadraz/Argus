"""Rolling a deployment back through the platform's own rollback.

What is worth pinning is the order and the refusals, because both are the
platform's rules rather than this module's preferences. A real Argo CD refuses
a rollback while it is reconciling the application itself, so suspending that
is part of performing one - and an application with no earlier entry has
nothing to roll back to, which has to be found out before anything is touched.

The descriptor is the other half. Only this module ever knows which entry was
running or whether reconciliation was on, so a withdrawal hours later can put
back exactly as much as this records and no more.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import MagicMock, create_autospec

import httpx2
import pytest
from argus_core.mcp_transport import (
    LEFT_BEHIND_MARKER,
    UNREACHABLE_PLATFORM_MARKER,
    what_was_left_behind,
)
from argus_core.models import DeploymentRestored, DeploymentRollbackUndo
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
from write_mcp_server.rolling_back import (
    NoEarlierRevision,
    RollbackRefused,
    RollbackSettings,
    restore_deployment,
    roll_back_deployment,
)

SOME_APPLICATION = "io-shop"
DONT_CARE_URL = "http://argocd.invalid"
SOME_APPLICATION_PATH = "/api/v1/applications/{application}"
SOME_ROLLBACK_PATH = "/api/v1/applications/{application}/rollback"
# Where the application itself is, which is where a patch to it goes.
THE_APPLICATIONS_ROUTE = f"{DONT_CARE_URL}/api/v1/applications/{SOME_APPLICATION}"

THE_ENTRY_RUNNING = 2
THE_ENTRY_BEFORE_IT = 1
THE_REVISION_RUNNING = "0d8e826225f0de73958a8a8dd3d867b2ae249e72"
THE_REVISION_BEFORE_IT = "544cef36a8eaf45c5b030c3d5c21473d8176cef3"

# Automated sync as an operator declares it, and as one switches it off while
# keeping what it was configured to do. Whichever of the two an application
# carries, `selfHeal` is in it - so a module that wrote an `automated` object of
# its own would be a module that dropped it.
SYNCING_ITSELF = {"selfHeal": True}
SWITCHED_OFF = {"selfHeal": True, ENABLED: False}


@dataclass
class _Platform:
    """The three routes a rollback touches, each answering as Argo CD does."""

    get: MagicMock = field(default_factory=lambda: create_autospec(httpx2.get))
    post: MagicMock = field(default_factory=lambda: create_autospec(httpx2.post))
    patch: MagicMock = field(default_factory=lambda: create_autospec(httpx2.patch))


def _settings() -> RollbackSettings:
    return RollbackSettings(
        argocd_base_url=DONT_CARE_URL,
        argocd_application_path=SOME_APPLICATION_PATH,
        argocd_rollback_path=SOME_ROLLBACK_PATH,
        argocd_auth_token=""
    )


def _an_application(history: list[dict[str, Any]],
                    automated: dict[str, Any] | None) -> dict[str, Any]:
    policy: dict[str, Any] = {AUTOMATED: automated} if automated is not None else {}

    return {
        SPEC: {SYNC_POLICY: policy},
        "status": {"history": history}
    }


def _two_deployments() -> list[dict[str, Any]]:
    return [
        {"id": THE_ENTRY_BEFORE_IT, "revision": THE_REVISION_BEFORE_IT},
        {"id": THE_ENTRY_RUNNING, "revision": THE_REVISION_RUNNING}
    ]


def _an_ok(body: dict[str, Any] | None = None) -> httpx2.Response:
    return httpx2.Response(
        status_code=200,
        json=body if body is not None else {},
        request=httpx2.Request("GET", DONT_CARE_URL)
    )


def a_platform(history: list[dict[str, Any]] | None = None,
               automated: dict[str, Any] | None = SYNCING_ITSELF) -> _Platform:
    platform = _Platform()
    platform.get.return_value = _an_ok(
        _an_application(
            history if history is not None else _two_deployments(),
            automated
        )
    )
    platform.post.return_value = _an_ok()
    platform.patch.return_value = _an_ok()

    return platform


def _rolling_back(platform: _Platform) -> DeploymentRollbackUndo:
    return roll_back_deployment(
        SOME_APPLICATION,
        _settings(),
        get=platform.get,
        post=platform.post,
        patch=platform.patch
    )


@pytest.mark.unit
def test_a_rollback_returns_to_the_entry_before_the_one_running() -> None:
    # Which entry is the platform's to choose, and the choice is the one
    # `argocd app rollback APPNAME` makes with its id omitted.
    platform = a_platform()

    Scenario() \
        .given(platform) \
        .when(lambda: _rolling_back(platform)) \
        .then(_it_rolled_back_to(platform, THE_ENTRY_BEFORE_IT))


@pytest.mark.unit
def test_reconciliation_is_suspended_before_the_rollback_is_asked_for() -> None:
    # The platform refuses a rollback while it syncs the application itself,
    # and would re-apply the revision being rolled away from at the next pass.
    platform = a_platform(automated=SYNCING_ITSELF)

    Scenario() \
        .given(platform) \
        .when(lambda: _rolling_back(platform)) \
        .then(all_of(
            _reconciliation_was_turned(platform, off=True),
            _it_rolled_back_to(platform, THE_ENTRY_BEFORE_IT)
        ))


@pytest.mark.unit
def test_an_application_nobody_was_reconciling_is_left_alone() -> None:
    platform = a_platform(automated=None)

    Scenario() \
        .given(platform) \
        .when(lambda: _rolling_back(platform)) \
        .then(all_of(
            _the_sync_policy_was_not_touched(platform),
            _the_descriptor_records_sync_was(False)
        ))


@pytest.mark.unit
def test_an_application_whose_automated_sync_is_switched_off_is_left_alone() -> None:
    # Read as the platform reads it: an `automated` carrying `enabled: false` is
    # configured and not syncing. Suspending it would change nothing, and an undo
    # that later turned it back on would start something Argus did not stop.
    platform = a_platform(automated=SWITCHED_OFF)

    Scenario() \
        .given(platform) \
        .when(lambda: _rolling_back(platform)) \
        .then(all_of(
            _the_sync_policy_was_not_touched(platform),
            _the_descriptor_records_sync_was(False),
            _it_rolled_back_to(platform, THE_ENTRY_BEFORE_IT)
        ))


@pytest.mark.unit
def test_the_descriptor_records_the_entry_and_revision_that_were_running() -> None:
    # Only this module ever knows them. A withdrawal hours later can put back
    # exactly as much as this records.
    platform = a_platform()

    Scenario() \
        .given(platform) \
        .when(lambda: _rolling_back(platform)) \
        .then(all_of(
            _the_descriptor_records_it_was_on(THE_ENTRY_RUNNING,
                                              THE_REVISION_RUNNING),
            _the_descriptor_records_sync_was(True)
        ))


@pytest.mark.unit
def test_an_application_with_no_earlier_entry_is_refused_before_anything_changes() -> None:
    # An application on its first deployment. Told "done", a caller would
    # record a mitigation that never happened and judge the service against it.
    only_ever_deployed_once = [
        {"id": THE_ENTRY_RUNNING, "revision": THE_REVISION_RUNNING}
    ]
    platform = a_platform(history=only_ever_deployed_once)

    Scenario() \
        .given(platform) \
        .when(attempting(lambda: _rolling_back(platform))) \
        .then(all_of(
            an_error_was_raised(NoEarlierRevision),
            _nothing_was_changed(platform)
        ))


@pytest.mark.unit
def test_an_application_that_has_never_deployed_is_refused() -> None:
    platform = a_platform(history=[])

    Scenario() \
        .given(platform) \
        .when(attempting(lambda: _rolling_back(platform))) \
        .then(all_of(
            an_error_was_raised(NoEarlierRevision),
            _nothing_was_changed(platform)
        ))


@pytest.mark.unit
def test_a_platform_that_will_not_answer_is_not_reported_as_rolled_back() -> None:
    platform = a_platform()
    platform.post.side_effect = httpx2.ConnectError("no route to host")

    Scenario() \
        .given(platform) \
        .when(attempting(lambda: _rolling_back(platform))) \
        .then(an_error_was_raised(RollbackRefused))


@pytest.mark.unit
def test_restoring_puts_back_the_entry_that_was_running() -> None:
    platform = a_platform()

    Scenario() \
        .given(descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: restore_deployment(
            descriptor, _settings(), post=platform.post, patch=platform.patch
        )) \
        .then(all_of(
            _it_rolled_back_to(platform, THE_ENTRY_RUNNING),
            _it_reports_restored(revision=True, automated_sync=True)
        ))


@pytest.mark.unit
def test_restoring_turns_reconciliation_back_on_where_it_was_on() -> None:
    platform = a_platform()

    Scenario() \
        .given(descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: restore_deployment(
            descriptor, _settings(), post=platform.post, patch=platform.patch
        )) \
        .then(_reconciliation_was_turned(platform, off=False))


@pytest.mark.unit
def test_restoring_leaves_reconciliation_off_where_argus_found_it_off() -> None:
    # Turning it on because that is the usual arrangement would be Argus
    # starting something it did not stop.
    platform = a_platform()

    Scenario() \
        .given(descriptor := _a_descriptor(was_syncing_itself=False)) \
        .when(lambda: restore_deployment(
            descriptor, _settings(), post=platform.post, patch=platform.patch
        )) \
        .then(all_of(
            _the_sync_policy_was_not_touched(platform),
            _it_reports_restored(revision=True, automated_sync=True)
        ))


@pytest.mark.unit
def test_a_restore_that_only_managed_the_revision_says_so() -> None:
    # The half that is easy to lose. The deployment looks right and is
    # receiving nothing anybody ships to it.
    platform = a_platform()
    platform.patch.side_effect = httpx2.ConnectError("no route to host")

    Scenario() \
        .given(descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: restore_deployment(
            descriptor, _settings(), post=platform.post, patch=platform.patch
        )) \
        .then(_it_reports_restored(revision=True, automated_sync=False))


@pytest.mark.unit
def test_a_restore_that_could_not_reach_the_platform_at_all_says_so() -> None:
    platform = a_platform()
    platform.post.side_effect = httpx2.ConnectError("no route to host")
    platform.patch.side_effect = httpx2.ConnectError("no route to host")

    Scenario() \
        .given(descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: restore_deployment(
            descriptor, _settings(), post=platform.post, patch=platform.patch
        )) \
        .then(_it_reports_restored(revision=False, automated_sync=False))


@pytest.mark.unit
def test_a_platform_that_never_answered_the_read_is_reported_as_unreachable() -> None:
    # Nothing has been touched when this fails, which is what makes the report
    # honest: the walk is told that four actions are unavailable and told
    # nothing about a state somebody has to put back.
    platform = a_platform()
    platform.get.side_effect = httpx2.ConnectError("no route to host")

    Scenario() \
        .given(platform) \
        .when(attempting(lambda: _rolling_back(platform))) \
        .then(all_of(_it_is_reported_as_an_unreachable_platform()))


@pytest.mark.unit
def test_a_platform_unavailable_when_sync_is_suspended_is_reported_as_unreachable() -> None:
    # The suspension is the first thing a rollback changes, so a platform that
    # refuses it has left the estate exactly as it found it.
    platform = a_platform()
    platform.patch.return_value = _answering(503)

    Scenario() \
        .given(platform) \
        .when(attempting(lambda: _rolling_back(platform))) \
        .then(all_of(_it_is_reported_as_an_unreachable_platform()))


@pytest.mark.unit
def test_a_platform_that_died_before_a_rollback_that_changed_nothing_is_unreachable() -> None:
    # An application nobody was reconciling needs no suspension, so the rollback
    # request is the first write - and a platform that stopped answering before
    # it took nothing with it.
    platform = a_platform(automated=None)
    platform.post.side_effect = httpx2.ConnectError("no route to host")

    Scenario() \
        .given(platform) \
        .when(attempting(lambda: _rolling_back(platform))) \
        .then(all_of(_it_is_reported_as_an_unreachable_platform()))

@pytest.mark.unit
def test_a_rollback_that_left_sync_suspended_says_so_and_still_reports_the_platform() -> None:
    # Both, and the reason it is both is the reason this mode exists at all. The
    # platform is gone, so every action through it is unavailable - and that is
    # true however far into this one the outage arrived. Reporting it as this
    # action's own failure would narrow the walk or not depending on which call
    # the outage landed on, which is learning the scenario rather than the mode.
    #
    # The suspension landed and the revision never moved, so what is left behind
    # is one boolean this tier put there. It travels on the failure, which is
    # what makes marking safe: the earlier rule refused the mark because a
    # suspension was recorded nowhere, and now it is recorded here.
    platform = a_platform(automated=SYNCING_ITSELF)
    platform.post.side_effect = httpx2.ConnectError("no route to host")

    Scenario() \
        .given(platform) \
        .when(attempting(lambda: _rolling_back(platform))) \
        .then(all_of(
            _it_is_reported_as_an_unreachable_platform(),
            _it_says_what_it_left_behind(DeploymentRollbackUndo(
                application=SOME_APPLICATION,
                was_on_history_id=THE_ENTRY_RUNNING,
                was_on_revision=THE_REVISION_RUNNING,
                was_syncing_itself=True
            ))
        ))


@pytest.mark.unit
def test_a_platform_that_answered_and_refused_is_not_reported_as_unreachable() -> None:
    # The distinction the change rests on. This platform is reachable and this
    # rollback is what it would not do, so the other actions through it are
    # still worth trying.
    platform = a_platform(automated=None)
    platform.post.return_value = _answering(400)

    Scenario() \
        .given(platform) \
        .when(attempting(lambda: _rolling_back(platform))) \
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
        if not isinstance(raised, RollbackRefused):
            raise AssertionError(
                f"Expected the rollback to be refused, and what was raised was "
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
        if not isinstance(raised, RollbackRefused):
            raise AssertionError(
                f"Expected the rollback to be refused, and what was raised was "
                f"{raised!r}."
            )

        if UNREACHABLE_PLATFORM_MARKER in str(raised):
            raise AssertionError(
                f"Expected the refusal to be reported as this action's own, and "
                f"it reported a platform that could not be reached: [{raised}]."
            )

        return True

    return assertion


def _a_descriptor(was_syncing_itself: bool) -> DeploymentRollbackUndo:
    return DeploymentRollbackUndo(
        application=SOME_APPLICATION,
        was_on_history_id=THE_ENTRY_RUNNING,
        was_on_revision=THE_REVISION_RUNNING,
        was_syncing_itself=was_syncing_itself
    )


def _the_rollback_body(platform: _Platform) -> dict[str, Any]:
    return dict(platform.post.call_args.kwargs.get("json", {}))


def _it_rolled_back_to(platform: _Platform, entry: int) -> Assertion[object]:
    def assertion(dont_care: object) -> bool:
        asked = _the_rollback_body(platform).get("id")

        if asked != entry:
            raise AssertionError(
                f"Expected a rollback to history entry [{entry}], and it asked "
                f"for [{asked}]."
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
                "Expected the sync policy to be written, and it was not."
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
    def assertion(dont_care: object) -> bool:
        if platform.patch.called:
            raise AssertionError(
                f"Expected the sync policy to be left alone, and it was patched "
                f"with {platform.patch.call_args.kwargs.get('json')}."
            )

        return True

    return assertion


def _nothing_was_changed(platform: _Platform) -> Assertion[Exception | None]:
    def assertion(dont_care: Exception | None) -> bool:
        if platform.post.called or platform.patch.called:
            raise AssertionError(
                "Expected nothing to be changed, and the platform was written to."
            )

        return True

    return assertion


def _the_descriptor_records_it_was_on(entry: int,
                                      revision: str) -> Assertion[DeploymentRollbackUndo]:
    def assertion(descriptor: DeploymentRollbackUndo) -> bool:
        actual = (descriptor.was_on_history_id, descriptor.was_on_revision)

        if actual != (entry, revision):
            raise AssertionError(
                f"Expected the descriptor to record entry [{entry}] at "
                f"[{revision}], and it recorded {actual}."
            )

        return True

    return assertion


def _the_descriptor_records_sync_was(syncing: bool) -> Assertion[DeploymentRollbackUndo]:
    def assertion(descriptor: DeploymentRollbackUndo) -> bool:
        if descriptor.was_syncing_itself is not syncing:
            raise AssertionError(
                f"Expected the descriptor to record reconciliation as "
                f"[{syncing}], and it recorded [{descriptor.was_syncing_itself}]."
            )

        return True

    return assertion


def _it_reports_restored(revision: bool,
                         automated_sync: bool) -> Assertion[DeploymentRestored]:
    def assertion(restored: DeploymentRestored) -> bool:
        if (restored.revision_put_back,
                restored.automated_sync_put_back) != (revision, automated_sync):
            raise AssertionError(
                f"Expected a restore reporting revision={revision} "
                f"automated_sync={automated_sync}, and it reported "
                f"revision={restored.revision_put_back} "
                f"automated_sync={restored.automated_sync_put_back}."
            )

        return True

    return assertion


def _it_says_what_it_left_behind(
    expected: DeploymentRollbackUndo
) -> Assertion[Exception | None]:
    """The refusal carries the descriptor, and carries the right one.

    Compared as a value rather than checked for presence, because a descriptor
    that reached the walk with a field lost would put back something other than
    what was changed - and would satisfy every assertion short of this one.
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
