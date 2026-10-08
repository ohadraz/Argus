"""Rolling a deployment back through the platform's own rollback.

What is worth pinning is the order and the refusals, because both are the
platform's rules rather than this module's preferences. A platform refuses a
rollback while it is reconciling the application itself, so suspending that is
part of performing one - and an application with no earlier entry has nothing to
roll back to, which has to be found out before anything is touched.

The descriptor is the other half. Only this module ever knows which entry was
running or whether reconciliation was on, so a withdrawal hours later can put
back exactly as much as this records and no more.

How each of those is asked of Argo CD - the routes, the merge patch, the rollback
body - is the adapter's, and pinned in its own suite. This one stands the
platform in at its port.
"""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import create_autospec

import pytest
from argus_core.mcp_transport import (
    LEFT_BEHIND_MARKER,
    UNREACHABLE_PLATFORM_MARKER,
    what_was_left_behind,
)
from argus_core.models import DeploymentRestored, DeploymentRollbackUndo
from argus_testkit import (
    Assertion,
    Scenario,
    all_of,
    an_error_was_raised,
    attempting,
    calling,
    one_record_was_logged,
)
from deployment_platform import (
    DeploymentPlatformWrites,
    DeploymentRecord,
    PlatformRefused,
    PlatformUnreachable,
)
from write_mcp_server.rolling_back import (
    NoEarlierRevision,
    RollbackRefused,
    restore_deployment,
    roll_back_deployment,
)

SOME_APPLICATION = "io-shop"

THE_ENTRY_RUNNING = 2
THE_ENTRY_BEFORE_IT = 1
THE_REVISION_RUNNING = "0d8e826225f0de73958a8a8dd3d867b2ae249e72"
THE_REVISION_BEFORE_IT = "544cef36a8eaf45c5b030c3d5c21473d8176cef3"


def _a_deployment(history_id: int, revision: str) -> DeploymentRecord:
    return DeploymentRecord(
        history_id=history_id,
        revision=revision,
        deployed_at="2026-10-07T09:00:00Z",
        repo_url=None,
        path=None,
        initiated_by=None
    )


def _two_deployments() -> list[DeploymentRecord]:
    """In the order the platform serves them: the one running is last."""
    return [
        _a_deployment(THE_ENTRY_BEFORE_IT, THE_REVISION_BEFORE_IT),
        _a_deployment(THE_ENTRY_RUNNING, THE_REVISION_RUNNING)
    ]


def a_platform(history: list[DeploymentRecord] | None = None,
               syncing_itself: bool = True) -> Any:
    platform = create_autospec(DeploymentPlatformWrites, instance=True)
    platform.deployments_of.return_value = (
        history if history is not None else _two_deployments()
    )
    platform.is_syncing_itself.return_value = syncing_itself

    return platform


def _rolling_back(platform: Any) -> DeploymentRollbackUndo:
    return roll_back_deployment(SOME_APPLICATION, platform)


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
    platform = a_platform(syncing_itself=True)

    Scenario() \
        .given(platform) \
        .when(lambda: _rolling_back(platform)) \
        .then(all_of(
            _it_was_asked_in_order(platform, "suspend_sync", "roll_back"),
            _it_rolled_back_to(platform, THE_ENTRY_BEFORE_IT)
        ))


@pytest.mark.unit
def test_an_application_nobody_was_reconciling_is_left_alone() -> None:
    # Suspending it would change nothing, and an undo that later turned it on
    # would start something Argus did not stop.
    platform = a_platform(syncing_itself=False)

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
    only_ever_deployed_once = [_a_deployment(THE_ENTRY_RUNNING, THE_REVISION_RUNNING)]
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
    platform.roll_back.side_effect = PlatformUnreachable("no route to host")

    Scenario() \
        .given(platform) \
        .when(attempting(lambda: _rolling_back(platform))) \
        .then(an_error_was_raised(RollbackRefused))


@pytest.mark.unit
def test_restoring_puts_back_the_entry_that_was_running() -> None:
    platform = a_platform()

    Scenario() \
        .given(descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: restore_deployment(descriptor, platform)) \
        .then(all_of(
            _it_rolled_back_to(platform, THE_ENTRY_RUNNING),
            _it_reports_restored(revision=True, automated_sync=True)
        ))


