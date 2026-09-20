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

from dataclasses import dataclass, field
from typing import Any
from unittest.mock import MagicMock, create_autospec

import httpx
import pytest
from argus_core.models import ConfigRollbackUndo, ConfigurationRestored
from argus_testkit import Assertion, Scenario, all_of, an_error_was_raised, attempting
from write_mcp_server.rolling_back import (
    NoEarlierRevision,
    RollbackRefused,
    RollbackSettings,
    restore_configuration,
    roll_back_configuration,
)

SOME_APPLICATION = "io-shop"
DONT_CARE_URL = "http://argocd.invalid"
SOME_APPLICATION_PATH = "/api/v1/applications/{application}"
SOME_ROLLBACK_PATH = "/api/v1/applications/{application}/rollback"
SOME_SPEC_PATH = "/api/v1/applications/{application}/spec"

THE_ENTRY_RUNNING = 2
THE_ENTRY_BEFORE_IT = 1
THE_REVISION_RUNNING = "0d8e826225f0de73958a8a8dd3d867b2ae249e72"
THE_REVISION_BEFORE_IT = "544cef36a8eaf45c5b030c3d5c21473d8176cef3"


@dataclass
class _Platform:
    """The three routes a rollback touches, each answering as Argo CD does."""

    get: MagicMock = field(default_factory=lambda: create_autospec(httpx.get))
    post: MagicMock = field(default_factory=lambda: create_autospec(httpx.post))
    put: MagicMock = field(default_factory=lambda: create_autospec(httpx.put))


def _settings() -> RollbackSettings:
    return RollbackSettings(
        argocd_base_url=DONT_CARE_URL,
        argocd_application_path=SOME_APPLICATION_PATH,
        argocd_rollback_path=SOME_ROLLBACK_PATH,
        argocd_spec_path=SOME_SPEC_PATH,
        argocd_auth_token=""
    )


def _an_application(history: list[dict[str, Any]],
                    reconciling_itself: bool) -> dict[str, Any]:
    policy: dict[str, Any] = {"automated": {}} if reconciling_itself else {}

    return {
        "spec": {"syncPolicy": policy},
        "status": {"history": history}
    }


def _two_deployments() -> list[dict[str, Any]]:
    return [
        {"id": THE_ENTRY_BEFORE_IT, "revision": THE_REVISION_BEFORE_IT},
        {"id": THE_ENTRY_RUNNING, "revision": THE_REVISION_RUNNING}
    ]


def _an_ok(body: dict[str, Any] | None = None) -> httpx.Response:
    return httpx.Response(
        status_code=200,
        json=body if body is not None else {},
        request=httpx.Request("GET", DONT_CARE_URL)
    )


def a_platform(history: list[dict[str, Any]] | None = None,
               reconciling_itself: bool = True) -> _Platform:
    platform = _Platform()
    platform.get.return_value = _an_ok(
        _an_application(
            history if history is not None else _two_deployments(),
            reconciling_itself
        )
    )
    platform.post.return_value = _an_ok()
    platform.put.return_value = _an_ok()

    return platform


