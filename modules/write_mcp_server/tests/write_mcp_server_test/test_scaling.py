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

And a withdrawal puts back only what is still Argus's. A count that is still the
one Argus asked for is put back; one already back where Argus found it needs no
write; any other is somebody's since, and is left as they set it - with the
reconciliation Argus suspended left suspended where it still is, since resuming
it would have the platform re-apply git over them. Where an autoscaler owns the
count, the count is the controller's and nobody's to put back: only the sync is.

How the count is read and written on Argo CD - the manifest, the merge patch the
count and the mark travel in - is the adapter's, and pinned in its own suite.
"""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import create_autospec

import pytest
from argus_testkit import (
    Assertion,
    Scenario,
    all_of,
    an_error_was_raised,
    attempting,
    calling,
    one_record_was_logged,
)
from core.mcp_transport import (
    EXHAUSTED_ACTION_MARKER,
    LEFT_BEHIND_MARKER,
    UNREACHABLE_PLATFORM_MARKER,
    what_was_left_behind,
)
from core.models import CapacityRestored, ReplicaUndo, RolloutProgress
from deployment_platform import (
    Autoscaler,
    DeploymentPlatformWrites,
    PlatformRefused,
    PlatformUnreachable,
)
from write_mcp_server.scaling import (
    THE_MOST_REPLICAS_ARGUS_MAY_ASK_FOR,
    AlreadyAtItsLargest,
    ScaleRefused,
    restore_replica_count,
    scale_out,
)

from write_mcp_server_test.framework.marks import a_mark, every_write_carried
from write_mcp_server_test.framework.putting_back import (
    it_was_left_because,
    it_was_not_left_alone,
    the_suspension_is_said_to_stand,
)
from write_mcp_server_test.framework.refusals import (
    it_is_marked_unreachable,
    it_left_behind,
    it_was_refused_as,
    what_it_left_is_known,
)

SOME_APPLICATION = "io-shop"
# What every scale-out and restore here is made under. One for the file: which
# action a write is for is the caller's, and what is asserted is only that the
# writes carry it.
SOME_MARK = a_mark()

# What the deployment is running when anybody looks, and what one doubling of it
# comes to. Three is the size the fixture's own values file asks for.
THE_COUNT_RUNNING = 3
TWICE_THAT = 6
# A count somebody set since, which is neither of the two above.
A_COUNT_SOMEBODY_SET = TWICE_THAT - 1

# An autoscaler the platform names for the application, where one owns the count.
SOME_AUTOSCALER = Autoscaler(name="io-shop-cpu", namespace="shopping")

# What a scale-out leaves where it suspended the sync and the count never moved.
THE_SUSPENSION = ReplicaUndo(
    application=SOME_APPLICATION,
    was_replicas=THE_COUNT_RUNNING,
    replicas_asked_for=TWICE_THAT,
    was_syncing_itself=True
)


def _running(replicas: int) -> RolloutProgress:
    """A Deployment asked for `replicas`, with every one of them serving."""
    return RolloutProgress(
        replicas_wanted=replicas,
        replicas_serving=replicas,
        replicas_updated=replicas,
        is_paused=False,
        has_failed=False
    )


def a_platform(replicas: int = THE_COUNT_RUNNING,
               reconciling_itself: bool = True,
               autoscaler: Autoscaler | None = None) -> Any:
    platform = create_autospec(DeploymentPlatformWrites, instance=True)
    platform.rollout_of.return_value = _running(replicas)
    platform.is_syncing_itself.return_value = reconciling_itself
    platform.autoscaler_of.return_value = autoscaler

    return platform


def a_platform_as_the_scale_out_left_it(replicas: int = TWICE_THAT,
                                        reconciling_itself: bool = False,
                                        autoscaler: Autoscaler | None = None) -> Any:
    """A platform a scale-out of Argus's has been through: running the count it
    asked for unless a case names another, and not syncing itself, because the
    scale-out suspended that, unless a case says somebody turned it back on."""
    return a_platform(replicas=replicas, reconciling_itself=reconciling_itself,
                      autoscaler=autoscaler)


def _scaling_out(platform: Any) -> ReplicaUndo:
    return scale_out(SOME_APPLICATION, platform, SOME_MARK)


def _restoring(descriptor: ReplicaUndo, platform: Any) -> CapacityRestored:
    return restore_replica_count(descriptor, platform, SOME_MARK)


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
def test_reconciliation_is_suspended_before_the_count_is_changed() -> None:
    # The platform's rule rather than a preference: a reconciling application has
    # its live replica count set back to whatever the repository holds at the next
    # sync, so a scale-out taken under automated sync is a mitigation with a timer
    # on it.
    platform = a_platform(reconciling_itself=True)

    Scenario() \
        .given(platform) \
        .when(lambda: _scaling_out(platform)) \
        .then(_it_was_asked_in_order(platform, "suspend_sync", "scale"))


@pytest.mark.unit
def test_every_write_a_scale_out_makes_carries_its_actions_mark() -> None:
    # The suspension and the count alike: either left on the platform unmarked
    # is a change nobody can tell from a person's.
    platform = a_platform(reconciling_itself=True)

    Scenario() \
        .given(platform) \
        .when(lambda: _scaling_out(platform)) \
        .then(all_of(
            every_write_carried(platform, "suspend_sync", SOME_MARK),
            every_write_carried(platform, "scale", SOME_MARK)
        ))


@pytest.mark.unit
def test_every_write_a_restore_makes_carries_its_mark() -> None:
    platform = a_platform_as_the_scale_out_left_it()

    Scenario() \
        .given(a_descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: _restoring(a_descriptor, platform)) \
        .then(all_of(
            every_write_carried(platform, "scale", SOME_MARK),
            every_write_carried(platform, "resume_sync", SOME_MARK)
        ))


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
def test_the_descriptor_records_the_count_it_asked_for() -> None:
    # What a withdrawal compares the live count with to find out whether the
    # scale-out is still Argus's.
    platform = a_platform(replicas=THE_COUNT_RUNNING)

    Scenario() \
        .given(platform) \
        .when(lambda: _scaling_out(platform)) \
        .then(_the_descriptor_records_it_asked_for(TWICE_THAT))


@pytest.mark.unit
def test_the_count_recorded_as_asked_for_is_the_ceiling_where_doubling_passed_it() -> None:
    # The count actually asked for, not twice what was running: a withdrawal
    # comparing the live count with the doubling would call Argus's own
    # scale-out somebody else's.
    just_under = THE_MOST_REPLICAS_ARGUS_MAY_ASK_FOR - 1
    platform = a_platform(replicas=just_under)

    Scenario() \
        .given(platform) \
        .when(lambda: _scaling_out(platform)) \
        .then(_the_descriptor_records_it_asked_for(THE_MOST_REPLICAS_ARGUS_MAY_ASK_FOR))


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
    platform.rollout_of.side_effect = PlatformUnreachable("no route to the platform")

    Scenario() \
        .given(platform) \
        .when(attempting(lambda: _scaling_out(platform))) \
        .then(all_of(
            an_error_was_raised(ScaleRefused),
            _nothing_was_changed(platform)
        ))


@pytest.mark.unit
def test_a_count_the_platform_could_not_say_is_refused() -> None:
    # A Deployment with no count in its manifest is one this cannot double, and a
    # guess of one would halve a shop serving three.
    platform = a_platform()
    platform.rollout_of.side_effect = PlatformRefused("the manifest has no replicas")

    Scenario() \
        .given(platform) \
        .when(attempting(lambda: _scaling_out(platform))) \
        .then(all_of(
            an_error_was_raised(ScaleRefused),
            _nothing_was_changed(platform)
        ))


@pytest.mark.unit
def test_restoring_puts_back_the_count_that_was_running() -> None:
    platform = a_platform_as_the_scale_out_left_it()

    Scenario() \
        .given(a_descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: _restoring(a_descriptor, platform)) \
        .then(all_of(
            _it_asked_for(platform, replicas=THE_COUNT_RUNNING),
            _it_reports_restored(count=True, automated_sync=True)
        ))


@pytest.mark.unit
def test_restoring_turns_reconciliation_back_on_after_the_count() -> None:
    # Re-enabling sync first would have the platform set the count back on its
    # own - to the same number, and unverifiably, at a moment nothing here chose.
    platform = a_platform_as_the_scale_out_left_it()

    Scenario() \
        .given(a_descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: _restoring(a_descriptor, platform)) \
        .then(_it_was_asked_in_order(platform, "scale", "resume_sync"))


@pytest.mark.unit
def test_restoring_leaves_reconciliation_off_where_argus_found_it_off() -> None:
    platform = a_platform_as_the_scale_out_left_it()

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
    platform = a_platform_as_the_scale_out_left_it()
    platform.resume_sync.side_effect = PlatformUnreachable("no route to the platform")

    Scenario() \
        .given(a_descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: _restoring(a_descriptor, platform)) \
        .then(_it_reports_restored(count=True, automated_sync=False))


@pytest.mark.unit
def test_a_restore_that_could_not_reach_the_platform_at_all_says_so() -> None:
    platform = a_platform_as_the_scale_out_left_it()
    platform.scale.side_effect = PlatformUnreachable("no route to the platform")
    platform.resume_sync.side_effect = PlatformUnreachable("no route to the platform")

    Scenario() \
        .given(a_descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: _restoring(a_descriptor, platform)) \
        .then(_it_reports_restored(count=False, automated_sync=False))


@pytest.mark.unit
def test_a_count_still_argus_s_is_put_back_and_said_to_be_nobody_else_s() -> None:
    # The deployment runs the count Argus asked for, so nobody has resized it.
    platform = a_platform_as_the_scale_out_left_it(replicas=TWICE_THAT)

    Scenario() \
        .given(a_descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: _restoring(a_descriptor, platform)) \
        .then(all_of(
            _it_asked_for(platform, replicas=THE_COUNT_RUNNING),
            _it_reports_restored(count=True, automated_sync=True),
            it_was_not_left_alone()
        ))


@pytest.mark.unit
def test_a_count_already_back_where_argus_found_it_is_not_written_again() -> None:
    # Somebody - anybody - has already set it back. Nothing is written for the
    # count, and it counts as put back; the sync Argus suspended is still
    # Argus's to resume.
    platform = a_platform_as_the_scale_out_left_it(replicas=THE_COUNT_RUNNING)

    Scenario() \
        .given(a_descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: _restoring(a_descriptor, platform)) \
        .then(all_of(
            _the_count_was_not_written(platform),
            every_write_carried(platform, "resume_sync", SOME_MARK),
            _it_reports_restored(count=True, automated_sync=True),
            it_was_not_left_alone()
        ))


@pytest.mark.unit
def test_a_count_somebody_set_since_is_left_as_they_set_it() -> None:
    # Setting it back would replace their decision with a number nobody now
    # wants, and resuming sync would have the platform re-apply git over it - so
    # neither is written, and what was found is said.
    platform = a_platform_as_the_scale_out_left_it(replicas=A_COUNT_SOMEBODY_SET)

    Scenario() \
        .given(a_descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: _restoring(a_descriptor, platform)) \
        .then(all_of(
            _nothing_was_written(platform),
            it_was_left_because(f"[{A_COUNT_SOMEBODY_SET}]")
        ))


@pytest.mark.unit
@pytest.mark.parametrize(
    ("was_syncing_itself", "syncing_now", "still_suspended"),
    [
        pytest.param(True, False, True, id="argus-suspended-it-and-it-is-still-off"),
        pytest.param(True, True, False, id="somebody-turned-it-back-on"),
        pytest.param(False, False, False, id="it-was-off-before-argus-came")
    ]
)
def test_a_count_left_as_somebody_set_it_says_whether_argus_s_suspension_still_stands(
    was_syncing_itself: bool, syncing_now: bool, still_suspended: bool
) -> None:
    # Read from the platform, because only it knows: a person who reverted in
    # git and turned sync back on has ended Argus's suspension themselves, and
    # one sync was off for before Argus came was never suspended by Argus.
    platform = a_platform_as_the_scale_out_left_it(replicas=A_COUNT_SOMEBODY_SET,
                                                   reconciling_itself=syncing_now)

    Scenario() \
        .given(a_descriptor := _a_descriptor(was_syncing_itself=was_syncing_itself)) \
        .when(lambda: _restoring(a_descriptor, platform)) \
        .then(all_of(
            _nothing_was_written(platform),
            the_suspension_is_said_to_stand(still_suspended)
        ))


@pytest.mark.unit
def test_a_count_an_autoscaler_owns_is_left_to_it_and_the_sync_is_put_back() -> None:
    # Whatever the count reads, it is the controller's: a figure written here
    # would be re-derived within a sync period, and a count matching neither of
    # Argus's is the autoscaler moving rather than a person deciding. So the
    # count is left to it, and the reconciliation Argus suspended is resumed.
    platform = a_platform_as_the_scale_out_left_it(replicas=A_COUNT_SOMEBODY_SET,
                                                   autoscaler=SOME_AUTOSCALER)

    Scenario() \
        .given(a_descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: _restoring(a_descriptor, platform)) \
        .then(all_of(
            _the_count_was_not_written(platform),
            every_write_carried(platform, "resume_sync", SOME_MARK),
            _the_count_is_said_left_to_its_autoscaler(),
            it_was_not_left_alone()
        ))


@pytest.mark.unit
def test_a_count_an_autoscaler_owns_leaves_reconciliation_off_where_argus_found_it_off() -> None:
    platform = a_platform_as_the_scale_out_left_it(autoscaler=SOME_AUTOSCALER)

    Scenario() \
        .given(a_descriptor := _a_descriptor(was_syncing_itself=False)) \
        .when(lambda: _restoring(a_descriptor, platform)) \
        .then(all_of(
            _the_count_was_not_written(platform),
            _the_sync_policy_was_not_touched(platform),
            _the_count_is_said_left_to_its_autoscaler()
        ))


@pytest.mark.unit
@pytest.mark.parametrize("read", ["autoscaler_of", "rollout_of"])
def test_a_restore_that_could_not_read_whose_the_count_is_writes_nothing(read: str) -> None:
    # Writing on a reading that never came back is the blind put-back the check
    # exists to prevent - so neither half is written, neither is said to be
    # back, and nothing is said to have been found.
    platform = a_platform_as_the_scale_out_left_it()
    getattr(platform, read).side_effect = PlatformUnreachable("no route to host")

    Scenario() \
        .given(a_descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: _restoring(a_descriptor, platform)) \
        .then(all_of(
            _nothing_was_written(platform),
            _it_reports_restored(count=False, automated_sync=False),
            it_was_not_left_alone()
        ))


@pytest.mark.unit
def test_a_restore_that_could_not_read_whether_sync_is_back_on_writes_nothing() -> None:
    # The last read, made only where the count is somebody's: without it nobody
    # can say whether Argus's suspension still stands, and the answer says
    # nothing it could not establish.
    platform = a_platform_as_the_scale_out_left_it(replicas=A_COUNT_SOMEBODY_SET)
    platform.is_syncing_itself.side_effect = PlatformRefused("403")

    Scenario() \
        .given(a_descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: _restoring(a_descriptor, platform)) \
        .then(all_of(
            _nothing_was_written(platform),
            _it_reports_restored(count=False, automated_sync=False),
            it_was_not_left_alone()
        ))


@pytest.mark.unit
def test_a_scale_out_recorded_without_the_count_it_asked_for_is_not_written_over() -> None:
    # A row written before the descriptor said what Argus asked for. Whether
    # the live count is still Argus's cannot be asked without it, so the restore
    # answers as a read that never came back does: nothing written, neither
    # half back, nothing found.
    from_before = _a_descriptor(was_syncing_itself=True).model_copy(
        update={"replicas_asked_for": None}
    )
    platform = a_platform_as_the_scale_out_left_it()

    Scenario() \
        .given(from_before) \
        .when(lambda: _restoring(from_before, platform)) \
        .then(all_of(
            _nothing_was_written(platform),
            _it_reports_restored(count=False, automated_sync=False),
            it_was_not_left_alone()
        ))


@pytest.mark.unit
def test_a_deployment_at_the_ceiling_refuses_in_a_way_a_caller_can_recognise() -> None:
    # The refusal that is an answer, and the walk acts on the difference: an
    # estate already as large as Argus may make it has not failed, so the next
    # explanation gets tried instead of a human getting woken. A caller that had
    # to read the words of the sentence to tell that would classify it differently
    # the day somebody rephrased it, so the marker crosses the wire.
    platform = a_platform(replicas=THE_MOST_REPLICAS_ARGUS_MAY_ASK_FOR)

    Scenario() \
        .given(platform) \
        .when(attempting(lambda: _scaling_out(platform))) \
        .then(_the_refusal_says_the_action_is_exhausted())


@pytest.mark.unit
def test_a_platform_that_never_answered_the_read_is_reported_as_unreachable() -> None:
    # Nothing has been touched when this fails. The walk is told four actions
    # are unavailable and told nothing about a state somebody has to put back,
    # which is exactly what is true.
    platform = a_platform()
    platform.rollout_of.side_effect = PlatformUnreachable("no route to host")

    Scenario() \
        .given(platform) \
        .when(attempting(lambda: _scaling_out(platform))) \
        .then(_it_is_reported_as_an_unreachable_platform())


@pytest.mark.unit
def test_a_platform_unavailable_when_sync_is_suspended_is_reported_as_unreachable() -> None:
    # The suspension is the first thing a scale-out changes, so a platform that
    # said it did not handle it has left the estate as it found it.
    platform = a_platform()
    platform.suspend_sync.side_effect = PlatformUnreachable("503", known_not_applied=True)

    Scenario() \
        .given(platform) \
        .when(attempting(lambda: _scaling_out(platform))) \
        .then(_it_is_reported_as_an_unreachable_platform())


@pytest.mark.unit
def test_a_platform_that_died_before_a_scale_out_that_changed_nothing_is_unreachable() -> None:
    # A deployment nobody was reconciling needs no suspension, so the action is
    # the first write - and a platform that stopped answering before it took
    # nothing with it.
    platform = a_platform(reconciling_itself=False)
    platform.scale.side_effect = PlatformUnreachable(
        "no route to host", known_not_applied=True
    )

    Scenario() \
        .given(platform) \
        .when(attempting(lambda: _scaling_out(platform))) \
        .then(_it_is_reported_as_an_unreachable_platform())


@pytest.mark.unit
def test_a_scale_out_that_left_sync_suspended_says_so_and_still_reports_the_platform() -> None:
    # The rollback's case, for the second of the three actions that suspend
    # reconciliation before they act. The platform is gone and the count never
    # moved, so what is left behind is the suspension alone - and it travels on
    # the failure, so the walk can narrow itself and still know an application is
    # sitting un-reconciled.
    platform = a_platform(reconciling_itself=True)
    platform.scale.side_effect = PlatformUnreachable(
        "no route to host", known_not_applied=True
    )

    Scenario() \
        .given(platform) \
        .when(attempting(lambda: _scaling_out(platform))) \
        .then(all_of(
            _it_is_reported_as_an_unreachable_platform(),
            _it_says_what_it_left_behind(THE_SUSPENSION)
        ))


@pytest.mark.unit
def test_a_count_the_platform_would_not_give_is_known_to_have_changed_nothing() -> None:
    # Nothing had been asked to change, so however the read failed, nothing did.
    platform = a_platform()
    platform.rollout_of.side_effect = PlatformRefused("the manifest has no replicas")

    Scenario() \
        .given(platform) \
        .when(attempting(lambda: _scaling_out(platform))) \
        .then(all_of(
            it_was_refused_as(ScaleRefused),
            it_is_marked_unreachable(False),
            what_it_left_is_known(True),
            it_left_behind(None)
        ))


@pytest.mark.unit
def test_asking_whether_it_syncs_itself_is_a_read_and_changes_nothing() -> None:
    platform = a_platform()
    platform.is_syncing_itself.side_effect = PlatformUnreachable(
        "timed out", known_not_applied=False
    )

    Scenario() \
        .given(platform) \
        .when(attempting(lambda: _scaling_out(platform))) \
        .then(all_of(
            it_is_marked_unreachable(True),
            what_it_left_is_known(True),
            it_left_behind(None)
        ))


@pytest.mark.unit
def test_a_suspension_whose_answer_was_lost_is_not_said_to_have_changed_nothing() -> None:
    platform = a_platform()
    platform.suspend_sync.side_effect = PlatformUnreachable(
        "timed out", known_not_applied=False
    )

    Scenario() \
        .given(platform) \
        .when(attempting(lambda: _scaling_out(platform))) \
        .then(all_of(
            it_was_refused_as(ScaleRefused),
            it_is_marked_unreachable(False),
            what_it_left_is_known(False),
            it_left_behind(None)
        ))


@pytest.mark.unit
def test_a_scale_out_rejected_after_sync_was_suspended_says_the_suspension_is_left() -> None:
    # A platform that answered the scale with a no, after the suspension
    # landed: the suspension is the whole of what is left, and it is said.
    platform = a_platform(reconciling_itself=True)
    platform.scale.side_effect = PlatformRefused("400", known_not_applied=True)

    Scenario() \
        .given(platform) \
        .when(attempting(lambda: _scaling_out(platform))) \
        .then(all_of(
            it_is_marked_unreachable(False),
            what_it_left_is_known(True),
            it_left_behind(THE_SUSPENSION)
        ))


@pytest.mark.unit
def test_a_scale_out_whose_answer_was_lost_carries_the_suspension_and_no_more() -> None:
    # The count may be doubling this second. The suspension is carried, and
    # nothing is said to be all of it.
    platform = a_platform(reconciling_itself=True)
    platform.scale.side_effect = PlatformUnreachable("timed out", known_not_applied=False)

    Scenario() \
        .given(platform) \
        .when(attempting(lambda: _scaling_out(platform))) \
        .then(all_of(
            it_is_marked_unreachable(False),
            what_it_left_is_known(False),
            it_left_behind(THE_SUSPENSION)
        ))


@pytest.mark.unit
def test_a_platform_that_answered_and_refused_is_not_reported_as_unreachable() -> None:
    # Reachable, and this action is what it would not do. The pin and the
    # restart are still worth reaching for, and what a person has to look at is
    # the refusal rather than the platform.
    platform = a_platform(reconciling_itself=False)
    platform.scale.side_effect = PlatformRefused("400")

    Scenario() \
        .given(platform) \
        .when(attempting(lambda: _scaling_out(platform))) \
        .then(_it_is_not_reported_as_an_unreachable_platform())


@pytest.mark.unit
def test_a_scale_out_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    # A change to production, and what it changed.
    platform = a_platform()

    Scenario() \
        .given(
            calling(lambda: caplog.set_level(logging.INFO)),
            platform
        ) \
        .when(lambda: _scaling_out(platform)) \
        .then(
            one_record_was_logged(caplog, "write_mcp_server.scaling", logging.INFO,
                                  "deployment scaled out",
                                  values={"application": SOME_APPLICATION,
                                          "from_replicas": THE_COUNT_RUNNING,
                                          "to_replicas": TWICE_THAT})
        )


@pytest.mark.unit
def test_a_scale_out_refused_after_sync_was_suspended_is_logged_as_a_warning(
    caplog: pytest.LogCaptureFixture
) -> None:
    # The refusal leaves reconciliation off on purpose, and the line says so:
    # an application nobody is reconciling looks healthy until the next deploy
    # quietly does not arrive.
    platform = a_platform(reconciling_itself=True)
    platform.scale.side_effect = PlatformRefused("400")

    Scenario() \
        .given(platform) \
        .when(attempting(lambda: _scaling_out(platform))) \
        .then(
            one_record_was_logged(caplog, "write_mcp_server.scaling", logging.WARNING,
                                  "scale-out refused",
                                  values={"application": SOME_APPLICATION,
                                          "sync_suspended": True})
        )


@pytest.mark.unit
def test_a_complete_restore_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    # A change to production as much as the action was.
    platform = a_platform_as_the_scale_out_left_it()

    Scenario() \
        .given(
            calling(lambda: caplog.set_level(logging.INFO)),
            descriptor := _a_descriptor(was_syncing_itself=True)
        ) \
        .when(lambda: _restoring(descriptor, platform)) \
        .then(
            one_record_was_logged(caplog, "write_mcp_server.scaling", logging.INFO,
                                  "replica count restored",
                                  values={"application": SOME_APPLICATION})
        )


@pytest.mark.unit
def test_a_restore_that_only_managed_the_count_is_logged_as_a_warning(
    caplog: pytest.LogCaptureFixture
) -> None:
    # The quiet half. The application looks put back and is receiving nothing
    # anybody ships to it, and no other line would say so.
    platform = a_platform_as_the_scale_out_left_it()
    platform.resume_sync.side_effect = PlatformUnreachable("no route to host")

    Scenario() \
        .given(descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: _restoring(descriptor, platform)) \
        .then(
            one_record_was_logged(caplog, "write_mcp_server.scaling", logging.WARNING,
                                  "replica count not fully restored",
                                  values={"application": SOME_APPLICATION,
                                          "count_put_back": True,
                                          "automated_sync_put_back": False})
        )


@pytest.mark.unit
def test_a_restore_step_that_failed_is_logged_as_an_error(
    caplog: pytest.LogCaptureFixture
) -> None:
    # The restore reports which half it lost, never why. The why is here, and
    # it is what a person putting the other half back by hand needs first.
    platform = a_platform_as_the_scale_out_left_it()
    platform.resume_sync.side_effect = PlatformUnreachable("no route to host")

    Scenario() \
        .given(descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: _restoring(descriptor, platform)) \
        .then(
            one_record_was_logged(caplog, "write_mcp_server.scaling", logging.ERROR,
                                  "restore step failed",
                                  values={"application": SOME_APPLICATION,
                                          "step": "automated sync"},
                                  failure=PlatformUnreachable)
        )


def _it_is_reported_as_an_unreachable_platform() -> Assertion[Exception | None]:
    def assertion(raised: Exception | None) -> bool:
        if not isinstance(raised, ScaleRefused):
            raise AssertionError(
                f"Expected the scale-out to be refused, and what was raised was "
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
        if not isinstance(raised, ScaleRefused):
            raise AssertionError(
                f"Expected the scale-out to be refused, and what was raised was "
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

    Asserted against the marker itself rather than against the sentence, because
    the sentence is allowed to change and the marker is not - and asserted here
    rather than only in the kernel's own suite, because this is the end that has
    to remember to apply it. The kernel proves a marked refusal arrives as
    `ActionExhausted`; this proves this refusal is marked.
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


def _a_descriptor(was_syncing_itself: bool) -> ReplicaUndo:
    return ReplicaUndo(
        application=SOME_APPLICATION,
        was_replicas=THE_COUNT_RUNNING,
        replicas_asked_for=TWICE_THAT,
        was_syncing_itself=was_syncing_itself
    )


def _the_descriptor_records_it_asked_for(replicas: int) -> Assertion[ReplicaUndo]:
    def assertion(descriptor: ReplicaUndo) -> bool:
        if descriptor.replicas_asked_for != replicas:
            raise AssertionError(
                f"Expected the descriptor to record [{replicas}] replicas as the count "
                f"asked for, and it records [{descriptor.replicas_asked_for}]."
            )

        return True

    return assertion


def _the_count_was_not_written(platform: Any) -> Assertion[CapacityRestored]:
    def assertion(dont_care_restored: CapacityRestored) -> bool:
        if platform.scale.called:
            raise AssertionError(
                f"Expected no count written, and the platform was asked "
                f"{platform.scale.call_args_list}."
            )

        return True

    return assertion


def _nothing_was_written(platform: Any) -> Assertion[CapacityRestored]:
    """Neither the count nor the sync policy - the reads are what a restore
    that left the deployment alone did ask."""
    def assertion(dont_care_restored: CapacityRestored) -> bool:
        written = [name for name, operation in (("the count", platform.scale),
                                                ("the sync policy", platform.resume_sync),
                                                ("the sync policy", platform.suspend_sync))
                   if operation.called]

        if written:
            raise AssertionError(
                f"Expected nothing written, and the restore wrote {written}: "
                f"{platform.method_calls}."
            )

        return True

    return assertion


def _the_count_is_said_left_to_its_autoscaler() -> Assertion[CapacityRestored]:
    def assertion(restored: CapacityRestored) -> bool:
        if not restored.count_left_to_its_autoscaler or not restored.automated_sync_put_back:
            raise AssertionError(
                f"Expected the count left to its autoscaler and the sync put back, "
                f"and the restore reported {restored!r}."
            )

        return True

    return assertion


def _it_asked_for(platform: Any, replicas: int) -> Assertion[object]:
    """One count asked for, of the application - the mark it carried is
    `every_write_carried`'s to say."""
    def assertion(dont_care_result: object) -> bool:
        asked = [call.args[:2] for call in platform.scale.call_args_list]

        if asked != [(SOME_APPLICATION, replicas)]:
            raise AssertionError(
                f"Expected the platform to be asked once for [{replicas}] "
                f"replicas of [{SOME_APPLICATION}], and it was asked {asked}."
            )

        return True

    return assertion


def _it_was_asked_in_order(platform: Any, *expected: str) -> Assertion[object]:
    """The named operations happened, and in this order relative to each other."""
    def assertion(dont_care_result: object) -> bool:
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
    def assertion(dont_care_result: object) -> bool:
        if platform.suspend_sync.called or platform.resume_sync.called:
            raise AssertionError(
                f"Expected the sync policy to be left as it was found, and the "
                f"platform was asked {platform.method_calls}."
            )

        return True

    return assertion


def _nothing_was_changed(platform: Any) -> Assertion[Exception | None]:
    def assertion(dont_care_error: Exception | None) -> bool:
        changed = [
            name for name, operation in (("the count", platform.scale),
                                         ("the sync policy", platform.suspend_sync))
            if operation.called
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


def _it_says_what_it_left_behind(expected: ReplicaUndo) -> Assertion[Exception | None]:
    """The refusal carries the descriptor, and carries the right one.

    `test_rolling_back.py`'s helper for the second of the three actions that
    suspend reconciliation before acting. Not lifted anywhere shared: the three
    compare different descriptor types, and one version would take the union and
    stop telling a scale-out's descriptor from a rollback's.
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