@pytest.mark.unit
def test_restoring_turns_reconciliation_back_on_after_the_revision() -> None:
    # In the order the platform allows: automated sync refuses a rollback, so
    # re-enabling it first would make the second step impossible.
    platform = a_platform()

    Scenario() \
        .given(descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: restore_deployment(descriptor, platform)) \
        .then(_it_was_asked_in_order(platform, "roll_back", "resume_sync"))


@pytest.mark.unit
def test_restoring_leaves_reconciliation_off_where_argus_found_it_off() -> None:
    # Turning it on because that is the usual arrangement would be Argus
    # starting something it did not stop.
    platform = a_platform()

    Scenario() \
        .given(descriptor := _a_descriptor(was_syncing_itself=False)) \
        .when(lambda: restore_deployment(descriptor, platform)) \
        .then(all_of(
            _the_sync_policy_was_not_touched(platform),
            _it_reports_restored(revision=True, automated_sync=True)
        ))


@pytest.mark.unit
def test_a_restore_that_only_managed_the_revision_says_so() -> None:
    # The half that is easy to lose. The deployment looks right and is
    # receiving nothing anybody ships to it.
    platform = a_platform()
    platform.resume_sync.side_effect = PlatformUnreachable("no route to host")

    Scenario() \
        .given(descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: restore_deployment(descriptor, platform)) \
        .then(_it_reports_restored(revision=True, automated_sync=False))


@pytest.mark.unit
def test_a_restore_that_could_not_reach_the_platform_at_all_says_so() -> None:
    platform = a_platform()
    platform.roll_back.side_effect = PlatformUnreachable("no route to host")
    platform.resume_sync.side_effect = PlatformUnreachable("no route to host")

    Scenario() \
        .given(descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: restore_deployment(descriptor, platform)) \
        .then(_it_reports_restored(revision=False, automated_sync=False))


@pytest.mark.unit
def test_a_platform_that_never_answered_the_read_is_reported_as_unreachable() -> None:
    # Nothing has been touched when this fails, which is what makes the report
    # honest: the walk is told that four actions are unavailable and told
    # nothing about a state somebody has to put back.
    platform = a_platform()
    platform.deployments_of.side_effect = PlatformUnreachable("no route to host")

    Scenario() \
        .given(platform) \
        .when(attempting(lambda: _rolling_back(platform))) \
        .then(_it_is_reported_as_an_unreachable_platform())


@pytest.mark.unit
def test_a_platform_unavailable_when_sync_is_suspended_is_reported_as_unreachable() -> None:
    # The suspension is the first thing a rollback changes, so a platform that
    # refuses it has left the estate exactly as it found it.
    platform = a_platform()
    platform.suspend_sync.side_effect = PlatformUnreachable("503")

    Scenario() \
        .given(platform) \
        .when(attempting(lambda: _rolling_back(platform))) \
        .then(_it_is_reported_as_an_unreachable_platform())


@pytest.mark.unit
def test_a_platform_that_died_before_a_rollback_that_changed_nothing_is_unreachable() -> None:
    # An application nobody was reconciling needs no suspension, so the rollback
    # request is the first write - and a platform that stopped answering before
    # it took nothing with it.
    platform = a_platform(syncing_itself=False)
    platform.roll_back.side_effect = PlatformUnreachable("no route to host")

    Scenario() \
        .given(platform) \
        .when(attempting(lambda: _rolling_back(platform))) \
        .then(_it_is_reported_as_an_unreachable_platform())


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
    platform = a_platform(syncing_itself=True)
    platform.roll_back.side_effect = PlatformUnreachable("no route to host")

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
    platform = a_platform(syncing_itself=False)
    platform.roll_back.side_effect = PlatformRefused("400")

    Scenario() \
        .given(platform) \
        .when(attempting(lambda: _rolling_back(platform))) \
        .then(_it_is_not_reported_as_an_unreachable_platform())


@pytest.mark.unit
def test_a_rollback_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    # A change to production, and what it changed.
    platform = a_platform()

    Scenario() \
        .given(
            calling(lambda: caplog.set_level(logging.INFO)),
            platform
        ) \
        .when(lambda: _rolling_back(platform)) \
        .then(
            one_record_was_logged(caplog, "write_mcp_server.rolling_back", logging.INFO,
                                  "deployment rolled back",
                                  values={"application": SOME_APPLICATION,
                                          "to_history_id": THE_ENTRY_BEFORE_IT})
        )