def _rolling_back(platform: _Platform) -> ConfigRollbackUndo:
    return roll_back_configuration(
        SOME_APPLICATION,
        _settings(),
        get=platform.get,
        post=platform.post,
        put=platform.put
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
    platform = a_platform(reconciling_itself=True)

    Scenario() \
        .given(platform) \
        .when(lambda: _rolling_back(platform)) \
        .then(all_of(
            _reconciliation_was_turned(platform, off=True),
            _it_rolled_back_to(platform, THE_ENTRY_BEFORE_IT)
        ))


@pytest.mark.unit
def test_an_application_nobody_was_reconciling_is_left_alone() -> None:
    platform = a_platform(reconciling_itself=False)

    Scenario() \
        .given(platform) \
        .when(lambda: _rolling_back(platform)) \
        .then(all_of(
            _the_sync_policy_was_not_touched(platform),
            _the_descriptor_records_sync_was(False)
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
    platform.post.side_effect = httpx.ConnectError("no route to host")

    Scenario() \
        .given(platform) \
        .when(attempting(lambda: _rolling_back(platform))) \
        .then(an_error_was_raised(RollbackRefused))


@pytest.mark.unit
def test_restoring_puts_back_the_entry_that_was_running() -> None:
    platform = a_platform()

    Scenario() \
        .given(descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: restore_configuration(
            descriptor, _settings(), post=platform.post, put=platform.put
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
        .when(lambda: restore_configuration(
            descriptor, _settings(), post=platform.post, put=platform.put
        )) \
        .then(_reconciliation_was_turned(platform, off=False))


@pytest.mark.unit
def test_restoring_leaves_reconciliation_off_where_argus_found_it_off() -> None:
    # Turning it on because that is the usual arrangement would be Argus
    # starting something it did not stop.
    platform = a_platform()

    Scenario() \
        .given(descriptor := _a_descriptor(was_syncing_itself=False)) \
        .when(lambda: restore_configuration(
            descriptor, _settings(), post=platform.post, put=platform.put
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
    platform.put.side_effect = httpx.ConnectError("no route to host")

    Scenario() \
        .given(descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: restore_configuration(
            descriptor, _settings(), post=platform.post, put=platform.put
        )) \
        .then(_it_reports_restored(revision=True, automated_sync=False))


@pytest.mark.unit
def test_a_restore_that_could_not_reach_the_platform_at_all_says_so() -> None:
    platform = a_platform()
    platform.post.side_effect = httpx.ConnectError("no route to host")
    platform.put.side_effect = httpx.ConnectError("no route to host")

    Scenario() \
        .given(descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: restore_configuration(
            descriptor, _settings(), post=platform.post, put=platform.put
        )) \
        .then(_it_reports_restored(revision=False, automated_sync=False))


def _a_descriptor(was_syncing_itself: bool) -> ConfigRollbackUndo:
    return ConfigRollbackUndo(
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
    def assertion(dont_care: object) -> bool:
        if not platform.put.called:
            raise AssertionError(
                "Expected the sync policy to be written, and it was not."
            )

        policy = platform.put.call_args.kwargs["json"]["syncPolicy"]
        was_turned_off = policy.get("automated") is None

        if was_turned_off is not off:
            raise AssertionError(
                f"Expected reconciliation to be turned {'off' if off else 'on'}, "
                f"and the policy written was {policy}."
            )

        return True

    return assertion


def _the_sync_policy_was_not_touched(platform: _Platform) -> Assertion[object]:
    def assertion(dont_care: object) -> bool:
        if platform.put.called:
            raise AssertionError(
                f"Expected the sync policy to be left alone, and it was written "
                f"as {platform.put.call_args.kwargs.get('json')}."
            )

        return True

    return assertion


def _nothing_was_changed(platform: _Platform) -> Assertion[Exception | None]:
    def assertion(dont_care: Exception | None) -> bool:
        if platform.post.called or platform.put.called:
            raise AssertionError(
                "Expected nothing to be changed, and the platform was written to."
            )

        return True

    return assertion


def _the_descriptor_records_it_was_on(entry: int,
                                      revision: str) -> Assertion[ConfigRollbackUndo]:
    def assertion(descriptor: ConfigRollbackUndo) -> bool:
        actual = (descriptor.was_on_history_id, descriptor.was_on_revision)

        if actual != (entry, revision):
            raise AssertionError(
                f"Expected the descriptor to record entry [{entry}] at "
                f"[{revision}], and it recorded {actual}."
            )

        return True

    return assertion


def _the_descriptor_records_sync_was(syncing: bool) -> Assertion[ConfigRollbackUndo]:
    def assertion(descriptor: ConfigRollbackUndo) -> bool:
        if descriptor.was_syncing_itself is not syncing:
            raise AssertionError(
                f"Expected the descriptor to record reconciliation as "
                f"[{syncing}], and it recorded [{descriptor.was_syncing_itself}]."
            )

        return True

    return assertion


def _it_reports_restored(revision: bool,
                         automated_sync: bool) -> Assertion[ConfigurationRestored]:
    def assertion(restored: ConfigurationRestored) -> bool:
        if (restored.revision, restored.automated_sync) != (revision, automated_sync):
            raise AssertionError(
                f"Expected a restore reporting revision={revision} "
                f"automated_sync={automated_sync}, and it reported "
                f"revision={restored.revision} "
                f"automated_sync={restored.automated_sync}."
            )

        return True

    return assertion