@pytest.mark.unit
def test_a_rollback_refused_after_sync_was_suspended_is_logged_as_a_warning(
    caplog: pytest.LogCaptureFixture
) -> None:
    # The refusal leaves reconciliation off on purpose, and the line says so:
    # an application nobody is reconciling looks healthy until the next deploy
    # quietly does not arrive.
    platform = a_platform(syncing_itself=True)
    platform.roll_back.side_effect = PlatformRefused("400")

    Scenario() \
        .given(platform) \
        .when(attempting(lambda: _rolling_back(platform))) \
        .then(
            one_record_was_logged(caplog, "write_mcp_server.rolling_back", logging.WARNING,
                                  "rollback refused",
                                  values={"application": SOME_APPLICATION,
                                          "sync_suspended": True})
        )


@pytest.mark.unit
def test_a_complete_restore_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    # A change to production as much as the action was.
    platform = a_platform()

    Scenario() \
        .given(
            calling(lambda: caplog.set_level(logging.INFO)),
            descriptor := _a_descriptor(was_syncing_itself=True)
        ) \
        .when(lambda: restore_deployment(descriptor, platform)) \
        .then(
            one_record_was_logged(caplog, "write_mcp_server.rolling_back", logging.INFO,
                                  "deployment restored",
                                  values={"application": SOME_APPLICATION})
        )


@pytest.mark.unit
def test_a_restore_that_only_managed_the_revision_is_logged_as_a_warning(
    caplog: pytest.LogCaptureFixture
) -> None:
    # The quiet half. The application looks put back and is receiving nothing
    # anybody ships to it, and no other line would say so.
    platform = a_platform()
    platform.resume_sync.side_effect = PlatformUnreachable("no route to host")

    Scenario() \
        .given(descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: restore_deployment(descriptor, platform)) \
        .then(
            one_record_was_logged(caplog, "write_mcp_server.rolling_back", logging.WARNING,
                                  "deployment not fully restored",
                                  values={"application": SOME_APPLICATION,
                                          "revision_put_back": True,
                                          "automated_sync_put_back": False})
        )


@pytest.mark.unit
def test_a_restore_step_that_failed_is_logged_as_an_error(
    caplog: pytest.LogCaptureFixture
) -> None:
    # The restore reports which half it lost, never why. The why is here, and
    # it is what a person putting the other half back by hand needs first.
    platform = a_platform()
    platform.resume_sync.side_effect = PlatformUnreachable("no route to host")

    Scenario() \
        .given(descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: restore_deployment(descriptor, platform)) \
        .then(
            one_record_was_logged(caplog, "write_mcp_server.rolling_back", logging.ERROR,
                                  "restore step failed",
                                  values={"application": SOME_APPLICATION,
                                          "step": "automated sync"},
                                  failure=PlatformUnreachable)
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


def _it_rolled_back_to(platform: Any, entry: int) -> Assertion[object]:
    def assertion(dont_care: object) -> bool:
        asked = [call.args for call in platform.roll_back.call_args_list]

        if asked != [(SOME_APPLICATION, entry)]:
            raise AssertionError(
                f"Expected one rollback of [{SOME_APPLICATION}] to history entry "
                f"[{entry}], and the platform was asked {asked}."
            )

        return True

    return assertion


def _it_was_asked_in_order(platform: Any, *expected: str) -> Assertion[object]:
    """The named operations happened, and in this order relative to each other."""
    def assertion(dont_care: object) -> bool:
        asked = [name for name, _args, _kwargs in platform.method_calls]
        relevant = [name for name in asked if name in expected]

        if relevant != list(expected):
            raise AssertionError(
                f"Expected {list(expected)} in that order, and the platform was "
                f"asked {asked}."
            )

        return True

    return assertion


def _the_sync_policy_was_not_touched(platform: Any) -> Assertion[object]:
    def assertion(dont_care: object) -> bool:
        if platform.suspend_sync.called or platform.resume_sync.called:
            raise AssertionError(
                f"Expected the sync policy to be left alone, and the platform was "
                f"asked {platform.method_calls}."
            )

        return True

    return assertion


def _nothing_was_changed(platform: Any) -> Assertion[Exception | None]:
    def assertion(dont_care: Exception | None) -> bool:
        if platform.suspend_sync.called or platform.roll_back.called:
            raise AssertionError(
                f"Expected nothing to be changed, and the platform was asked "
                f"{platform.method_calls}."
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
