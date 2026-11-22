"""Rolling a deployment back through the platform's own rollback.

Three acts, each with rules that are the platform's rather than this module's.

The plan reads and changes nothing. It finds the entry running and the entry to
return to, and whether the platform reconciles the application itself - and an
application with nothing earlier to return to is found out here, before
anything is touched. Which entry is "earlier" is worked out from the history
alone: every full sync the platform makes adds an entry, so runs of one revision
are one deployment, and a newest run that returns to a revision already in the
history is a rollback somebody - Argus or a person - has already made. Rolling
back from it would roll forward to the revision that was rolled away from.

The rollback is made from the plan and only where the platform still stands as
the plan found it, every comparison made before anything is written - and the
plan is first held to this tier's own rule, so one naming any entry but the one
the rule gives is refused plainly. Running the revision the plan found -
whatever the entry's number - with no named account's entry since, is written.
Running the revision the plan returns to, newest entry Argus's own and dated at
or after the plan was read, is this rollback already made, and answered as made
- at or after, because both times are whole seconds, and a rollback landing in
the plan's own second is still this one. So is a sync to that revision Argus
asked for and the platform has not finished, whose history entry does not exist
yet. Anything else is somebody's change since, and nothing is written: the
revision alone cannot say who put it there. The sync switch is held to the same
rule, where the only suspension that is not somebody's change is one carrying
this action's own mark - and the switch back on under that mark is somebody
resuming it. A refusal says what this action's marks show already landed: where
its suspension still stands, the plan travels on the refusal as what it left
behind. What a rollback answers with is the plan, undated: the platform's own
time for the write is not carried yet.

A withdrawal puts back only what is still Argus's. The newest entry in the
history has to be Argus's own rollback, by the account Argus signs in as, and the
images the Deployment runs have to be the ones the platform renders for the
revision Argus rolled back to - a `kubectl set image` leaves no history entry, and
the images are what it changes. Anything else is somebody's change since, and is
left as they set it, with the reconciliation Argus suspended left suspended where
it still is: resuming it would have the platform re-apply git over them.

How each of those is asked of Argo CD - the routes, the merge patch, the rollback
body - is the adapter's, and pinned in its own suite. This one stands the
platform in at its port.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
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
from core.models import DeploymentRestored, DeploymentRollbackUndo, Planned
from deployment_platform import (
    DeploymentPlatformWrites,
    DeploymentRecord,
    MarkedObject,
    PlatformRefused,
    PlatformUnreachable,
    RequestedSync,
    SyncOperations,
    SyncPhase,
    SyncRun,
)
from mcp_transport import (
    EXHAUSTED_ACTION_MARKER,
    LEFT_BEHIND_MARKER,
    UNREACHABLE_PLATFORM_MARKER,
    what_was_left_behind,
)
from write_mcp_server.rolling_back import (
    NoEarlierRevision,
    RollbackRefused,
    RollbackStanding,
    plan_rollback,
    restore_deployment,
    roll_back_deployment,
    still_argus_s,
    what_became_of_the_rollback,
    whether_it_was_made,
)

from write_mcp_server_test.framework.marks import (
    ANOTHER_CLAIM,
    THIS_CLAIM,
    a_mark,
    a_mark_found,
    every_write_carried,
)
from write_mcp_server_test.framework.putting_back import (
    it_was_left_because,
    it_was_not_left_alone,
    the_suspension_is_said_to_stand,
)
from write_mcp_server_test.framework.refusals import (
    it_is_marked_unreachable,
    it_left_behind,
    it_was_refused_as,
    it_was_refused_as_changed_since,
    its_change_is_said_performed,
    what_it_left_is_known,
)
from write_mcp_server_test.framework.resuming import (
    it_is_not_said_changed_since,
    it_is_still_argus_s,
    it_refused_as_the_write_does,
    it_was_changed_since,
    it_was_made,
    nobody_can_say,
    nothing_landed,
    what_was_found_does_not_say,
)

SOME_APPLICATION = "io-shop"
# What every rollback and restore here is made under. One for the file: which
# action a write is for is the caller's, and what is asserted is only that the
# writes carry it.
SOME_MARK = a_mark()
# What the platform says when it fails or refuses a call: whatever it says, the
# refusal here is decided by which call failed and how.
DONT_CARE_PLATFORM_WORDS = "the platform did not do it"

# The time the platform's own clock gives on the answer a plan reads - the
# plan's `since` - and a moment either side of it, which is all a history entry's
# time is ever compared for.
SOME_PLATFORM_TIME = datetime(2026, 11, 18, 13, 4, tzinfo=UTC)
BEFORE_THE_PLAN = SOME_PLATFORM_TIME - timedelta(hours=1)
AFTER_THE_PLAN = SOME_PLATFORM_TIME + timedelta(minutes=1)
# When the platform answered the rollback it was asked for, by its own clock.
THE_MOMENT_THE_PLATFORM_ANSWERED = AFTER_THE_PLAN + timedelta(seconds=2)
# When Argus's run of a rollback started, after the plan and before the entry
# the platform wrote once it finished.
A_RUN_STARTED_BEFORE_ITS_ENTRY = AFTER_THE_PLAN - timedelta(seconds=30)

THE_ENTRY_RUNNING = 2
THE_ENTRY_BEFORE_IT = 1
THE_REVISION_RUNNING = "0d8e826225f0de73958a8a8dd3d867b2ae249e72"
THE_REVISION_BEFORE_IT = "544cef36a8eaf45c5b030c3d5c21473d8176cef3"
# A revision deployed before both of the above, which no rollback here goes to.
AN_OLDER_REVISION = "3e1d9a7c5b2f4e6d8c0a1b3d5f7e9c2a4b6d8f0e"
# The entries the history gains after the two above, by position: whose each
# is, and of which revision, is the case's to say.
THE_NEXT_ENTRY = THE_ENTRY_RUNNING + 1
THE_ENTRY_AFTER_THAT = THE_NEXT_ENTRY + 1
A_REVISION_SOMEBODY_ELSE_DEPLOYED = "9b2c4e1f0a7d8c6b5e4f3a2d1c0b9a8f7e6d5c4b"

# The account Argus signs in to the platform as, which the platform writes on
# every history entry Argus's rollbacks add - and somebody who is not Argus.
SOME_ARGUS_ACCOUNT = "argus"
SOME_PERSON = "alice"
# The account setting left empty, as it is where the credential is shared.
NO_ACCOUNT = ""

# The one container the Deployment runs, and an image somebody built by hand
# and set with `kubectl set image` - which leaves no history entry behind it.
SOME_CONTAINER = "io-shop"
AN_IMAGE_SET_BY_HAND = "io-shop:hand-built"

# What a rollback leaves where it suspended the sync and the revision never moved:
# the plan it was made from, whole.
THE_SUSPENSION = DeploymentRollbackUndo(
    application=SOME_APPLICATION,
    was_on_history_id=THE_ENTRY_RUNNING,
    was_on_revision=THE_REVISION_RUNNING,
    rolled_back_to_revision=THE_REVISION_BEFORE_IT,
    rolled_back_to_history_id=THE_ENTRY_BEFORE_IT,
    was_syncing_itself=True
)

# A platform with no sync asked of it and none it has run - the demo's stand-in,
# which keeps no state of its runs, among them - so the history alone says
# what was deployed.
NO_SYNC_ASKED_OR_RUN = SyncOperations(requested=None, last_run=None)
# Where a run stands while the platform still keeps the request it was asked
# by: it clears the request only once the run completes.
THE_PHASES_A_REQUEST_IS_KEPT_THROUGH = {SyncPhase.RUNNING, SyncPhase.TERMINATING}
# Where a run that failed of itself stands - failed, or errored - and so no
# stop of anybody's. A run somebody terminated stands apart from both.
EVERY_WAY_A_RUN_FAILS_OF_ITSELF = [SyncPhase.FAILED, SyncPhase.ERROR]
# A put-back stopped: being terminated, its request still kept, or terminated -
# by somebody, or by the platform's own sync timeout where one is set.
EVERY_WAY_SOMEBODY_STOPS_A_PUT_BACK = [
    pytest.param(SyncPhase.TERMINATING, id="being-terminated"),
    pytest.param(SyncPhase.TERMINATED, id="terminated")
]
# How a performed rollback whose run of Argus's failed of itself is said - which
# a run somebody terminated is not.
THE_RUN_FAILED = "the rollback's run failed"
# Why nobody can say whose a rollback is whose newest entry is Argus's own, of a
# revision it did not roll back to - not a change since: Argus's account is
# Argus's, whichever walk or person used it.
ARGUS_S_ACCOUNT_ELSEWHERE = "Argus's account at a revision this rollback did not go to"
# The platform in the middle of a sync of its own - asked by nobody, to the
# revision it already runs - as an automated sync is.
THE_PLATFORM_MID_SYNC = SyncOperations(
    requested=RequestedSync(revision=THE_REVISION_RUNNING, initiated_by=None),
    last_run=None
)

# Every way a rollback of Argus's is found somebody else's since, each as the
# platform it leaves - syncing itself or not, as a case says. Lambdas, so the
# builders they call can be defined further down.
EVERY_WAY_A_ROLLBACK_BECOMES_SOMEBODY_S = [
    pytest.param(
        lambda syncing: a_platform_as_the_rollback_left_it(
            newest=_a_deployment(THE_NEXT_ENTRY, A_REVISION_SOMEBODY_ELSE_DEPLOYED,
                                 initiated_by=SOME_PERSON),
            syncing_itself=syncing
        ),
        id="a-revision-somebody-deployed"
    ),
    pytest.param(
        lambda syncing: a_platform_as_the_rollback_left_it(
            images_running={SOME_CONTAINER: AN_IMAGE_SET_BY_HAND},
            syncing_itself=syncing
        ),
        id="an-image-set-by-hand-on-argus-s-own-entry"
    ),
    pytest.param(
        lambda syncing: a_platform_as_the_rollback_left_it(
            newest=_a_deployment(THE_NEXT_ENTRY, THE_REVISION_RUNNING,
                                 initiated_by=SOME_PERSON),
            images_running={SOME_CONTAINER: AN_IMAGE_SET_BY_HAND},
            syncing_itself=syncing
        ),
        id="an-image-set-by-hand-on-an-entry-already-back"
    )
]

# Every history whose newest run returns to a revision already in it - a
# rollback already made, whoever made it, or the revision deployed again after
# another. Rolling back from any of them would roll forward to the revision the
# return went away from.
EVERY_HISTORY_WHOSE_NEWEST_RUN_IS_A_RETURN = [
    pytest.param(
        lambda: [*_two_deployments(),
                 _a_deployment(THE_NEXT_ENTRY, THE_REVISION_BEFORE_IT,
                               initiated_by=SOME_ARGUS_ACCOUNT, made_by_argus=True)],
        id="argus-s-own-rollback"
    ),
    pytest.param(
        lambda: [*_two_deployments(),
                 _a_deployment(THE_NEXT_ENTRY, THE_REVISION_BEFORE_IT,
                               initiated_by=SOME_PERSON)],
        id="a-person-s-rollback"
    ),
    pytest.param(
        lambda: _a_history(THE_REVISION_RUNNING, THE_REVISION_BEFORE_IT, THE_REVISION_RUNNING),
        id="a-revision-deployed-again-after-another"
    )
]

# Every way the sync switch is found other than the plan found it, before
# anything is written: (whether the plan found it syncing, whether it syncs now,
# whose mark the application carries).
EVERY_WAY_THE_SYNC_CHANGED_SINCE = [
    pytest.param(False, True, None, id="somebody-turned-it-on"),
    pytest.param(True, False, None, id="somebody-suspended-it-unmarked"),
    pytest.param(True, False, ANOTHER_CLAIM, id="suspended-under-another-action-s-mark"),
    pytest.param(True, True, THIS_CLAIM,
                 id="somebody-resumed-what-this-action-suspended")
]

# Every newest entry of the revision a plan returns to that is not this
# rollback: a person's since the plan, and Argus's own from before it. Lambdas,
# so the builders they call can be defined further down.
EVERY_RETURN_TO_THE_TARGET_NOT_ARGUS_S = [
    pytest.param(
        lambda: _a_deployment(THE_NEXT_ENTRY, THE_REVISION_BEFORE_IT,
                              deployed_at=AFTER_THE_PLAN, initiated_by=SOME_PERSON),
        id="a-person-s-rollback-since-the-plan"
    ),
    pytest.param(
        lambda: _a_deployment(THE_NEXT_ENTRY, THE_REVISION_BEFORE_IT,
                              deployed_at=BEFORE_THE_PLAN, initiated_by=SOME_ARGUS_ACCOUNT,
                              made_by_argus=True),
        id="argus-s-rollback-from-before-the-plan"
    )
]

# Every write the platform port has. A plan asks none of them.
EVERY_WRITE = ["suspend_sync", "resume_sync", "roll_back", "scale", "restart",
               "set_autoscaler_floor", "pin_to_accelerator"]


def _a_deployment(history_id: int,
                  revision: str,
                  deployed_at: datetime = BEFORE_THE_PLAN,
                  initiated_by: str | None = None,
                  made_by_argus: bool | None = None) -> DeploymentRecord:
    """Landed before any plan here was read, unless a case says otherwise -
    and stamped as the platform stamps it, whose it is included."""
    return DeploymentRecord(
        history_id=history_id,
        revision=revision,
        deployed_at=deployed_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        repo_url=None,
        path=None,
        initiated_by=initiated_by,
        made_by_argus=made_by_argus
    )


def _a_history(*revisions: str) -> list[DeploymentRecord]:
    """One entry per revision, oldest first and numbered from 1, as the platform
    serves them."""
    return [_a_deployment(history_id, revision)
            for history_id, revision in enumerate(revisions, start=1)]


def _the_images_rendered_for(revision: str) -> dict[str, str]:
    """What the platform renders the Deployment's containers as at `revision` -
    an image of each revision's own, as a build pipeline tags them."""
    return {SOME_CONTAINER: f"{SOME_CONTAINER}:{revision[:7]}"}


def _argus_s_rollback() -> DeploymentRecord:
    """The entry Argus's rollback added: by Argus's account, of the revision
    before the one that was running."""
    return _a_deployment(THE_NEXT_ENTRY, THE_REVISION_BEFORE_IT,
                         initiated_by=SOME_ARGUS_ACCOUNT, made_by_argus=True)


def _argus_s_rollback_since_the_plan() -> DeploymentRecord:
    """The entry this rollback adds: Argus's own, of the revision the plan
    returns to, landed after the plan was read."""
    return _a_deployment(THE_NEXT_ENTRY, THE_REVISION_BEFORE_IT,
                         deployed_at=AFTER_THE_PLAN, initiated_by=SOME_ARGUS_ACCOUNT,
                         made_by_argus=True)


def _a_plan(was_syncing_itself: bool) -> Planned[DeploymentRollbackUndo]:
    """The plan for rolling the two deployments back, read at the platform's
    `SOME_PLATFORM_TIME`."""
    return Planned(descriptor=_a_descriptor(was_syncing_itself=was_syncing_itself),
                   since=SOME_PLATFORM_TIME)


def _a_run(phase: SyncPhase,
           started_at: datetime,
           revision: str = THE_REVISION_BEFORE_IT) -> SyncOperations:
    """The last sync the platform ran: to `revision` - the one the plan returns
    to, unless a case names the one it found - by Argus's account, started at
    `started_at` and standing at `phase` - with its request still kept while it
    runs or is being terminated, as the platform keeps it until the run
    completes, and none asked once it has."""
    return SyncOperations(
        requested=(
            RequestedSync(revision=revision, initiated_by=SOME_ARGUS_ACCOUNT, made_by_argus=True)
            if phase in THE_PHASES_A_REQUEST_IS_KEPT_THROUGH else None
        ),
        last_run=SyncRun(revision=revision, initiated_by=SOME_ARGUS_ACCOUNT, made_by_argus=True,
                         started_at=started_at, phase=phase)
    )


def _a_platform_terminating_this_rollback() -> Any:
    """A platform this claim's rollback was asked of, whose run of it somebody
    is terminating: the request kept, the run terminating, the sync suspended
    under this claim's mark, and no entry of the rollback in the history."""
    return a_platform(syncing_itself=False, marked_by=THIS_CLAIM,
                      operations=_a_run(SyncPhase.TERMINATING, started_at=AFTER_THE_PLAN))


def _a_platform_where_somebody_terminated_this_rollback() -> Any:
    """A platform this claim's rollback was asked of, whose run of it somebody
    terminated: the run finished terminated, no request kept, the sync
    suspended under this claim's mark, no entry of the rollback in the history,
    and the Deployment still running what the revision it was on renders."""
    platform = a_platform(syncing_itself=False, marked_by=THIS_CLAIM,
                          operations=_a_run(SyncPhase.TERMINATED, started_at=AFTER_THE_PLAN))
    platform.images_running.return_value = _the_images_rendered_for(THE_REVISION_RUNNING)
    platform.images_at.side_effect = (
        lambda dont_care_application, revision: _the_images_rendered_for(revision)
    )

    return platform


def a_platform_as_the_rollback_left_it(newest: DeploymentRecord | None = None,
                                       images_running: dict[str, str] | None = None,
                                       syncing_itself: bool = False,
                                       operations: SyncOperations = NO_SYNC_ASKED_OR_RUN
                                       ) -> Any:
    """A platform a rollback of Argus's has been through: the history it found,
    then `newest` - Argus's own entry unless a case names somebody's - and the
    Deployment running `images_running`, which are the images rendered for the
    newest entry's revision unless a case names others. Not syncing itself,
    because the rollback suspended that, unless a case says somebody turned it
    back on - and no sync asked or run unless a case says otherwise."""
    on_top = newest if newest is not None else _argus_s_rollback()
    platform = _a_platform_holding(history=[*_two_deployments(), on_top],
                                   syncing_itself=syncing_itself,
                                   operations=operations)
    platform.images_running.return_value = (
        images_running if images_running is not None
        else _the_images_rendered_for(on_top.revision)
    )
    platform.images_at.side_effect = (
        lambda dont_care_application, revision: _the_images_rendered_for(revision)
    )

    return platform


def _two_deployments() -> list[DeploymentRecord]:
    """In the order the platform serves them: the one running is last."""
    return [
        _a_deployment(THE_ENTRY_BEFORE_IT, THE_REVISION_BEFORE_IT),
        _a_deployment(THE_ENTRY_RUNNING, THE_REVISION_RUNNING)
    ]


def _a_platform_holding(history: list[DeploymentRecord] | None,
                        syncing_itself: bool,
                        operations: SyncOperations = NO_SYNC_ASKED_OR_RUN) -> Any:
    platform = create_autospec(DeploymentPlatformWrites, instance=True)
    platform.deployments_of.return_value = (
        history if history is not None else _two_deployments()
    )
    platform.is_syncing_itself.return_value = syncing_itself
    platform.sync_operations_of.return_value = operations

    return platform


def a_platform(history: list[DeploymentRecord] | None = None,
               syncing_itself: bool = True,
               marked_by: str | None = None,
               operations: SyncOperations = NO_SYNC_ASKED_OR_RUN) -> Any:
    """A platform a plan or a rollback is made against: its clock answering
    with `SOME_PLATFORM_TIME`, the application carrying the mark of the action
    `marked_by` names - none unless a case names one - and no sync asked or run
    unless a case says otherwise."""
    platform = _a_platform_holding(history, syncing_itself, operations)
    platform.now.return_value = SOME_PLATFORM_TIME
    # The Application is the one object a rollback marks: its sync switch.
    platform.mark_on.side_effect = (
        lambda dont_care_application, kind: (
            a_mark_found(marked_by) if kind == MarkedObject.APPLICATION else None
        )
    )

    return platform


@pytest.mark.unit
def test_a_plan_returns_to_the_entry_before_the_one_running() -> None:
    # The choice `argocd app rollback APPNAME` makes with its id omitted, where
    # the history has nothing more to it than two deployments.
    platform = a_platform(syncing_itself=True)

    Scenario() \
        .given(platform) \
        .when(lambda: plan_rollback(SOME_APPLICATION, platform)) \
        .then(_it_planned(DeploymentRollbackUndo(
            application=SOME_APPLICATION,
            was_on_history_id=THE_ENTRY_RUNNING,
            was_on_revision=THE_REVISION_RUNNING,
            rolled_back_to_revision=THE_REVISION_BEFORE_IT,
            rolled_back_to_history_id=THE_ENTRY_BEFORE_IT,
            was_syncing_itself=True
        )))


@pytest.mark.unit
@pytest.mark.parametrize("syncing_itself", [True, False])
def test_a_plan_records_whether_the_platform_was_syncing_itself(syncing_itself: bool) -> None:
    # Only the plan ever reads it before anything changes. A withdrawal hours
    # later can put back exactly as much as this records, and the rollback holds
    # the switch to it.
    platform = a_platform(syncing_itself=syncing_itself)

    Scenario() \
        .given(platform) \
        .when(lambda: plan_rollback(SOME_APPLICATION, platform)) \
        .then(_the_plan_records_sync_was(syncing_itself))


@pytest.mark.unit
def test_a_plan_changes_nothing() -> None:
    # It is the read the claim is written from, before anything is asked to
    # change - and it carries no mark, because it leaves nothing to carry one.
    platform = a_platform(syncing_itself=True)

    Scenario() \
        .given(platform) \
        .when(lambda: plan_rollback(SOME_APPLICATION, platform)) \
        .then(_no_write_was_asked(platform))


@pytest.mark.unit
def test_a_plan_is_dated_by_the_platform_s_own_clock() -> None:
    # What a resumed walk asks the platform about - whether Argus's rollback
    # landed after it - so it is the platform's time, never the write tier's.
    platform = a_platform()

    Scenario() \
        .given(platform) \
        .when(lambda: plan_rollback(SOME_APPLICATION, platform)) \
        .then(_it_is_dated(SOME_PLATFORM_TIME))


@pytest.mark.unit
def test_a_plan_does_not_return_to_a_re_sync_of_the_revision_running() -> None:
    # Every full sync adds an entry, so the entry before the newest can be the
    # very revision running. Rolled back to, it would change nothing and be
    # judged as though it had.
    history = _a_history(THE_REVISION_BEFORE_IT, THE_REVISION_RUNNING, THE_REVISION_RUNNING)
    platform = a_platform(history=history, syncing_itself=True)

    Scenario() \
        .given(platform) \
        .when(lambda: plan_rollback(SOME_APPLICATION, platform)) \
        .then(_it_planned(DeploymentRollbackUndo(
            application=SOME_APPLICATION,
            was_on_history_id=history[-1].history_id,
            was_on_revision=THE_REVISION_RUNNING,
            rolled_back_to_revision=THE_REVISION_BEFORE_IT,
            rolled_back_to_history_id=history[0].history_id,
            was_syncing_itself=True
        )))


@pytest.mark.unit
def test_a_plan_returns_to_the_last_entry_of_the_run_before_the_one_running() -> None:
    # The revision before is synced more than once: its newest entry is the one
    # rolled back to, and nothing older than that run is.
    history = _a_history(AN_OLDER_REVISION, THE_REVISION_BEFORE_IT, THE_REVISION_BEFORE_IT,
                         THE_REVISION_RUNNING)
    the_last_entry_of_the_run_before = history[2]
    platform = a_platform(history=history, syncing_itself=True)

    Scenario() \
        .given(platform) \
        .when(lambda: plan_rollback(SOME_APPLICATION, platform)) \
        .then(_it_planned(DeploymentRollbackUndo(
            application=SOME_APPLICATION,
            was_on_history_id=history[-1].history_id,
            was_on_revision=THE_REVISION_RUNNING,
            rolled_back_to_revision=THE_REVISION_BEFORE_IT,
            rolled_back_to_history_id=the_last_entry_of_the_run_before.history_id,
            was_syncing_itself=True
        )))


@pytest.mark.unit
@pytest.mark.parametrize("a_history_ending_in_a_return", EVERY_HISTORY_WHOSE_NEWEST_RUN_IS_A_RETURN)
def test_a_history_whose_newest_run_returns_to_an_earlier_revision_is_refused(
    a_history_ending_in_a_return: Callable[[], list[DeploymentRecord]]
) -> None:
    # The deployment is already back on a revision it ran before. The entry
    # before the newest is the one that return went away from, and rolling back
    # to it would undo the rollback - Argus's own or a person's alike, which is
    # why nobody's account is read.
    platform = a_platform(history=a_history_ending_in_a_return())

    Scenario() \
        .given(platform) \
        .when(attempting(lambda: plan_rollback(SOME_APPLICATION, platform))) \
        .then(all_of(
            an_error_was_raised(NoEarlierRevision),
            _the_refusal_says_the_action_is_exhausted(),
            _no_write_was_asked(platform)
        ))


@pytest.mark.unit
def test_an_application_with_no_earlier_entry_is_refused_before_anything_changes() -> None:
    # An application on its first deployment. Told "done", a caller would
    # record a mitigation that never happened and judge the service against it.
    only_ever_deployed_once = [_a_deployment(THE_ENTRY_RUNNING, THE_REVISION_RUNNING)]
    platform = a_platform(history=only_ever_deployed_once)

    Scenario() \
        .given(platform) \
        .when(attempting(lambda: plan_rollback(SOME_APPLICATION, platform))) \
        .then(all_of(
            an_error_was_raised(NoEarlierRevision),
            _nothing_was_changed(platform)
        ))


@pytest.mark.unit
def test_an_application_only_ever_synced_to_one_revision_is_refused() -> None:
    # Several entries, one deployment: every one of them runs what is running.
    platform = a_platform(history=_a_history(THE_REVISION_RUNNING, THE_REVISION_RUNNING))

    Scenario() \
        .given(platform) \
        .when(attempting(lambda: plan_rollback(SOME_APPLICATION, platform))) \
        .then(all_of(
            an_error_was_raised(NoEarlierRevision),
            _no_write_was_asked(platform)
        ))


@pytest.mark.unit
def test_an_application_that_has_never_deployed_is_refused() -> None:
    platform = a_platform(history=[])

    Scenario() \
        .given(platform) \
        .when(attempting(lambda: plan_rollback(SOME_APPLICATION, platform))) \
        .then(all_of(
            an_error_was_raised(NoEarlierRevision),
            _nothing_was_changed(platform)
        ))


@pytest.mark.unit
def test_an_application_with_no_earlier_entry_refuses_in_a_way_a_caller_can_recognise() -> None:
    # The refusal that is an answer, as a deployment already at its ceiling
    # refuses a scale-out: nothing was changed and the action has nowhere to
    # go, so the walk tries its next explanation rather than waking a human, and
    # the postmortem says nothing was changed rather than that nobody knows.
    only_ever_deployed_once = [_a_deployment(THE_ENTRY_RUNNING, THE_REVISION_RUNNING)]
    platform = a_platform(history=only_ever_deployed_once)

    Scenario() \
        .given(platform) \
        .when(attempting(lambda: plan_rollback(SOME_APPLICATION, platform))) \
        .then(_the_refusal_says_the_action_is_exhausted())


@pytest.mark.unit
def test_a_platform_that_never_answered_the_read_is_reported_as_unreachable() -> None:
    # Nothing has been touched when this fails, which is what makes the report
    # honest: the walk is told that four actions are unavailable and told
    # nothing about a state somebody has to put back.
    platform = a_platform()
    platform.deployments_of.side_effect = PlatformUnreachable(DONT_CARE_PLATFORM_WORDS)

    Scenario() \
        .given(platform) \
        .when(attempting(lambda: plan_rollback(SOME_APPLICATION, platform))) \
        .then(_it_is_reported_as_an_unreachable_platform())


@pytest.mark.unit
def test_a_history_the_platform_would_not_give_is_known_to_have_changed_nothing() -> None:
    # The history is read before anything is asked to change, so a refusal
    # here says it left nothing - and is not written up as nobody knowing
    # whether anything was changed.
    platform = a_platform()
    platform.deployments_of.side_effect = PlatformRefused(DONT_CARE_PLATFORM_WORDS)

    Scenario() \
        .given(platform) \
        .when(attempting(lambda: plan_rollback(SOME_APPLICATION, platform))) \
        .then(all_of(
            it_was_refused_as(RollbackRefused),
            it_is_marked_unreachable(False),
            what_it_left_is_known(True),
            it_left_behind(None)
        ))


@pytest.mark.unit
def test_asking_whether_it_syncs_itself_is_a_read_and_changes_nothing() -> None:
    # A timed-out read took nothing with it, so the platform is reported as
    # gone and the estate as untouched.
    platform = a_platform()
    platform.is_syncing_itself.side_effect = PlatformUnreachable(
        DONT_CARE_PLATFORM_WORDS, known_not_applied=False
    )

    Scenario() \
        .given(platform) \
        .when(attempting(lambda: plan_rollback(SOME_APPLICATION, platform))) \
        .then(all_of(
            it_is_marked_unreachable(True),
            what_it_left_is_known(True),
            it_left_behind(None)
        ))


@pytest.mark.unit
def test_a_rollback_goes_to_the_entry_its_plan_names() -> None:
    # Not the entry before the newest, re-derived: the plan is what the claim
    # recorded, and the entry it names is what the action is. The history only
    # ever grows, so the plan's two entries are still in it - and the platform's
    # own sync, which names nobody, has deployed another revision since and then
    # the one the plan found again. The running revision is the one the plan
    # found, under an entry of another number, and a target worked out again
    # from this history would be the revision the sync passed through.
    live = [*_two_deployments(),
            _a_deployment(THE_NEXT_ENTRY, A_REVISION_SOMEBODY_ELSE_DEPLOYED,
                          deployed_at=AFTER_THE_PLAN),
            _a_deployment(THE_ENTRY_AFTER_THAT, THE_REVISION_RUNNING,
                          deployed_at=AFTER_THE_PLAN)]
    platform = a_platform(history=live, syncing_itself=True)

    Scenario() \
        .given(planned := _a_plan(was_syncing_itself=True)) \
        .when(lambda: roll_back_deployment(planned, platform, SOME_MARK, SOME_ARGUS_ACCOUNT)) \
        .then(_it_rolled_back_to(platform, THE_ENTRY_BEFORE_IT))


@pytest.mark.unit
def test_reconciliation_is_suspended_before_the_rollback_is_asked_for() -> None:
    # The platform refuses a rollback while it syncs the application itself,
    # and would re-apply the revision being rolled away from at the next pass.
    platform = a_platform(syncing_itself=True)

    Scenario() \
        .given(planned := _a_plan(was_syncing_itself=True)) \
        .when(lambda: roll_back_deployment(planned, platform, SOME_MARK, SOME_ARGUS_ACCOUNT)) \
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
        .given(planned := _a_plan(was_syncing_itself=False)) \
        .when(lambda: roll_back_deployment(planned, platform, SOME_MARK, SOME_ARGUS_ACCOUNT)) \
        .then(all_of(
            _the_sync_policy_was_not_touched(platform),
            _it_rolled_back_to(platform, THE_ENTRY_BEFORE_IT)
        ))


@pytest.mark.unit
def test_a_rollback_argus_made_since_the_plan_is_answered_as_made() -> None:
    # The redo of a rollback whose answer was lost: the newest entry is Argus's
    # own, of the revision the plan returns to, made after the plan was read -
    # under the suspension this action marked. Nothing is written and nothing
    # is refused, and the answer is the one the first asking would have given.
    platform = a_platform(history=[*_two_deployments(), _argus_s_rollback_since_the_plan()],
                          syncing_itself=False,
                          marked_by=THIS_CLAIM)

    Scenario() \
        .given(planned := _a_plan(was_syncing_itself=True)) \
        .when(lambda: roll_back_deployment(planned, platform, SOME_MARK, SOME_ARGUS_ACCOUNT)) \
        .then(all_of(
            _no_write_was_asked(platform),
            _it_answered_with(_dated(planned.descriptor, AFTER_THE_PLAN))
        ))


@pytest.mark.unit
def test_a_rollback_argus_made_in_the_plan_s_own_second_is_answered_as_made() -> None:
    # The platform dates its entries and its answers in whole seconds, so a
    # rollback landing in the second the plan was read carries the plan's own
    # time. "Since the plan" is at or after it: read as strictly after, this
    # action's own rollback would be refused as somebody's.
    in_the_plan_s_second = _a_deployment(THE_NEXT_ENTRY, THE_REVISION_BEFORE_IT,
                                         deployed_at=SOME_PLATFORM_TIME,
                                         initiated_by=SOME_ARGUS_ACCOUNT, made_by_argus=True)
    platform = a_platform(history=[*_two_deployments(), in_the_plan_s_second],
                          syncing_itself=False,
                          marked_by=THIS_CLAIM)

    Scenario() \
        .given(planned := _a_plan(was_syncing_itself=True)) \
        .when(lambda: roll_back_deployment(planned, platform, SOME_MARK, SOME_ARGUS_ACCOUNT)) \
        .then(all_of(
            _no_write_was_asked(platform),
            _it_answered_with(_dated(planned.descriptor, SOME_PLATFORM_TIME))
        ))


@pytest.mark.unit
def test_a_rollback_argus_asked_for_that_the_platform_has_not_run_is_answered_as_made() -> None:
    # The platform records a rollback the moment it answers the request, and
    # writes the history entry only once it has run it - so a rollback asked
    # again while the first is still waiting finds no entry of its own. The
    # request, to the plan's revision and by Argus's account, is this one:
    # asked again, the platform would refuse it as another operation already in
    # progress, and the first would land unrecorded.
    platform = a_platform(syncing_itself=False, marked_by=THIS_CLAIM,
                          operations=SyncOperations(
                              requested=RequestedSync(revision=THE_REVISION_BEFORE_IT,
                                                      initiated_by=SOME_ARGUS_ACCOUNT,
                                                      made_by_argus=True),
                              last_run=None
                          ))

    Scenario() \
        .given(planned := _a_plan(was_syncing_itself=True)) \
        .when(lambda: roll_back_deployment(planned, platform, SOME_MARK, SOME_ARGUS_ACCOUNT)) \
        .then(all_of(
            _no_write_was_asked(platform),
            _it_answered_with(planned.descriptor)
        ))


@pytest.mark.unit
@pytest.mark.parametrize("phase", [SyncPhase.RUNNING, SyncPhase.SUCCEEDED])
def test_a_rollback_argus_s_sync_started_since_the_plan_is_answered_as_made(
    phase: SyncPhase
) -> None:
    # Running, or finished before its entry was read: either way the sync the
    # platform started after the plan, to the plan's revision and by Argus's
    # account, is this rollback.
    platform = a_platform(syncing_itself=False, marked_by=THIS_CLAIM,
                          operations=_a_run(phase, started_at=AFTER_THE_PLAN))

    Scenario() \
        .given(planned := _a_plan(was_syncing_itself=True)) \
        .when(lambda: roll_back_deployment(planned, platform, SOME_MARK, SOME_ARGUS_ACCOUNT)) \
        .then(all_of(
            _no_write_was_asked(platform),
            _it_answered_with(_dated(planned.descriptor, AFTER_THE_PLAN))
        ))


@pytest.mark.unit
@pytest.mark.parametrize("phase", EVERY_WAY_A_RUN_FAILS_OF_ITSELF)
def test_a_rollback_argus_s_sync_could_not_make_is_made_again(phase: SyncPhase) -> None:
    # A sync that failed of itself returned nothing: the platform still runs the
    # revision the plan found, so the rollback is asked again - under the
    # suspension this action already made, which is not made twice.
    platform = a_platform(syncing_itself=False, marked_by=THIS_CLAIM,
                          operations=_a_run(phase, started_at=AFTER_THE_PLAN))

    Scenario() \
        .given(planned := _a_plan(was_syncing_itself=True)) \
        .when(lambda: roll_back_deployment(planned, platform, SOME_MARK, SOME_ARGUS_ACCOUNT)) \
        .then(all_of(
            _the_sync_policy_was_not_touched(platform),
            _it_rolled_back_to(platform, THE_ENTRY_BEFORE_IT)
        ))


@pytest.mark.unit
def test_a_sync_another_account_asked_for_still_being_run_is_a_change_since() -> None:
    # Somebody is deploying this application right now, and the platform would
    # refuse a rollback asked beside it as another operation in progress -
    # an answer that says nothing of what lands. Refused here instead, knowing
    # nothing was written.
    platform = a_platform(syncing_itself=True,
                          operations=SyncOperations(
                              requested=RequestedSync(
                                  revision=A_REVISION_SOMEBODY_ELSE_DEPLOYED,
                                  initiated_by=SOME_PERSON
                              ),
                              last_run=None
                          ))

    Scenario() \
        .given(planned := _a_plan(was_syncing_itself=True)) \
        .when(attempting(
            lambda: roll_back_deployment(planned, platform, SOME_MARK, SOME_ARGUS_ACCOUNT)
        )) \
        .then(all_of(
            it_was_refused_as_changed_since(),
            its_change_is_said_performed(False),
            what_it_left_is_known(True),
            it_left_behind(None),
            _no_write_was_asked(platform)
        ))


@pytest.mark.unit
def test_a_rollback_is_not_asked_while_the_platform_runs_a_sync_of_its_own() -> None:
    # The platform's own sync names nobody, so it is no change of anybody's -
    # but a rollback asked while it runs is refused as another operation in
    # progress, an answer that says nothing of what lands. So nothing is asked:
    # refused plainly, knowing nothing was written, the sync switch included.
    platform = a_platform(syncing_itself=True, operations=THE_PLATFORM_MID_SYNC)

    Scenario() \
        .given(planned := _a_plan(was_syncing_itself=True)) \
        .when(attempting(
            lambda: roll_back_deployment(planned, platform, SOME_MARK, SOME_ARGUS_ACCOUNT)
        )) \
        .then(all_of(
            it_was_refused_as(RollbackRefused),
            it_is_marked_unreachable(False),
            what_it_left_is_known(True),
            it_left_behind(None),
            _no_write_was_asked(platform)
        ))


@pytest.mark.unit
def test_a_rollback_re_asked_mid_sync_still_carries_the_suspension_it_made() -> None:
    # Asked again after the first asking's suspension landed, and the platform
    # has started a sync of its own since. Nothing is written - and the refusal
    # says what this claim left out there, which a withdrawal puts back.
    platform = a_platform(syncing_itself=False, marked_by=THIS_CLAIM,
                          operations=THE_PLATFORM_MID_SYNC)

    Scenario() \
        .given(planned := _a_plan(was_syncing_itself=True)) \
        .when(attempting(
            lambda: roll_back_deployment(planned, platform, SOME_MARK, SOME_ARGUS_ACCOUNT)
        )) \
        .then(all_of(
            it_was_refused_as(RollbackRefused),
            what_it_left_is_known(True),
            it_left_behind(THE_SUSPENSION),
            _no_write_was_asked(platform)
        ))


@pytest.mark.unit
def test_a_rollback_whose_sync_somebody_is_terminating_is_a_change_since() -> None:
    # The platform keeps the request while a sync is being terminated, so this
    # rollback's own reads as still asked - and terminating it is something only
    # somebody does. Refused as their change, nothing written, and said to have
    # been performed: the rollback was asked, whatever is left of it.
    platform = _a_platform_terminating_this_rollback()

    Scenario() \
        .given(planned := _a_plan(was_syncing_itself=True)) \
        .when(attempting(
            lambda: roll_back_deployment(planned, platform, SOME_MARK, SOME_ARGUS_ACCOUNT)
        )) \
        .then(all_of(
            it_was_refused_as_changed_since(),
            its_change_is_said_performed(True),
            it_left_behind(THE_SUSPENSION),
            _no_write_was_asked(platform)
        ))


@pytest.mark.unit
def test_a_rollback_whose_sync_somebody_terminated_is_a_change_since() -> None:
    # Terminated, not failed of itself - which is asked again: somebody stopped
    # this rollback, and asking it again would overrule them. Refused as their
    # change, nothing written, and said performed: the rollback was asked.
    platform = _a_platform_where_somebody_terminated_this_rollback()

    Scenario() \
        .given(planned := _a_plan(was_syncing_itself=True)) \
        .when(attempting(
            lambda: roll_back_deployment(planned, platform, SOME_MARK, SOME_ARGUS_ACCOUNT)
        )) \
        .then(all_of(
            it_was_refused_as_changed_since(),
            its_change_is_said_performed(True),
            it_left_behind(THE_SUSPENSION),
            _no_write_was_asked(platform)
        ))


@pytest.mark.unit
@pytest.mark.parametrize("phase", list(SyncPhase), ids=lambda phase: phase.name.lower())
def test_a_sync_another_account_started_since_the_plan_is_a_change_since(
    phase: SyncPhase
) -> None:
    # Whatever came of it: somebody deployed this application after the plan,
    # and one that failed leaves no entry in the history to say so.
    # The request kept beside a run still going, as the platform keeps it.
    still_asked = (RequestedSync(revision=A_REVISION_SOMEBODY_ELSE_DEPLOYED,
                                 initiated_by=SOME_PERSON)
                   if phase in THE_PHASES_A_REQUEST_IS_KEPT_THROUGH else None)
    platform = a_platform(syncing_itself=True,
                          operations=SyncOperations(
                              requested=still_asked,
                              last_run=SyncRun(revision=A_REVISION_SOMEBODY_ELSE_DEPLOYED,
                                               initiated_by=SOME_PERSON,
                                               started_at=AFTER_THE_PLAN, phase=phase)
                          ))

    Scenario() \
        .given(planned := _a_plan(was_syncing_itself=True)) \
        .when(attempting(
            lambda: roll_back_deployment(planned, platform, SOME_MARK, SOME_ARGUS_ACCOUNT)
        )) \
        .then(all_of(
            it_was_refused_as_changed_since(),
            its_change_is_said_performed(False),
            it_left_behind(None),
            _no_write_was_asked(platform)
        ))


@pytest.mark.unit
@pytest.mark.parametrize(
    "this_rollback_under_way",
    [
        pytest.param(SyncOperations(
            requested=RequestedSync(revision=THE_REVISION_BEFORE_IT,
                                    initiated_by=SOME_ARGUS_ACCOUNT, made_by_argus=True),
            last_run=None
        ), id="asked-and-not-yet-run"),
        pytest.param(_a_run(SyncPhase.RUNNING, started_at=AFTER_THE_PLAN), id="running")
    ]
)
def test_a_rollback_under_way_when_somebody_deployed_is_said_performed(
    this_rollback_under_way: SyncOperations
) -> None:
    # A person's deployment since the plan makes it a change since - and this
    # rollback was already asked of the platform, so the refusal says the change
    # was made, and carries the plan that puts it back.
    somebody_s = _a_deployment(THE_NEXT_ENTRY, A_REVISION_SOMEBODY_ELSE_DEPLOYED,
                               deployed_at=AFTER_THE_PLAN, initiated_by=SOME_PERSON)
    platform = a_platform(history=[*_two_deployments(), somebody_s], syncing_itself=False,
                          marked_by=THIS_CLAIM, operations=this_rollback_under_way)

    Scenario() \
        .given(planned := _a_plan(was_syncing_itself=True)) \
        .when(attempting(
            lambda: roll_back_deployment(planned, platform, SOME_MARK, SOME_ARGUS_ACCOUNT)
        )) \
        .then(all_of(
            it_was_refused_as_changed_since(),
            its_change_is_said_performed(True),
            it_left_behind(THE_SUSPENSION),
            _no_write_was_asked(platform)
        ))


@pytest.mark.unit
@pytest.mark.parametrize(
    "a_plan_the_rule_does_not_give",
    [
        pytest.param({"rolled_back_to_history_id": THE_ENTRY_RUNNING,
                      "rolled_back_to_revision": THE_REVISION_RUNNING},
                     id="the-entry-it-found-running"),
        pytest.param({"rolled_back_to_revision": AN_OLDER_REVISION},
                     id="another-revision-under-the-entry-before"),
        pytest.param({"rolled_back_to_revision": None}, id="no-revision"),
        pytest.param({"rolled_back_to_history_id": None}, id="no-entry")
    ]
)
def test_a_plan_the_tier_s_own_rule_does_not_give_is_refused_by_the_write(
    a_plan_the_rule_does_not_give: dict[str, Any]
) -> None:
    # The write returns to the entry the plan names rather than working one
    # out, so it holds the plan to the rule the plan step follows, over the
    # history up to the entry the plan found running: a plan built any other
    # way is no licence to send a deployment somewhere else. Refused plainly,
    # before the sync switch is touched.
    platform = a_platform(syncing_itself=True)
    off_the_rule = Planned[DeploymentRollbackUndo](
        descriptor=_a_descriptor(was_syncing_itself=True).model_copy(
            update=a_plan_the_rule_does_not_give
        ),
        since=SOME_PLATFORM_TIME
    )

    Scenario() \
        .given(off_the_rule) \
        .when(attempting(
            lambda: roll_back_deployment(off_the_rule, platform, SOME_MARK, SOME_ARGUS_ACCOUNT)
        )) \
        .then(all_of(
            it_was_refused_as(RollbackRefused),
            it_is_marked_unreachable(False),
            what_it_left_is_known(True),
            it_left_behind(None),
            _no_write_was_asked(platform)
        ))


@pytest.mark.unit
def test_a_rollback_with_no_account_to_look_for_is_made_where_nobody_named_deployed() -> None:
    # The account setting is empty where the credential is shared. Nobody named
    # has deployed or asked for a sync since the plan, so there is nothing whose
    # it could be to ask about, and the revision is the one the plan found.
    platform = a_platform(syncing_itself=True)

    Scenario() \
        .given(planned := _a_plan(was_syncing_itself=True)) \
        .when(lambda: roll_back_deployment(planned, platform, SOME_MARK, NO_ACCOUNT)) \
        .then(all_of(
            _it_was_asked_in_order(platform, "suspend_sync", "roll_back"),
            _it_rolled_back_to(platform, THE_ENTRY_BEFORE_IT)
        ))


@pytest.mark.unit
def test_a_rollback_with_no_account_to_look_for_is_unanswerable_once_somebody_named_deployed(
) -> None:
    # An entry since the plan by a named account could be Argus's own rollback
    # or a person's, and with no account to look for nothing tells them apart.
    # So nothing is written, and nothing is said to be known - but the
    # suspension this action made is still its own, and travels on the refusal.
    platform = a_platform(history=[*_two_deployments(), _argus_s_rollback_since_the_plan()],
                          syncing_itself=False,
                          marked_by=THIS_CLAIM)

    Scenario() \
        .given(planned := _a_plan(was_syncing_itself=True)) \
        .when(attempting(
            lambda: roll_back_deployment(planned, platform, SOME_MARK, NO_ACCOUNT)
        )) \
        .then(all_of(
            it_was_refused_as(RollbackRefused),
            what_it_left_is_known(False),
            it_left_behind(THE_SUSPENSION),
            _no_write_was_asked(platform)
        ))


@pytest.mark.unit
@pytest.mark.parametrize("a_return_not_argus_s", EVERY_RETURN_TO_THE_TARGET_NOT_ARGUS_S)
def test_the_revision_rolled_back_to_reached_other_than_by_this_rollback_is_a_change_since(
    a_return_not_argus_s: Callable[[], DeploymentRecord]
) -> None:
    # The value alone cannot say who put it there. A person's rollback to the
    # same revision, or one of Argus's from before the plan was read, is not
    # this action's - and answering it as made would judge the service against
    # a mitigation nobody here performed. This action's suspension did land,
    # and still stands, so the refusal carries it.
    platform = a_platform(history=[*_two_deployments(), a_return_not_argus_s()],
                          syncing_itself=False,
                          marked_by=THIS_CLAIM)

    Scenario() \
        .given(planned := _a_plan(was_syncing_itself=True)) \
        .when(attempting(
            lambda: roll_back_deployment(planned, platform, SOME_MARK, SOME_ARGUS_ACCOUNT)
        )) \
        .then(all_of(
            it_was_refused_as_changed_since(),
            its_change_is_said_performed(False),
            it_left_behind(THE_SUSPENSION),
            _no_write_was_asked(platform)
        ))


@pytest.mark.unit
def test_argus_s_rollback_since_undone_by_somebody_is_not_made_again() -> None:
    # The rollback landed after the plan, and somebody has since put the
    # revision the plan found back. Running it again would undo their decision,
    # so it is a change since, with no redo - and the suspension this action
    # made still stands, so the refusal carries it.
    put_back_by_somebody = _a_deployment(THE_ENTRY_AFTER_THAT, THE_REVISION_RUNNING,
                                         deployed_at=AFTER_THE_PLAN,
                                         initiated_by=SOME_PERSON)
    platform = a_platform(history=[*_two_deployments(), _argus_s_rollback_since_the_plan(),
                                   put_back_by_somebody],
                          syncing_itself=False,
                          marked_by=THIS_CLAIM)

    Scenario() \
        .given(planned := _a_plan(was_syncing_itself=True)) \
        .when(attempting(
            lambda: roll_back_deployment(planned, platform, SOME_MARK, SOME_ARGUS_ACCOUNT)
        )) \
        .then(all_of(
            it_was_refused_as_changed_since(),
            its_change_is_said_performed(True),
            it_left_behind(THE_SUSPENSION),
            _no_write_was_asked(platform)
        ))


@pytest.mark.unit
def test_a_revision_somebody_deployed_under_this_action_s_suspension_leaves_the_suspension(
) -> None:
    # The suspension landed under this action's mark and the rollback did not,
    # and somebody deployed a revision of their own in between. Nothing is
    # rolled back over them, and the switch this action turned off is still
    # off - so the refusal carries the plan, which is what puts it back on.
    somebody_s = _a_deployment(THE_NEXT_ENTRY, A_REVISION_SOMEBODY_ELSE_DEPLOYED,
                               deployed_at=AFTER_THE_PLAN, initiated_by=SOME_PERSON)
    platform = a_platform(history=[*_two_deployments(), somebody_s],
                          syncing_itself=False,
                          marked_by=THIS_CLAIM)

    Scenario() \
        .given(planned := _a_plan(was_syncing_itself=True)) \
        .when(attempting(
            lambda: roll_back_deployment(planned, platform, SOME_MARK, SOME_ARGUS_ACCOUNT)
        )) \
        .then(all_of(
            it_was_refused_as_changed_since(),
            its_change_is_said_performed(False),
            it_left_behind(THE_SUSPENSION),
            _no_write_was_asked(platform)
        ))


@pytest.mark.unit
def test_a_re_sync_of_the_revision_the_plan_found_is_not_a_change_since() -> None:
    # The platform syncing itself adds an entry of the same revision between the
    # plan and the rollback. The running revision is compared, never the entry,
    # so what runs is still what the plan found and the rollback is made to the
    # entry the plan names.
    re_synced = _a_deployment(THE_NEXT_ENTRY, THE_REVISION_RUNNING,
                              deployed_at=AFTER_THE_PLAN)
    platform = a_platform(history=[*_two_deployments(), re_synced], syncing_itself=True)

    Scenario() \
        .given(planned := _a_plan(was_syncing_itself=True)) \
        .when(lambda: roll_back_deployment(planned, platform, SOME_MARK, SOME_ARGUS_ACCOUNT)) \
        .then(all_of(
            _it_was_asked_in_order(platform, "suspend_sync", "roll_back"),
            _it_rolled_back_to(platform, THE_ENTRY_BEFORE_IT)
        ))


@pytest.mark.unit
def test_a_revision_somebody_deployed_since_the_plan_is_not_rolled_back() -> None:
    # Rolling back now would replace their deployment with one the plan chose
    # against a history that no longer stands. The sync still reads as the plan
    # found it, and is not suspended either: every comparison is made before
    # anything is written.
    somebody_s = _a_deployment(THE_NEXT_ENTRY, A_REVISION_SOMEBODY_ELSE_DEPLOYED,
                               deployed_at=AFTER_THE_PLAN, initiated_by=SOME_PERSON)
    platform = a_platform(history=[*_two_deployments(), somebody_s], syncing_itself=True)

    Scenario() \
        .given(planned := _a_plan(was_syncing_itself=True)) \
        .when(attempting(
            lambda: roll_back_deployment(planned, platform, SOME_MARK, SOME_ARGUS_ACCOUNT)
        )) \
        .then(all_of(
            it_was_refused_as_changed_since(),
            its_change_is_said_performed(False),
            it_is_marked_unreachable(False),
            what_it_left_is_known(True),
            it_left_behind(None),
            _no_write_was_asked(platform)
        ))


@pytest.mark.unit
def test_a_person_s_deploy_since_the_plan_is_a_change_since_even_back_at_the_revision_found(
) -> None:
    # Somebody deployed a revision of their own since the plan and then the
    # revision the plan found again. The running revision nets back to what the
    # plan found, and the history says a person is acting on this service now -
    # so the rollback is refused rather than made beside them, and nothing is
    # written.
    their_deploy = _a_deployment(THE_NEXT_ENTRY, A_REVISION_SOMEBODY_ELSE_DEPLOYED,
                                 deployed_at=AFTER_THE_PLAN, initiated_by=SOME_PERSON)
    their_redeploy = _a_deployment(THE_ENTRY_AFTER_THAT, THE_REVISION_RUNNING,
                                   deployed_at=AFTER_THE_PLAN, initiated_by=SOME_PERSON)
    platform = a_platform(history=[*_two_deployments(), their_deploy, their_redeploy],
                          syncing_itself=True)

    Scenario() \
        .given(planned := _a_plan(was_syncing_itself=True)) \
        .when(attempting(
            lambda: roll_back_deployment(planned, platform, SOME_MARK, SOME_ARGUS_ACCOUNT)
        )) \
        .then(all_of(
            it_was_refused_as_changed_since(),
            its_change_is_said_performed(False),
            what_it_left_is_known(True),
            it_left_behind(None),
            _no_write_was_asked(platform)
        ))


@pytest.mark.unit
@pytest.mark.parametrize(("was_syncing_itself", "syncing_now", "marked_by"),
                         EVERY_WAY_THE_SYNC_CHANGED_SINCE)
def test_a_sync_switch_changed_since_the_plan_refuses_the_rollback(
    was_syncing_itself: bool, syncing_now: bool, marked_by: str | None
) -> None:
    # Somebody's switch, every way: suspending what they turned on - or turned
    # back on after this action suspended it - or rolling back under a
    # suspension Argus would later resume as its own, writes over a decision
    # that is not Argus's. Found before anything is written, so not even the
    # suspension is.
    platform = a_platform(syncing_itself=syncing_now, marked_by=marked_by)

    Scenario() \
        .given(planned := _a_plan(was_syncing_itself=was_syncing_itself)) \
        .when(attempting(
            lambda: roll_back_deployment(planned, platform, SOME_MARK, SOME_ARGUS_ACCOUNT)
        )) \
        .then(all_of(
            it_was_refused_as_changed_since(),
            its_change_is_said_performed(False),
            it_is_marked_unreachable(False),
            what_it_left_is_known(True),
            it_left_behind(None),
            _no_write_was_asked(platform)
        ))


@pytest.mark.unit
def test_a_suspension_carrying_this_action_s_own_mark_is_rolled_back_under() -> None:
    # The redo of a rollback whose suspension landed and whose rollback did not:
    # the switch is off because this action turned it off, so it is not
    # suspended again and the rollback is made.
    platform = a_platform(syncing_itself=False, marked_by=THIS_CLAIM)

    Scenario() \
        .given(planned := _a_plan(was_syncing_itself=True)) \
        .when(lambda: roll_back_deployment(planned, platform, SOME_MARK, SOME_ARGUS_ACCOUNT)) \
        .then(all_of(
            _the_sync_policy_was_not_touched(platform),
            _it_rolled_back_to(platform, THE_ENTRY_BEFORE_IT)
        ))


@pytest.mark.unit
@pytest.mark.parametrize("read", ["deployments_of", "sync_operations_of", "is_syncing_itself"])
def test_a_rollback_that_could_not_read_the_platform_writes_nothing(read: str) -> None:
    # The live state is read before anything is written, so a read that never
    # came back took nothing with it: the platform is reported as gone and the
    # estate as untouched.
    platform = a_platform(syncing_itself=True)
    getattr(platform, read).side_effect = PlatformUnreachable(
        DONT_CARE_PLATFORM_WORDS, known_not_applied=False
    )

    Scenario() \
        .given(planned := _a_plan(was_syncing_itself=True)) \
        .when(attempting(
            lambda: roll_back_deployment(planned, platform, SOME_MARK, SOME_ARGUS_ACCOUNT)
        )) \
        .then(all_of(
            it_is_marked_unreachable(True),
            what_it_left_is_known(True),
            it_left_behind(None),
            _no_write_was_asked(platform)
        ))


@pytest.mark.unit
def test_a_platform_that_will_not_answer_is_not_reported_as_rolled_back() -> None:
    platform = a_platform()
    platform.roll_back.side_effect = PlatformUnreachable(DONT_CARE_PLATFORM_WORDS)

    Scenario() \
        .given(planned := _a_plan(was_syncing_itself=True)) \
        .when(attempting(
            lambda: roll_back_deployment(planned, platform, SOME_MARK, SOME_ARGUS_ACCOUNT)
        )) \
        .then(an_error_was_raised(RollbackRefused))


@pytest.mark.unit
def test_the_suspension_a_rollback_makes_carries_its_actions_mark() -> None:
    # The one write here that takes a mark: the rollback itself is the
    # platform's own history entry, and says whose it was in that history.
    platform = a_platform(syncing_itself=True)

    Scenario() \
        .given(planned := _a_plan(was_syncing_itself=True)) \
        .when(lambda: roll_back_deployment(planned, platform, SOME_MARK, SOME_ARGUS_ACCOUNT)) \
        .then(every_write_carried(platform, "suspend_sync", SOME_MARK))


@pytest.mark.unit
def test_turning_reconciliation_back_on_carries_the_restores_mark() -> None:
    # A restore is a write of Argus's as much as the action was, and is marked
    # as the one putting the action back.
    platform = a_platform_as_the_rollback_left_it()

    Scenario() \
        .given(descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: restore_deployment(descriptor, platform, SOME_MARK, SOME_ARGUS_ACCOUNT)) \
        .then(every_write_carried(platform, "resume_sync", SOME_MARK))


@pytest.mark.unit
def test_restoring_puts_back_the_entry_that_was_running() -> None:
    platform = a_platform_as_the_rollback_left_it()

    Scenario() \
        .given(descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: restore_deployment(descriptor, platform, SOME_MARK, SOME_ARGUS_ACCOUNT)) \
        .then(all_of(
            _it_rolled_back_to(platform, THE_ENTRY_RUNNING),
            _it_reports_restored(revision=True, automated_sync=True)
        ))


@pytest.mark.unit
def test_restoring_turns_reconciliation_back_on_after_the_revision() -> None:
    # In the order the platform allows: automated sync refuses a rollback, so
    # re-enabling it first would make the second step impossible.
    platform = a_platform_as_the_rollback_left_it()

    Scenario() \
        .given(descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: restore_deployment(descriptor, platform, SOME_MARK, SOME_ARGUS_ACCOUNT)) \
        .then(_it_was_asked_in_order(platform, "roll_back", "resume_sync"))


@pytest.mark.unit
def test_restoring_leaves_reconciliation_off_where_argus_found_it_off() -> None:
    # Turning it on because that is the usual arrangement would be Argus
    # starting something it did not stop.
    platform = a_platform_as_the_rollback_left_it()

    Scenario() \
        .given(descriptor := _a_descriptor(was_syncing_itself=False)) \
        .when(lambda: restore_deployment(descriptor, platform, SOME_MARK, SOME_ARGUS_ACCOUNT)) \
        .then(all_of(
            _the_sync_policy_was_not_touched(platform),
            _it_reports_restored(revision=True, automated_sync=True)
        ))


@pytest.mark.unit
def test_a_restore_that_only_managed_the_revision_says_so() -> None:
    # The half that is easy to lose. The deployment looks right and is
    # receiving nothing anybody ships to it.
    platform = a_platform_as_the_rollback_left_it()
    platform.resume_sync.side_effect = PlatformUnreachable(DONT_CARE_PLATFORM_WORDS)

    Scenario() \
        .given(descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: restore_deployment(descriptor, platform, SOME_MARK, SOME_ARGUS_ACCOUNT)) \
        .then(_it_reports_restored(revision=True, automated_sync=False))


@pytest.mark.unit
def test_a_restore_that_could_not_reach_the_platform_at_all_says_so() -> None:
    platform = a_platform_as_the_rollback_left_it()
    platform.roll_back.side_effect = PlatformUnreachable(DONT_CARE_PLATFORM_WORDS)
    platform.resume_sync.side_effect = PlatformUnreachable(DONT_CARE_PLATFORM_WORDS)

    Scenario() \
        .given(descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: restore_deployment(descriptor, platform, SOME_MARK, SOME_ARGUS_ACCOUNT)) \
        .then(_it_reports_restored(revision=False, automated_sync=False))


@pytest.mark.unit
def test_a_rollback_still_argus_s_is_put_back_and_said_to_be_nobody_else_s() -> None:
    # The newest entry is Argus's own, by its account and of the revision it
    # rolled back to, and the Deployment runs what that revision renders.
    platform = a_platform_as_the_rollback_left_it()

    Scenario() \
        .given(descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: restore_deployment(descriptor, platform, SOME_MARK, SOME_ARGUS_ACCOUNT)) \
        .then(all_of(
            _it_rolled_back_to(platform, THE_ENTRY_RUNNING),
            _it_reports_restored(revision=True, automated_sync=True),
            it_was_not_left_alone()
        ))


@pytest.mark.unit
def test_the_images_running_are_compared_with_those_of_the_revision_rolled_back_to() -> None:
    # What the platform renders for that revision, and not for any other: an
    # image compared with the wrong revision's would call Argus's own rollback
    # somebody else's, or somebody else's Argus's.
    platform = a_platform_as_the_rollback_left_it()

    Scenario() \
        .given(descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: restore_deployment(descriptor, platform, SOME_MARK, SOME_ARGUS_ACCOUNT)) \
        .then(_the_images_were_read_at(platform, THE_REVISION_BEFORE_IT))


@pytest.mark.unit
def test_a_deployment_already_back_on_its_revision_is_not_rolled_back_again() -> None:
    # Somebody - anybody - has already returned it to the revision it was on,
    # and it runs that revision's images. Nothing is written for the revision,
    # and it counts as put back; the sync Argus suspended is still Argus's to
    # resume.
    already_back = _a_deployment(THE_NEXT_ENTRY, THE_REVISION_RUNNING,
                                 initiated_by=SOME_PERSON)
    platform = a_platform_as_the_rollback_left_it(newest=already_back)

    Scenario() \
        .given(descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: restore_deployment(descriptor, platform, SOME_MARK, SOME_ARGUS_ACCOUNT)) \
        .then(all_of(
            _it_did_not_roll_back(platform),
            every_write_carried(platform, "resume_sync", SOME_MARK),
            _it_reports_restored(revision=True, automated_sync=True),
            it_was_not_left_alone()
        ))


@pytest.mark.unit
@pytest.mark.parametrize(
    "a_put_back_under_way",
    [
        pytest.param(SyncOperations(
            requested=RequestedSync(revision=THE_REVISION_RUNNING,
                                    initiated_by=SOME_ARGUS_ACCOUNT, made_by_argus=True),
            last_run=None
        ), id="asked-and-not-yet-run"),
        pytest.param(SyncOperations(
            # Kept beside the run while it runs, as the platform keeps it.
            requested=RequestedSync(revision=THE_REVISION_RUNNING,
                                    initiated_by=SOME_ARGUS_ACCOUNT, made_by_argus=True),
            last_run=SyncRun(revision=THE_REVISION_RUNNING, initiated_by=SOME_ARGUS_ACCOUNT,
                             made_by_argus=True,
                             started_at=AFTER_THE_PLAN, phase=SyncPhase.RUNNING)
        ), id="running")
    ]
)
def test_a_put_back_argus_already_asked_for_is_not_asked_again(
    a_put_back_under_way: SyncOperations
) -> None:
    # A restore asked again after its answer was lost: the platform has the sync
    # back to the revision Argus found, by Argus's account, and has not yet
    # written its entry - so the history still reads as Argus's rollback. Asked
    # again, the platform would refuse it as another operation in progress. The
    # revision counts as put back, and the sync Argus suspended is Argus's to
    # resume.
    platform = a_platform_as_the_rollback_left_it(operations=a_put_back_under_way)

    Scenario() \
        .given(descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: restore_deployment(descriptor, platform, SOME_MARK, SOME_ARGUS_ACCOUNT)) \
        .then(all_of(
            _it_did_not_roll_back(platform),
            every_write_carried(platform, "resume_sync", SOME_MARK),
            _it_reports_restored(revision=True, automated_sync=True)
        ))


@pytest.mark.unit
@pytest.mark.parametrize("phase", EVERY_WAY_SOMEBODY_STOPS_A_PUT_BACK)
def test_a_put_back_somebody_terminated_is_left_as_they_set_it(phase: SyncPhase) -> None:
    # Argus's own sync back to the revision it found, stopped by somebody - while
    # the platform still keeps its request, or once the run has finished. Not
    # already back: the revision is not put back, and resuming the sync would
    # have the platform re-apply git over the stop.
    platform = a_platform_as_the_rollback_left_it(operations=_a_run(
        phase, started_at=AFTER_THE_PLAN, revision=THE_REVISION_RUNNING
    ))

    Scenario() \
        .given(descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: restore_deployment(descriptor, platform, SOME_MARK, SOME_ARGUS_ACCOUNT)) \
        .then(all_of(
            _nothing_was_written(platform),
            it_was_left_because(THE_REVISION_RUNNING),
            the_suspension_is_said_to_stand(True)
        ))


@pytest.mark.unit
def test_a_restore_while_somebody_is_terminating_argus_s_rollback_leaves_it_as_they_set_it(
) -> None:
    # The rollback's own run being terminated: somebody is stopping Argus's
    # change, and a put-back asked beside them would overrule what they are
    # doing. Nothing written, the suspension said to stand.
    platform = _a_platform_terminating_this_rollback()

    Scenario() \
        .given(descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: restore_deployment(descriptor, platform, SOME_MARK, SOME_ARGUS_ACCOUNT)) \
        .then(all_of(
            _nothing_was_written(platform),
            it_was_left_because(THE_REVISION_BEFORE_IT),
            the_suspension_is_said_to_stand(True)
        ))


@pytest.mark.unit
def test_a_restore_is_not_asked_while_the_platform_runs_a_sync_of_its_own() -> None:
    # Nobody's change, and nothing a rollback can be asked beside: the put-back
    # cannot be made now, so it is answered as one that could not be - nothing
    # written, neither half back, nothing found - and goes to a person.
    platform = a_platform_as_the_rollback_left_it(operations=THE_PLATFORM_MID_SYNC)

    Scenario() \
        .given(descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: restore_deployment(descriptor, platform, SOME_MARK, SOME_ARGUS_ACCOUNT)) \
        .then(all_of(
            _nothing_was_written(platform),
            _it_reports_restored(revision=False, automated_sync=False),
            it_was_not_left_alone()
        ))


@pytest.mark.unit
def test_a_restore_is_not_asked_while_argus_s_own_rollback_is_still_being_run() -> None:
    # The withdrawal arrived before the platform finished the rollback itself.
    # Not somebody else's change - it is Argus's - and nothing a put-back can be
    # asked beside, so it is answered as one that could not be made and goes to
    # a person.
    # The history has no entry of the rollback yet: the platform writes it when
    # the sync finishes.
    platform = a_platform(syncing_itself=False, marked_by=THIS_CLAIM,
                          operations=SyncOperations(
                              requested=RequestedSync(revision=THE_REVISION_BEFORE_IT,
                                                      initiated_by=SOME_ARGUS_ACCOUNT,
                                                      made_by_argus=True),
                              last_run=None
                          ))

    Scenario() \
        .given(descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: restore_deployment(descriptor, platform, SOME_MARK, SOME_ARGUS_ACCOUNT)) \
        .then(all_of(
            _nothing_was_written(platform),
            _it_reports_restored(revision=False, automated_sync=False),
            it_was_not_left_alone()
        ))


@pytest.mark.unit
def test_a_sync_somebody_else_asked_for_still_being_run_is_left_to_them() -> None:
    # Somebody is deploying the application while Argus would put it back.
    # Rolling back beside them would be refused as another operation in
    # progress, and resuming sync would re-apply git over what they are doing.
    platform = a_platform_as_the_rollback_left_it(operations=SyncOperations(
        requested=RequestedSync(revision=A_REVISION_SOMEBODY_ELSE_DEPLOYED,
                                initiated_by=SOME_PERSON),
        last_run=None
    ))

    Scenario() \
        .given(descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: restore_deployment(descriptor, platform, SOME_MARK, SOME_ARGUS_ACCOUNT)) \
        .then(all_of(
            _nothing_was_written(platform),
            it_was_left_because(A_REVISION_SOMEBODY_ELSE_DEPLOYED, SOME_PERSON)
        ))


@pytest.mark.unit
def test_a_revision_somebody_deployed_since_is_left_as_they_set_it() -> None:
    # Rolling back to the entry Argus found would replace their deployment with
    # one nobody now wants, and resuming sync would have the platform re-apply
    # git over it - so neither is written, and what was found is said.
    somebody_s = _a_deployment(THE_NEXT_ENTRY, A_REVISION_SOMEBODY_ELSE_DEPLOYED,
                               initiated_by=SOME_PERSON)
    platform = a_platform_as_the_rollback_left_it(newest=somebody_s)

    Scenario() \
        .given(descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: restore_deployment(descriptor, platform, SOME_MARK, SOME_ARGUS_ACCOUNT)) \
        .then(all_of(
            _nothing_was_written(platform),
            it_was_left_because(A_REVISION_SOMEBODY_ELSE_DEPLOYED, SOME_PERSON)
        ))


@pytest.mark.unit
def test_the_revision_argus_rolled_back_to_deployed_again_by_somebody_else_is_theirs() -> None:
    # The same revision, and not Argus's entry: whoever deployed it made it
    # theirs, and their decision is not Argus's to roll away.
    somebody_s = _a_deployment(THE_NEXT_ENTRY, THE_REVISION_BEFORE_IT,
                               initiated_by=SOME_PERSON)
    platform = a_platform_as_the_rollback_left_it(newest=somebody_s)

    Scenario() \
        .given(descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: restore_deployment(descriptor, platform, SOME_MARK, SOME_ARGUS_ACCOUNT)) \
        .then(all_of(
            _nothing_was_written(platform),
            it_was_left_because(SOME_PERSON)
        ))


@pytest.mark.unit
def test_an_image_set_by_hand_since_is_left_as_it_was_set() -> None:
    # `kubectl set image` adds no history entry, so the newest entry is still
    # Argus's - and the Deployment runs something its revision never rendered.
    platform = a_platform_as_the_rollback_left_it(
        images_running={SOME_CONTAINER: AN_IMAGE_SET_BY_HAND}
    )

    Scenario() \
        .given(descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: restore_deployment(descriptor, platform, SOME_MARK, SOME_ARGUS_ACCOUNT)) \
        .then(all_of(
            _nothing_was_written(platform),
            it_was_left_because(AN_IMAGE_SET_BY_HAND)
        ))


@pytest.mark.unit
def test_a_deployment_back_on_its_revision_running_an_image_set_by_hand_is_left_as_set() -> None:
    # The newest entry is the revision Argus found, so the history reads as
    # already back - and the Deployment runs an image that revision never
    # rendered. Somebody rolled back and then set an image by hand, and
    # resuming sync would have the platform re-apply git over it.
    already_back = _a_deployment(THE_NEXT_ENTRY, THE_REVISION_RUNNING,
                                 initiated_by=SOME_PERSON)
    platform = a_platform_as_the_rollback_left_it(
        newest=already_back,
        images_running={SOME_CONTAINER: AN_IMAGE_SET_BY_HAND}
    )

    Scenario() \
        .given(descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: restore_deployment(descriptor, platform, SOME_MARK, SOME_ARGUS_ACCOUNT)) \
        .then(all_of(
            _nothing_was_written(platform),
            it_was_left_because(AN_IMAGE_SET_BY_HAND)
        ))


@pytest.mark.unit
def test_a_rollback_recorded_without_the_revision_it_went_to_is_not_written_over() -> None:
    # A row written before the descriptor said where the rollback went. Whose
    # the newest entry is cannot be asked without it, so the restore answers as
    # a read that never came back does: nothing written, neither half back,
    # nothing found.
    from_before = _a_descriptor(was_syncing_itself=True).model_copy(
        update={"rolled_back_to_revision": None}
    )
    platform = a_platform_as_the_rollback_left_it()

    Scenario() \
        .given(from_before) \
        .when(lambda: restore_deployment(from_before, platform, SOME_MARK, SOME_ARGUS_ACCOUNT)) \
        .then(all_of(
            _nothing_was_written(platform),
            _it_reports_restored(revision=False, automated_sync=False),
            it_was_not_left_alone()
        ))


@pytest.mark.unit
def test_a_rollback_put_back_with_no_account_to_look_for_is_not_written_over() -> None:
    # The account setting is empty where the credential is shared, and no
    # history entry is ever made by nobody - so Argus's own rollback would read
    # as somebody else's and be left standing. Whose the newest entry is cannot
    # be asked, so the restore answers as a read that never came back does.
    platform = a_platform_as_the_rollback_left_it()

    Scenario() \
        .given(descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: restore_deployment(descriptor, platform, SOME_MARK, NO_ACCOUNT)) \
        .then(all_of(
            _nothing_was_written(platform),
            _it_reports_restored(revision=False, automated_sync=False),
            it_was_not_left_alone()
        ))


@pytest.mark.unit
@pytest.mark.parametrize("a_platform_somebody_changed", EVERY_WAY_A_ROLLBACK_BECOMES_SOMEBODY_S)
@pytest.mark.parametrize(
    ("was_syncing_itself", "syncing_now", "still_suspended"),
    [
        pytest.param(True, False, True, id="argus-suspended-it-and-it-is-still-off"),
        pytest.param(True, True, False, id="somebody-turned-it-back-on"),
        pytest.param(False, False, False, id="it-was-off-before-argus-came")
    ]
)
def test_a_rollback_left_as_somebody_set_it_says_whether_argus_s_suspension_still_stands(
    a_platform_somebody_changed: Callable[[bool], Any],
    was_syncing_itself: bool, syncing_now: bool, still_suspended: bool
) -> None:
    # Read from the platform, because only it knows: a person who reverted in
    # git and turned sync back on has ended Argus's suspension themselves, and
    # one sync was off for before Argus came was never suspended by Argus.
    platform = a_platform_somebody_changed(syncing_now)

    Scenario() \
        .given(descriptor := _a_descriptor(was_syncing_itself=was_syncing_itself)) \
        .when(lambda: restore_deployment(descriptor, platform, SOME_MARK, SOME_ARGUS_ACCOUNT)) \
        .then(all_of(
            _nothing_was_written(platform),
            the_suspension_is_said_to_stand(still_suspended)
        ))


@pytest.mark.unit
@pytest.mark.parametrize("read", ["sync_operations_of", "deployments_of", "images_running",
                                  "images_at"])
def test_a_restore_that_could_not_read_whose_the_rollback_is_writes_nothing(read: str) -> None:
    # Writing on a reading that never came back is the blind put-back the check
    # exists to prevent - so neither half is written, neither is said to be
    # back, and nothing is said to have been found.
    platform = a_platform_as_the_rollback_left_it()
    getattr(platform, read).side_effect = PlatformUnreachable(DONT_CARE_PLATFORM_WORDS)

    Scenario() \
        .given(descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: restore_deployment(descriptor, platform, SOME_MARK, SOME_ARGUS_ACCOUNT)) \
        .then(all_of(
            _nothing_was_written(platform),
            _it_reports_restored(revision=False, automated_sync=False),
            it_was_not_left_alone()
        ))


@pytest.mark.unit
@pytest.mark.parametrize("a_platform_somebody_changed", EVERY_WAY_A_ROLLBACK_BECOMES_SOMEBODY_S)
def test_a_restore_that_could_not_read_whether_sync_is_back_on_writes_nothing(
    a_platform_somebody_changed: Callable[[bool], Any]
) -> None:
    # The last read, made only where the deployment is somebody's: without it
    # nobody can say whether Argus's suspension still stands, and the answer
    # says nothing it could not establish.
    dont_care_syncing_now = False
    platform = a_platform_somebody_changed(dont_care_syncing_now)
    platform.is_syncing_itself.side_effect = PlatformRefused(DONT_CARE_PLATFORM_WORDS)

    Scenario() \
        .given(descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: restore_deployment(descriptor, platform, SOME_MARK, SOME_ARGUS_ACCOUNT)) \
        .then(all_of(
            _nothing_was_written(platform),
            _it_reports_restored(revision=False, automated_sync=False),
            it_was_not_left_alone()
        ))


@pytest.mark.unit
def test_a_platform_unavailable_when_sync_is_suspended_is_reported_as_unreachable() -> None:
    # The suspension is the first thing a rollback changes, so a platform that
    # said it did not handle it has left the estate exactly as it found it.
    platform = a_platform(syncing_itself=True)
    platform.suspend_sync.side_effect = PlatformUnreachable(DONT_CARE_PLATFORM_WORDS,
                                                            known_not_applied=True)

    Scenario() \
        .given(planned := _a_plan(was_syncing_itself=True)) \
        .when(attempting(
            lambda: roll_back_deployment(planned, platform, SOME_MARK, SOME_ARGUS_ACCOUNT)
        )) \
        .then(_it_is_reported_as_an_unreachable_platform())


@pytest.mark.unit
def test_a_platform_that_died_before_a_rollback_that_changed_nothing_is_unreachable() -> None:
    # An application nobody was reconciling needs no suspension, so the rollback
    # request is the first write - and a platform that stopped answering before
    # it took nothing with it.
    platform = a_platform(syncing_itself=False)
    platform.roll_back.side_effect = PlatformUnreachable(
        DONT_CARE_PLATFORM_WORDS, known_not_applied=True
    )

    Scenario() \
        .given(planned := _a_plan(was_syncing_itself=False)) \
        .when(attempting(
            lambda: roll_back_deployment(planned, platform, SOME_MARK, SOME_ARGUS_ACCOUNT)
        )) \
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
    platform.roll_back.side_effect = PlatformUnreachable(
        DONT_CARE_PLATFORM_WORDS, known_not_applied=True
    )

    Scenario() \
        .given(planned := _a_plan(was_syncing_itself=True)) \
        .when(attempting(
            lambda: roll_back_deployment(planned, platform, SOME_MARK, SOME_ARGUS_ACCOUNT)
        )) \
        .then(all_of(
            _it_is_reported_as_an_unreachable_platform(),
            _it_says_what_it_left_behind(THE_SUSPENSION)
        ))


@pytest.mark.unit
def test_a_suspension_whose_answer_was_lost_is_not_said_to_have_changed_nothing() -> None:
    # The sync may be off by now, and nobody can say. Marked unreachable, the
    # walk would narrow onto an estate that may have moved.
    platform = a_platform(syncing_itself=True)
    platform.suspend_sync.side_effect = PlatformUnreachable(
        DONT_CARE_PLATFORM_WORDS, known_not_applied=False
    )

    Scenario() \
        .given(planned := _a_plan(was_syncing_itself=True)) \
        .when(attempting(
            lambda: roll_back_deployment(planned, platform, SOME_MARK, SOME_ARGUS_ACCOUNT)
        )) \
        .then(all_of(
            it_was_refused_as(RollbackRefused),
            it_is_marked_unreachable(False),
            what_it_left_is_known(False),
            it_left_behind(None)
        ))


@pytest.mark.unit
def test_a_rollback_rejected_after_sync_was_suspended_says_the_suspension_is_left() -> None:
    # A rollback the platform answered with a no, after the suspension landed:
    # the application sits un-reconciled, and the refusal is the only record
    # of it, so the suspension travels on it.
    platform = a_platform(syncing_itself=True)
    platform.roll_back.side_effect = PlatformRefused(DONT_CARE_PLATFORM_WORDS,
                                                     known_not_applied=True)

    Scenario() \
        .given(planned := _a_plan(was_syncing_itself=True)) \
        .when(attempting(
            lambda: roll_back_deployment(planned, platform, SOME_MARK, SOME_ARGUS_ACCOUNT)
        )) \
        .then(all_of(
            it_is_marked_unreachable(False),
            what_it_left_is_known(True),
            it_left_behind(THE_SUSPENSION)
        ))


@pytest.mark.unit
def test_a_rollback_whose_answer_was_lost_carries_the_suspension_and_no_more() -> None:
    # The revision may be moving this second. The suspension is carried,
    # because it is in place either way, and nothing is said to be all of it.
    platform = a_platform(syncing_itself=True)
    platform.roll_back.side_effect = PlatformUnreachable(
        DONT_CARE_PLATFORM_WORDS, known_not_applied=False
    )

    Scenario() \
        .given(planned := _a_plan(was_syncing_itself=True)) \
        .when(attempting(
            lambda: roll_back_deployment(planned, platform, SOME_MARK, SOME_ARGUS_ACCOUNT)
        )) \
        .then(all_of(
            it_is_marked_unreachable(False),
            what_it_left_is_known(False),
            it_left_behind(THE_SUSPENSION)
        ))


@pytest.mark.unit
def test_a_platform_that_answered_and_refused_is_not_reported_as_unreachable() -> None:
    # The distinction the change rests on. This platform is reachable and this
    # rollback is what it would not do, so the other actions through it are
    # still worth trying.
    platform = a_platform(syncing_itself=False)
    platform.roll_back.side_effect = PlatformRefused(DONT_CARE_PLATFORM_WORDS)

    Scenario() \
        .given(planned := _a_plan(was_syncing_itself=False)) \
        .when(attempting(
            lambda: roll_back_deployment(planned, platform, SOME_MARK, SOME_ARGUS_ACCOUNT)
        )) \
        .then(_it_is_not_reported_as_an_unreachable_platform())


@pytest.mark.unit
def test_a_rollback_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    # A change to production, and what it changed.
    platform = a_platform(syncing_itself=True)

    Scenario() \
        .given(
            calling(lambda: caplog.set_level(logging.INFO)),
            planned := _a_plan(was_syncing_itself=True)
        ) \
        .when(lambda: roll_back_deployment(planned, platform, SOME_MARK, SOME_ARGUS_ACCOUNT)) \
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
    platform.roll_back.side_effect = PlatformRefused(DONT_CARE_PLATFORM_WORDS)

    Scenario() \
        .given(planned := _a_plan(was_syncing_itself=True)) \
        .when(attempting(
            lambda: roll_back_deployment(planned, platform, SOME_MARK, SOME_ARGUS_ACCOUNT)
        )) \
        .then(
            one_record_was_logged(caplog, "write_mcp_server.rolling_back", logging.WARNING,
                                  "rollback refused",
                                  values={"application": SOME_APPLICATION,
                                          "sync_suspended": True})
        )


@pytest.mark.unit
def test_a_complete_restore_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    # A change to production as much as the action was.
    platform = a_platform_as_the_rollback_left_it()

    Scenario() \
        .given(
            calling(lambda: caplog.set_level(logging.INFO)),
            descriptor := _a_descriptor(was_syncing_itself=True)
        ) \
        .when(lambda: restore_deployment(descriptor, platform, SOME_MARK, SOME_ARGUS_ACCOUNT)) \
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
    platform = a_platform_as_the_rollback_left_it()
    platform.resume_sync.side_effect = PlatformUnreachable(DONT_CARE_PLATFORM_WORDS)

    Scenario() \
        .given(descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: restore_deployment(descriptor, platform, SOME_MARK, SOME_ARGUS_ACCOUNT)) \
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
    platform = a_platform_as_the_rollback_left_it()
    platform.resume_sync.side_effect = PlatformUnreachable(DONT_CARE_PLATFORM_WORDS)

    Scenario() \
        .given(descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: restore_deployment(descriptor, platform, SOME_MARK, SOME_ARGUS_ACCOUNT)) \
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
    """The plan for rolling the two deployments back: from the one running to
    the one before it - which is also the record a restore puts back from."""
    return DeploymentRollbackUndo(
        application=SOME_APPLICATION,
        was_on_history_id=THE_ENTRY_RUNNING,
        was_on_revision=THE_REVISION_RUNNING,
        rolled_back_to_revision=THE_REVISION_BEFORE_IT,
        rolled_back_to_history_id=THE_ENTRY_BEFORE_IT,
        was_syncing_itself=was_syncing_itself
    )


def _it_planned(
    expected: DeploymentRollbackUndo
) -> Assertion[Planned[DeploymentRollbackUndo]]:
    """Compared field by field, and every field that differs reported: a plan
    right about the entry and wrong about the sync rolls back the right
    revision and puts back the wrong switch."""
    def assertion(planned: Planned[DeploymentRollbackUndo]) -> bool:
        wanted = expected.model_dump()
        got = planned.descriptor.model_dump()
        wrong = {field: (value, got.get(field))
                 for field, value in wanted.items() if got.get(field) != value}

        if wrong:
            raise AssertionError(
                f"Expected the plan {wanted}, and {wrong} differed (expected, got)."
            )

        return True

    return assertion


def _it_is_dated(at: datetime) -> Assertion[Planned[DeploymentRollbackUndo]]:
    def assertion(planned: Planned[DeploymentRollbackUndo]) -> bool:
        if planned.since != at:
            raise AssertionError(
                f"Expected the plan dated [{at}], and it was dated [{planned.since}]."
            )

        return True

    return assertion


def _it_answered_with(expected: DeploymentRollbackUndo) -> Assertion[DeploymentRollbackUndo]:
    def assertion(descriptor: DeploymentRollbackUndo) -> bool:
        if descriptor != expected:
            raise AssertionError(
                f"Expected the rollback to answer with {expected!r}, and it "
                f"answered with {descriptor!r}."
            )

        return True

    return assertion


def _the_plan_records_sync_was(syncing: bool) -> Assertion[Planned[DeploymentRollbackUndo]]:
    def assertion(planned: Planned[DeploymentRollbackUndo]) -> bool:
        if planned.descriptor.was_syncing_itself is not syncing:
            raise AssertionError(
                f"Expected the plan to record reconciliation as [{syncing}], and it "
                f"recorded [{planned.descriptor.was_syncing_itself}]."
            )

        return True

    return assertion


def _no_write_was_asked(platform: Any) -> Assertion[object]:
    """None of the port's writes, whatever the act's answer - the reads are
    what a plan, or a rollback that found the platform moved, did ask."""
    def assertion(dont_care: object) -> bool:
        written = [write for write in EVERY_WRITE if getattr(platform, write).called]

        if written:
            raise AssertionError(
                f"Expected nothing written, and {written} were asked: "
                f"{platform.method_calls}"
            )

        return True

    return assertion


def _it_did_not_roll_back(platform: Any) -> Assertion[DeploymentRestored]:
    def assertion(dont_care: DeploymentRestored) -> bool:
        if platform.roll_back.called:
            raise AssertionError(
                f"Expected no rollback asked for, and the platform was asked "
                f"{platform.roll_back.call_args_list}."
            )

        return True

    return assertion


def _nothing_was_written(platform: Any) -> Assertion[DeploymentRestored]:
    """Neither the revision nor the sync policy - the reads are what a
    restore that left the deployment alone did ask."""
    def assertion(dont_care: DeploymentRestored) -> bool:
        written = [name for name, operation in (("the revision", platform.roll_back),
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


def _the_images_were_read_at(platform: Any, revision: str) -> Assertion[DeploymentRestored]:
    def assertion(dont_care: DeploymentRestored) -> bool:
        asked = [call.args for call in platform.images_at.call_args_list]

        if (SOME_APPLICATION, revision) not in asked:
            raise AssertionError(
                f"Expected the images of [{SOME_APPLICATION}] at [{revision}] read, and "
                f"the platform was asked {asked}."
            )

        return True

    return assertion


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


def _the_refusal_says_the_action_is_exhausted() -> Assertion[Exception | None]:
    """The refusal carries the marker the transport turns into a type - asserted
    against the marker rather than the sentence, which is allowed to change."""
    def assertion(refusal: Exception | None) -> bool:
        if refusal is None or EXHAUSTED_ACTION_MARKER not in str(refusal):
            raise AssertionError(
                f"Expected the refusal to carry [{EXHAUSTED_ACTION_MARKER}], so "
                f"that a caller can tell an exhausted action from a broken "
                f"platform, and it said [{refusal}]."
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


@pytest.mark.unit
def test_a_rollback_made_is_answered_dated_by_the_platform_s_answer_to_it() -> None:
    # What the way back is dated by, on the platform's own clock: a later look
    # at its history asks what landed since Argus wrote, and a moment on any
    # other clock can fall the wrong side of an entry.
    platform = a_platform(syncing_itself=True)
    platform.roll_back.return_value = THE_MOMENT_THE_PLATFORM_ANSWERED

    Scenario() \
        .given(planned := _a_plan(was_syncing_itself=True)) \
        .when(lambda: roll_back_deployment(planned, platform, SOME_MARK, SOME_ARGUS_ACCOUNT)) \
        .then(
            _it_answered_with(_dated(planned.descriptor, THE_MOMENT_THE_PLATFORM_ANSWERED))
        )


@pytest.mark.unit
def test_a_rollback_whose_answer_said_no_moment_is_answered_undated() -> None:
    # The rollback landed, and nobody can say when by the platform's clock:
    # absent says so, and a reader takes it as unknown, never as a time.
    platform = a_platform(syncing_itself=True)
    platform.roll_back.return_value = None

    Scenario() \
        .given(planned := _a_plan(was_syncing_itself=True)) \
        .when(lambda: roll_back_deployment(planned, platform, SOME_MARK, SOME_ARGUS_ACCOUNT)) \
        .then(
            _it_answered_with(_dated(planned.descriptor, None))
        )


def _dated(descriptor: DeploymentRollbackUndo, at: datetime | None) -> DeploymentRollbackUndo:
    """`descriptor` as a rollback made at `at` answers with it."""
    return descriptor.model_copy(update={"written_at": at})


# Argus's own rollback, asked of the platform and not yet in its history: asked
# and not yet run, or running - with its request kept beside the run.
EVERY_WAY_ARGUS_S_ROLLBACK_IS_UNDER_WAY = [
    pytest.param(SyncOperations(
        requested=RequestedSync(revision=THE_REVISION_BEFORE_IT,
                                initiated_by=SOME_ARGUS_ACCOUNT, made_by_argus=True),
        last_run=None
    ), id="asked-and-not-yet-run"),
    pytest.param(_a_run(SyncPhase.RUNNING, started_at=AFTER_THE_PLAN), id="running")
]

# Every read the check on where a rollback stands makes - the one the put-back
# and the resumed walk share. One that never comes back establishes nothing.
EVERY_READ_THE_CHECK_MAKES = ["sync_operations_of", "deployments_of", "images_running",
                              "images_at"]
# And the resumed walk's, which reads the sync switch beside it: a rollback the
# platform reconciles again is no longer where Argus left it.
EVERY_READ_STILL_ARGUS_S_MAKES = [*EVERY_READ_THE_CHECK_MAKES, "is_syncing_itself"]


def _a_platform_mid_way_through_argus_s_rollback(operations: SyncOperations) -> Any:
    """A platform Argus's rollback was asked of and has not finished: its sync
    suspended under this claim's mark, the history with no entry of the
    rollback yet - the platform writes it when the sync finishes - and the
    Deployment still running what the revision it was on renders."""
    platform = a_platform(syncing_itself=False, marked_by=THIS_CLAIM, operations=operations)
    platform.images_running.return_value = _the_images_rendered_for(THE_REVISION_RUNNING)
    platform.images_at.side_effect = (
        lambda dont_care_application, revision: _the_images_rendered_for(revision)
    )

    return platform


@pytest.mark.unit
def test_a_rollback_whose_newest_entry_is_argus_s_and_runs_its_images_stands_as_argus_s(
) -> None:
    platform = a_platform_as_the_rollback_left_it()

    Scenario() \
        .given(a_descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: what_became_of_the_rollback(a_descriptor, platform)) \
        .then(_it_stands(RollbackStanding.STILL_ARGUS_S))


@pytest.mark.unit
def test_a_deployment_back_on_the_revision_argus_found_stands_as_already_back() -> None:
    # Whoever put it there, running what that revision renders.
    platform = a_platform_as_the_rollback_left_it(
        newest=_a_deployment(THE_NEXT_ENTRY, THE_REVISION_RUNNING, initiated_by=SOME_PERSON)
    )

    Scenario() \
        .given(a_descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: what_became_of_the_rollback(a_descriptor, platform)) \
        .then(_it_stands(RollbackStanding.ALREADY_BACK))


@pytest.mark.unit
def test_the_platform_in_a_sync_of_its_own_stands_as_mid_sync() -> None:
    platform = a_platform_as_the_rollback_left_it(operations=THE_PLATFORM_MID_SYNC)

    Scenario() \
        .given(a_descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: what_became_of_the_rollback(a_descriptor, platform)) \
        .then(_it_stands(RollbackStanding.MID_SYNC))


@pytest.mark.unit
@pytest.mark.parametrize("under_way", EVERY_WAY_ARGUS_S_ROLLBACK_IS_UNDER_WAY)
def test_argus_s_own_rollback_not_yet_in_the_history_stands_as_under_way(
    under_way: SyncOperations
) -> None:
    # Not the platform's own sync, and not the deployment already back: the
    # history has no entry of it yet, so the revision it reads is the one the
    # rollback is going away from - and the images too, while it rolls out.
    platform = _a_platform_mid_way_through_argus_s_rollback(under_way)

    Scenario() \
        .given(a_descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: what_became_of_the_rollback(a_descriptor, platform)) \
        .then(_it_stands(RollbackStanding.UNDER_WAY))


@pytest.mark.unit
def test_argus_s_own_rollback_somebody_is_terminating_is_said_as_what_was_found() -> None:
    # The platform keeps this rollback's request while its run is terminated,
    # so the request alone reads as Argus's change on its way - but only
    # somebody terminates a sync, as the write reads it. The run is read before
    # the request.
    platform = _a_platform_terminating_this_rollback()

    Scenario() \
        .given(a_descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: what_became_of_the_rollback(a_descriptor, platform)) \
        .then(_it_was_found_somebody_s(THE_REVISION_BEFORE_IT))


@pytest.mark.unit
def test_argus_s_own_rollback_somebody_terminated_is_said_as_what_was_found() -> None:
    # No entry of the rollback, and the deployment still on the revision Argus
    # found - which alone reads as already back. The run says somebody stopped
    # it, as the write reads it.
    platform = _a_platform_where_somebody_terminated_this_rollback()

    Scenario() \
        .given(a_descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: what_became_of_the_rollback(a_descriptor, platform)) \
        .then(_it_was_found_somebody_s(THE_REVISION_BEFORE_IT))


@pytest.mark.unit
def test_argus_s_rollback_asked_again_after_a_terminated_run_stands_as_under_way() -> None:
    # The platform clears a request once its run ends, so one standing beside an
    # ended run was asked after it: Argus's rollback, asked again since somebody
    # terminated the last run of it. The request is the newer, and says the
    # rollback is on its way - not stopped.
    platform = _a_platform_mid_way_through_argus_s_rollback(SyncOperations(
        requested=RequestedSync(revision=THE_REVISION_BEFORE_IT,
                                initiated_by=SOME_ARGUS_ACCOUNT, made_by_argus=True),
        last_run=SyncRun(revision=THE_REVISION_BEFORE_IT, initiated_by=SOME_ARGUS_ACCOUNT,
                         made_by_argus=True,
                         started_at=AFTER_THE_PLAN, phase=SyncPhase.TERMINATED)
    ))

    Scenario() \
        .given(a_descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: what_became_of_the_rollback(a_descriptor, platform)) \
        .then(_it_stands(RollbackStanding.UNDER_WAY))


@pytest.mark.unit
@pytest.mark.parametrize("phase", EVERY_WAY_SOMEBODY_STOPS_A_PUT_BACK)
def test_a_put_back_somebody_terminated_is_said_as_what_was_found(phase: SyncPhase) -> None:
    # Argus's own sync back to the revision it found, stopped by somebody: not
    # the put-back whose answer was lost, and not already back. The run is read
    # before the request the platform keeps beside it.
    platform = a_platform_as_the_rollback_left_it(operations=_a_run(
        phase, started_at=AFTER_THE_PLAN, revision=THE_REVISION_RUNNING
    ))

    Scenario() \
        .given(a_descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: what_became_of_the_rollback(a_descriptor, platform)) \
        .then(_it_was_found_somebody_s(THE_REVISION_RUNNING))


@pytest.mark.unit
def test_a_revision_somebody_deployed_since_is_said_as_what_was_found() -> None:
    platform = a_platform_as_the_rollback_left_it(
        newest=_a_deployment(THE_NEXT_ENTRY, A_REVISION_SOMEBODY_ELSE_DEPLOYED,
                             initiated_by=SOME_PERSON)
    )

    Scenario() \
        .given(a_descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: what_became_of_the_rollback(a_descriptor, platform)) \
        .then(_it_was_found_somebody_s(A_REVISION_SOMEBODY_ELSE_DEPLOYED, SOME_PERSON))


@pytest.mark.unit
def test_images_set_by_hand_on_argus_s_entry_are_said_as_what_was_found() -> None:
    # A `kubectl set image` leaves no entry in the history, and changes exactly
    # the images.
    platform = a_platform_as_the_rollback_left_it(
        images_running={SOME_CONTAINER: AN_IMAGE_SET_BY_HAND}
    )

    Scenario() \
        .given(a_descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: what_became_of_the_rollback(a_descriptor, platform)) \
        .then(_it_was_found_somebody_s(AN_IMAGE_SET_BY_HAND))


@pytest.mark.unit
def test_a_sync_somebody_else_asked_for_still_being_run_is_said_as_what_was_found() -> None:
    platform = a_platform_as_the_rollback_left_it(operations=SyncOperations(
        requested=RequestedSync(revision=A_REVISION_SOMEBODY_ELSE_DEPLOYED,
                                initiated_by=SOME_PERSON),
        last_run=None
    ))

    Scenario() \
        .given(a_descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: what_became_of_the_rollback(a_descriptor, platform)) \
        .then(_it_was_found_somebody_s(A_REVISION_SOMEBODY_ELSE_DEPLOYED, SOME_PERSON))


@pytest.mark.unit
@pytest.mark.parametrize("read", EVERY_READ_THE_CHECK_MAKES)
def test_the_check_raises_where_a_read_never_came_back(read: str) -> None:
    # Raised as the platform raised it, so whoever asked writes nothing on it -
    # and says nothing it cannot establish.
    platform = a_platform_as_the_rollback_left_it()
    getattr(platform, read).side_effect = PlatformUnreachable(DONT_CARE_PLATFORM_WORDS)

    Scenario() \
        .given(a_descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(attempting(lambda: what_became_of_the_rollback(a_descriptor, platform))) \
        .then(an_error_was_raised(PlatformUnreachable))


@pytest.mark.unit
@pytest.mark.parametrize("under_way", EVERY_WAY_ARGUS_S_ROLLBACK_IS_UNDER_WAY)
def test_a_restore_while_argus_s_own_rollback_is_under_way_writes_nothing(
    under_way: SyncOperations
) -> None:
    # A pin that the lift keeps what the restore did: the withdrawal arrived
    # while the platform still had Argus's rollback to finish, and nothing a
    # put-back can be asked beside - so it is answered as one that could not be
    # made, and goes to a person, whether the check calls it under way or mid
    # sync.
    platform = _a_platform_mid_way_through_argus_s_rollback(under_way)

    Scenario() \
        .given(a_descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: restore_deployment(a_descriptor, platform, SOME_MARK, SOME_ARGUS_ACCOUNT)) \
        .then(all_of(
            _nothing_was_written(platform),
            _it_reports_restored(revision=False, automated_sync=False),
            it_was_not_left_alone()
        ))


@pytest.mark.unit
@pytest.mark.parametrize("was_syncing_itself", [True, False],
                         ids=["argus-suspended-the-sync", "the-sync-was-already-off"])
def test_a_rollback_as_argus_left_it_is_still_argus_s(was_syncing_itself: bool) -> None:
    # Argus's entry, running its images, and the platform not reconciling the
    # application - suspended by the rollback, or off as it was found.
    platform = a_platform_as_the_rollback_left_it()

    Scenario() \
        .given(a_descriptor := _a_descriptor(was_syncing_itself=was_syncing_itself)) \
        .when(lambda: still_argus_s(a_descriptor, platform, SOME_ARGUS_ACCOUNT)) \
        .then(it_is_still_argus_s())


@pytest.mark.unit
def test_whose_an_entry_is_is_the_platform_s_to_say_whatever_case_names_the_account() -> None:
    # The entry names Argus's account in another case than the setting does, and
    # the platform's adapter says it is Argus's: the write reads it as the read
    # tier does, rather than by a rule of its own that would make it somebody's.
    platform = a_platform_as_the_rollback_left_it(
        newest=_a_deployment(THE_NEXT_ENTRY, THE_REVISION_BEFORE_IT,
                             initiated_by=SOME_ARGUS_ACCOUNT.upper(), made_by_argus=True)
    )

    Scenario() \
        .given(a_descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: still_argus_s(a_descriptor, platform, SOME_ARGUS_ACCOUNT)) \
        .then(it_is_still_argus_s())


@pytest.mark.unit
@pytest.mark.parametrize("was_syncing_itself", [True, False],
                         ids=["somebody-resumed-what-argus-suspended",
                              "somebody-turned-on-a-sync-found-off"])
def test_a_rollback_the_platform_reconciles_again_is_a_change_since(
    was_syncing_itself: bool
) -> None:
    # Argus's entry is still the newest, and the platform is reconciling the
    # application: it re-applies git at its next pass, so the rollback is not
    # Argus's to watch any more - as the write, and every patch kind, read it.
    platform = a_platform_as_the_rollback_left_it(syncing_itself=True)

    Scenario() \
        .given(a_descriptor := _a_descriptor(was_syncing_itself=was_syncing_itself)) \
        .when(lambda: still_argus_s(a_descriptor, platform, SOME_ARGUS_ACCOUNT)) \
        .then(it_was_changed_since())


@pytest.mark.unit
def test_argus_s_own_rollback_somebody_is_terminating_is_a_change_since() -> None:
    # Its request still kept, and its run being terminated - by somebody, or by
    # the platform's own sync timeout where one is set: what is left of the
    # rollback is not Argus's to watch.
    platform = _a_platform_terminating_this_rollback()

    Scenario() \
        .given(a_descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: still_argus_s(a_descriptor, platform, SOME_ARGUS_ACCOUNT)) \
        .then(it_was_changed_since())


@pytest.mark.unit
def test_argus_s_own_rollback_somebody_terminated_is_somebody_s_change_since() -> None:
    # Not a run that failed of itself: terminated, by somebody or by the
    # platform's own sync timeout where one is set. A change since, said as what
    # was found, and not as the rollback's run having failed.
    platform = _a_platform_where_somebody_terminated_this_rollback()

    Scenario() \
        .given(a_descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: still_argus_s(a_descriptor, platform, SOME_ARGUS_ACCOUNT)) \
        .then(all_of(
            it_was_changed_since(f"[{THE_REVISION_BEFORE_IT}]"),
            what_was_found_does_not_say(THE_RUN_FAILED)
        ))


@pytest.mark.unit
def test_a_rollback_whose_newest_entry_is_argus_s_at_another_revision_is_nobody_s_to_say(
) -> None:
    # Argus's own account deployed a revision this rollback never named: some
    # other walk's doing, or a person's under Argus's account. Not a change of
    # somebody else's since - and not this rollback either.
    platform = a_platform_as_the_rollback_left_it(
        newest=_a_deployment(THE_NEXT_ENTRY, AN_OLDER_REVISION, initiated_by=SOME_ARGUS_ACCOUNT,
                             made_by_argus=True)
    )

    Scenario() \
        .given(a_descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: still_argus_s(a_descriptor, platform, SOME_ARGUS_ACCOUNT)) \
        .then(nobody_can_say(ARGUS_S_ACCOUNT_ELSEWHERE, f"[{AN_OLDER_REVISION}]"))


@pytest.mark.unit
@pytest.mark.parametrize("under_way", EVERY_WAY_ARGUS_S_ROLLBACK_IS_UNDER_WAY)
def test_argus_s_own_rollback_still_under_way_is_still_argus_s(
    under_way: SyncOperations
) -> None:
    # The forward sync of Argus's that the dead worker asked for, still being
    # run: Argus's change on its way, to be watched - whose arrival the watch
    # waits on - and not somebody's.
    platform = _a_platform_mid_way_through_argus_s_rollback(under_way)

    Scenario() \
        .given(a_descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: still_argus_s(a_descriptor, platform, SOME_ARGUS_ACCOUNT)) \
        .then(it_is_still_argus_s())


@pytest.mark.unit
def test_a_deployment_already_back_where_argus_found_it_is_a_change_since() -> None:
    # Somebody put it back: there is no rollback of Argus's left to watch, and
    # what was found says the revision it is back on.
    platform = a_platform_as_the_rollback_left_it(
        newest=_a_deployment(THE_NEXT_ENTRY, THE_REVISION_RUNNING, initiated_by=SOME_PERSON)
    )

    Scenario() \
        .given(a_descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: still_argus_s(a_descriptor, platform, SOME_ARGUS_ACCOUNT)) \
        .then(it_was_changed_since(f"[{THE_REVISION_RUNNING}]"))


@pytest.mark.unit
@pytest.mark.parametrize("a_platform_somebody_changed", EVERY_WAY_A_ROLLBACK_BECOMES_SOMEBODY_S)
@pytest.mark.parametrize("syncing_now", [True, False],
                         ids=["syncing-again", "still-suspended"])
def test_a_rollback_somebody_changed_since_is_a_change_since(
    a_platform_somebody_changed: Callable[[bool], Any], syncing_now: bool
) -> None:
    platform = a_platform_somebody_changed(syncing_now)

    Scenario() \
        .given(a_descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: still_argus_s(a_descriptor, platform, SOME_ARGUS_ACCOUNT)) \
        .then(it_was_changed_since())


@pytest.mark.unit
def test_a_rollback_while_the_platform_runs_a_sync_of_its_own_is_a_change_since() -> None:
    # A sync of its own runs only where the platform reconciles the
    # application again: it re-applies git at this pass, so the rollback is not
    # Argus's to watch any more, whatever this sync lands.
    platform = a_platform_as_the_rollback_left_it(operations=THE_PLATFORM_MID_SYNC,
                                                  syncing_itself=True)

    Scenario() \
        .given(a_descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: still_argus_s(a_descriptor, platform, SOME_ARGUS_ACCOUNT)) \
        .then(it_was_changed_since())


@pytest.mark.unit
@pytest.mark.parametrize("read", EVERY_READ_STILL_ARGUS_S_MAKES)
def test_a_rollback_whose_platform_could_not_be_read_is_nobody_s_to_say(read: str) -> None:
    # Not "changed since": a read that never came back found nothing.
    platform = a_platform_as_the_rollback_left_it()
    getattr(platform, read).side_effect = PlatformUnreachable(DONT_CARE_PLATFORM_WORDS)

    Scenario() \
        .given(a_descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: still_argus_s(a_descriptor, platform, SOME_ARGUS_ACCOUNT)) \
        .then(nobody_can_say())


@pytest.mark.unit
def test_a_rollback_recorded_without_the_revision_it_went_to_is_nobody_s_to_say() -> None:
    # Whether the newest entry is Argus's rollback cannot be asked without the
    # revision it rolled back to.
    platform = a_platform_as_the_rollback_left_it()

    Scenario() \
        .given(a_descriptor := _a_descriptor(was_syncing_itself=True).model_copy(
            update={"rolled_back_to_revision": None})) \
        .when(lambda: still_argus_s(a_descriptor, platform, SOME_ARGUS_ACCOUNT)) \
        .then(nobody_can_say())


@pytest.mark.unit
def test_a_rollback_with_no_account_to_look_for_is_nobody_s_to_say() -> None:
    # No history entry is ever made by nobody, so with no account of Argus's to
    # look for, its own rollback would read as somebody else's.
    platform = a_platform_as_the_rollback_left_it()

    Scenario() \
        .given(a_descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: still_argus_s(a_descriptor, platform, NO_ACCOUNT)) \
        .then(nobody_can_say())


@pytest.mark.unit
@pytest.mark.parametrize(
    "a_platform_found",
    [
        pytest.param(lambda: a_platform_as_the_rollback_left_it(), id="still-argus-s"),
        pytest.param(lambda: a_platform_as_the_rollback_left_it(
            newest=_a_deployment(THE_NEXT_ENTRY, A_REVISION_SOMEBODY_ELSE_DEPLOYED,
                                 initiated_by=SOME_PERSON)
        ), id="changed-since"),
        pytest.param(lambda: a_platform_as_the_rollback_left_it(
            operations=THE_PLATFORM_MID_SYNC
        ), id="mid-sync")
    ]
)
def test_asking_whether_a_rollback_is_still_argus_s_writes_nothing(
    a_platform_found: Callable[[], Any]
) -> None:
    # A read, whatever it finds: a walk asking it has decided nothing yet.
    platform = a_platform_found()

    Scenario() \
        .given(a_descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: still_argus_s(a_descriptor, platform, SOME_ARGUS_ACCOUNT)) \
        .then(_no_write_was_asked(platform))


def _it_stands(expected: RollbackStanding) -> Assertion[RollbackStanding | str]:
    def assertion(standing: RollbackStanding | str) -> bool:
        if standing is not expected:
            raise AssertionError(f"Expected the rollback to stand [{expected}], got [{standing}].")

        return True

    return assertion


def _it_was_found_somebody_s(*mentioning: str) -> Assertion[RollbackStanding | str]:
    """Somebody's change since, said - naming each of `mentioning`."""
    def assertion(standing: RollbackStanding | str) -> bool:
        if not isinstance(standing, str):
            raise AssertionError(
                f"Expected the rollback found somebody's change since, got [{standing}]."
            )

        missing = [each for each in mentioning if each not in standing]

        if missing:
            raise AssertionError(
                f"Expected what was found to name {list(mentioning)}, got [{standing}]."
            )

        return True

    return assertion


@pytest.mark.unit
def test_argus_s_sync_to_another_revision_stands_as_mid_sync() -> None:
    # A sync of Argus's own, to neither revision this rollback names: not this
    # rollback under way, and not its put-back - nothing that can be asked
    # beside.
    platform = _a_platform_mid_way_through_argus_s_rollback(SyncOperations(
        requested=RequestedSync(revision=AN_OLDER_REVISION, initiated_by=SOME_ARGUS_ACCOUNT,
                                made_by_argus=True),
        last_run=None
    ))

    Scenario() \
        .given(a_descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: what_became_of_the_rollback(a_descriptor, platform)) \
        .then(_it_stands(RollbackStanding.MID_SYNC))


@pytest.mark.unit
def test_argus_s_sync_to_another_revision_is_nobody_s_to_say() -> None:
    # Argus's own account, syncing a revision this claim's rollback never
    # named: some other walk's doing, or a person's under Argus's account - and
    # whatever it lands is not known yet.
    platform = _a_platform_mid_way_through_argus_s_rollback(SyncOperations(
        requested=RequestedSync(revision=AN_OLDER_REVISION, initiated_by=SOME_ARGUS_ACCOUNT,
                                made_by_argus=True),
        last_run=None
    ))

    Scenario() \
        .given(a_descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: still_argus_s(a_descriptor, platform, SOME_ARGUS_ACCOUNT)) \
        .then(nobody_can_say())


@pytest.mark.unit
@pytest.mark.parametrize("phase", EVERY_WAY_A_RUN_FAILS_OF_ITSELF)
def test_a_rollback_whose_run_failed_is_a_change_since_saying_so(phase: SyncPhase) -> None:
    # The row says the rollback was performed, and the platform's last run of it
    # failed of itself: no entry of it, the deployment still where it was. There
    # is no change of Argus's to watch - and what was found says why, rather than
    # reading as somebody having put it back.
    platform = _a_platform_mid_way_through_argus_s_rollback(SyncOperations(
        requested=None,
        last_run=SyncRun(revision=THE_REVISION_BEFORE_IT, initiated_by=SOME_ARGUS_ACCOUNT,
                         made_by_argus=True,
                         started_at=AFTER_THE_PLAN, phase=phase)
    ))

    Scenario() \
        .given(a_descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: still_argus_s(a_descriptor, platform, SOME_ARGUS_ACCOUNT)) \
        .then(it_was_changed_since(THE_RUN_FAILED))


@pytest.mark.unit
@pytest.mark.parametrize(
    "operations",
    [
        pytest.param(NO_SYNC_ASKED_OR_RUN, id="no-run-on-record"),
        pytest.param(_a_run(SyncPhase.SUCCEEDED, started_at=A_RUN_STARTED_BEFORE_ITS_ENTRY),
                     id="its-run-started-before-its-entry")
    ]
)
def test_a_rollback_argus_made_since_the_plan_is_found_made_and_dated_by_its_entry(
    operations: SyncOperations
) -> None:
    # The entry is the platform's record of the change landing; a run it has
    # finished started earlier, and is not the moment the change was made.
    platform = a_platform(history=[*_two_deployments(), _argus_s_rollback_since_the_plan()],
                          syncing_itself=False, marked_by=THIS_CLAIM, operations=operations)

    Scenario() \
        .given(planned := _a_plan(was_syncing_itself=True)) \
        .when(lambda: whether_it_was_made(planned, platform, THIS_CLAIM, SOME_ARGUS_ACCOUNT)) \
        .then(all_of(
            it_was_made(_dated(planned.descriptor, AFTER_THE_PLAN), made_at=AFTER_THE_PLAN),
            _no_write_was_asked(platform)
        ))


@pytest.mark.unit
@pytest.mark.parametrize("phase", [SyncPhase.RUNNING, SyncPhase.SUCCEEDED])
def test_a_rollback_argus_s_run_started_since_the_plan_is_found_made_and_dated_by_its_start(
    phase: SyncPhase
) -> None:
    # No entry yet - the platform writes it once the run finishes - so the run's
    # own start is the moment.
    platform = a_platform(syncing_itself=False, marked_by=THIS_CLAIM,
                          operations=_a_run(phase, started_at=AFTER_THE_PLAN))

    Scenario() \
        .given(planned := _a_plan(was_syncing_itself=True)) \
        .when(lambda: whether_it_was_made(planned, platform, THIS_CLAIM, SOME_ARGUS_ACCOUNT)) \
        .then(all_of(
            it_was_made(_dated(planned.descriptor, AFTER_THE_PLAN), made_at=AFTER_THE_PLAN),
            _no_write_was_asked(platform)
        ))


@pytest.mark.unit
def test_a_rollback_argus_asked_for_that_has_not_started_is_found_made_with_no_moment() -> None:
    # Taken by the platform and not yet run: made - asked again, it would be
    # refused as another operation in progress - and nothing yet says when, so
    # the walk dates it by its own claim rather than by a moment made up here.
    no_moment = None
    platform = a_platform(syncing_itself=False, marked_by=THIS_CLAIM,
                          operations=SyncOperations(
                              requested=RequestedSync(revision=THE_REVISION_BEFORE_IT,
                                                      initiated_by=SOME_ARGUS_ACCOUNT,
                                                      made_by_argus=True),
                              last_run=None
                          ))

    Scenario() \
        .given(planned := _a_plan(was_syncing_itself=True)) \
        .when(lambda: whether_it_was_made(planned, platform, THIS_CLAIM, SOME_ARGUS_ACCOUNT)) \
        .then(all_of(
            it_was_made(planned.descriptor, made_at=no_moment),
            _no_write_was_asked(platform)
        ))


@pytest.mark.unit
def test_a_rollback_nothing_of_which_landed_has_nothing_landed_and_nothing_left() -> None:
    # Running the revision the plan found, syncing itself as the plan found it,
    # and nothing of this rollback's in the history or under way: the write is
    # still to make, and nothing of this claim's is out there.
    no_suspension = None
    platform = a_platform(syncing_itself=True)

    Scenario() \
        .given(planned := _a_plan(was_syncing_itself=True)) \
        .when(lambda: whether_it_was_made(planned, platform, THIS_CLAIM, SOME_ARGUS_ACCOUNT)) \
        .then(all_of(
            nothing_landed(left_behind=no_suspension),
            _no_write_was_asked(platform)
        ))


@pytest.mark.unit
def test_a_rollback_planned_with_sync_off_nothing_of_which_landed_leaves_nothing() -> None:
    # The plan found the sync off, so the rollback suspends nothing: still off
    # and under no mark, there is nothing of this claim's out there to carry.
    no_suspension = None
    platform = a_platform(syncing_itself=False)

    Scenario() \
        .given(planned := _a_plan(was_syncing_itself=False)) \
        .when(lambda: whether_it_was_made(planned, platform, THIS_CLAIM, SOME_ARGUS_ACCOUNT)) \
        .then(all_of(
            nothing_landed(left_behind=no_suspension),
            _no_write_was_asked(platform)
        ))


@pytest.mark.unit
def test_a_rollback_whose_suspension_alone_landed_has_nothing_landed_carrying_it() -> None:
    # The suspension before the rollback landed under this claim's mark, and
    # the rollback did not: the write is still to make - and the answer carries
    # the plan, so a walk stopped before it writes still has what puts the
    # suspension back.
    platform = a_platform(syncing_itself=False, marked_by=THIS_CLAIM)

    Scenario() \
        .given(planned := _a_plan(was_syncing_itself=True)) \
        .when(lambda: whether_it_was_made(planned, platform, THIS_CLAIM, SOME_ARGUS_ACCOUNT)) \
        .then(all_of(
            nothing_landed(left_behind=planned.descriptor),
            _no_write_was_asked(platform)
        ))


@pytest.mark.unit
@pytest.mark.parametrize("phase", EVERY_WAY_A_RUN_FAILS_OF_ITSELF)
def test_a_rollback_whose_run_failed_of_itself_has_nothing_landed_carrying_the_suspension(
    phase: SyncPhase
) -> None:
    # A run of this rollback that failed of itself made nothing: the write is
    # still to make, as the write itself asks it again - and the suspension
    # under this claim's mark is carried as it stands.
    platform = a_platform(syncing_itself=False, marked_by=THIS_CLAIM,
                          operations=_a_run(phase, started_at=AFTER_THE_PLAN))

    Scenario() \
        .given(planned := _a_plan(was_syncing_itself=True)) \
        .when(lambda: whether_it_was_made(planned, platform, THIS_CLAIM, SOME_ARGUS_ACCOUNT)) \
        .then(all_of(
            nothing_landed(left_behind=planned.descriptor),
            _no_write_was_asked(platform)
        ))


@pytest.mark.unit
@pytest.mark.parametrize(
    "a_platform_changed_since",
    [
        pytest.param(lambda: a_platform(
            history=[*_two_deployments(),
                     _a_deployment(THE_NEXT_ENTRY, A_REVISION_SOMEBODY_ELSE_DEPLOYED,
                                   deployed_at=AFTER_THE_PLAN, initiated_by=SOME_PERSON)],
            syncing_itself=False, marked_by=THIS_CLAIM
        ), id="a-revision-somebody-deployed-since"),
        pytest.param(lambda: a_platform(
            history=[*_two_deployments(), _argus_s_rollback_since_the_plan(),
                     _a_deployment(THE_ENTRY_AFTER_THAT, THE_REVISION_RUNNING,
                                   deployed_at=AFTER_THE_PLAN, initiated_by=SOME_PERSON)],
            syncing_itself=False, marked_by=THIS_CLAIM
        ), id="argus-s-rollback-undone-by-somebody"),
        pytest.param(lambda: a_platform(syncing_itself=False, marked_by=ANOTHER_CLAIM),
                     id="a-sync-suspended-under-another-claim"),
        pytest.param(lambda: a_platform(syncing_itself=True, marked_by=THIS_CLAIM),
                     id="a-sync-somebody-resumed"),
        pytest.param(lambda: _a_platform_terminating_this_rollback(),
                     id="this-rollback-s-run-being-terminated"),
        pytest.param(lambda: _a_platform_where_somebody_terminated_this_rollback(),
                     id="this-rollback-s-run-terminated")
    ]
)
def test_a_rollback_changed_since_its_plan_is_refused_as_the_write_refuses_it(
    a_platform_changed_since: Callable[[], Any]
) -> None:
    # The same estate, the same answer: changed since, saying whether this
    # claim's rollback landed, and leaving behind what the write would.
    platform = a_platform_changed_since()

    Scenario() \
        .given(planned := _a_plan(was_syncing_itself=True)) \
        .when(attempting(lambda: whether_it_was_made(planned, platform, THIS_CLAIM,
                                                     SOME_ARGUS_ACCOUNT))) \
        .then(all_of(
            it_was_refused_as_changed_since(),
            it_refused_as_the_write_does(
                lambda: roll_back_deployment(planned, platform, SOME_MARK, SOME_ARGUS_ACCOUNT)
            ),
            _no_write_was_asked(platform)
        ))


@pytest.mark.unit
@pytest.mark.parametrize("read", ["deployments_of", "sync_operations_of", "is_syncing_itself",
                                  "mark_on"])
def test_a_rollback_whose_platform_could_not_be_read_is_refused_as_the_write_refuses_it(
    read: str
) -> None:
    platform = a_platform(syncing_itself=True)
    getattr(platform, read).side_effect = PlatformUnreachable(
        DONT_CARE_PLATFORM_WORDS, known_not_applied=False
    )

    Scenario() \
        .given(planned := _a_plan(was_syncing_itself=True)) \
        .when(attempting(lambda: whether_it_was_made(planned, platform, THIS_CLAIM,
                                                     SOME_ARGUS_ACCOUNT))) \
        .then(all_of(
            it_was_refused_as(RollbackRefused),
            it_refused_as_the_write_does(
                lambda: roll_back_deployment(planned, platform, SOME_MARK, SOME_ARGUS_ACCOUNT)
            ),
            _no_write_was_asked(platform)
        ))


@pytest.mark.unit
@pytest.mark.parametrize(
    "a_platform_nobody_can_answer_for",
    [
        pytest.param(lambda: a_platform(operations=THE_PLATFORM_MID_SYNC),
                     id="mid-sync-of-its-own"),
        pytest.param(lambda: a_platform(history=[_a_deployment(THE_ENTRY_RUNNING,
                                                               THE_REVISION_RUNNING)]),
                     id="a-plan-the-tier-s-rule-does-not-give")
    ]
)
def test_a_rollback_nobody_can_answer_for_is_refused_as_the_write_refuses_it(
    a_platform_nobody_can_answer_for: Callable[[], Any]
) -> None:
    # Refused plainly by the write, nothing said known of what landed - and so
    # by the read, which is no evidence anybody acted.
    platform = a_platform_nobody_can_answer_for()

    Scenario() \
        .given(planned := _a_plan(was_syncing_itself=True)) \
        .when(attempting(lambda: whether_it_was_made(planned, platform, THIS_CLAIM,
                                                     SOME_ARGUS_ACCOUNT))) \
        .then(all_of(
            it_was_refused_as(RollbackRefused),
            it_is_not_said_changed_since(),
            it_refused_as_the_write_does(
                lambda: roll_back_deployment(planned, platform, SOME_MARK, SOME_ARGUS_ACCOUNT)
            ),
            _no_write_was_asked(platform)
        ))


@pytest.mark.unit
def test_a_rollback_asked_after_by_no_claim_is_refused_saying_nobody_can_say() -> None:
    # Whose mark the sync switch carries is part of the write's compare, and a
    # call naming no claim has none to compare it with - which is not evidence
    # anybody acted.
    no_claim = None
    platform = a_platform(history=[*_two_deployments(), _argus_s_rollback_since_the_plan()],
                          syncing_itself=False, marked_by=THIS_CLAIM)

    Scenario() \
        .given(planned := _a_plan(was_syncing_itself=True)) \
        .when(attempting(lambda: whether_it_was_made(planned, platform, no_claim,
                                                     SOME_ARGUS_ACCOUNT))) \
        .then(all_of(
            it_was_refused_as(RollbackRefused),
            it_is_not_said_changed_since(),
            _no_write_was_asked(platform)
        ))


@pytest.mark.unit
def test_a_rollback_with_no_account_to_look_for_is_refused_as_the_write_refuses_it() -> None:
    # Somebody named has deployed since the plan, and with no account of Argus's
    # to look for nobody can say whether it was this rollback: refused as the
    # write refuses it, not said to be anybody's.
    named_since = _a_deployment(THE_NEXT_ENTRY, THE_REVISION_BEFORE_IT,
                                deployed_at=AFTER_THE_PLAN, initiated_by=SOME_PERSON)
    platform = a_platform(history=[*_two_deployments(), named_since],
                          syncing_itself=False, marked_by=THIS_CLAIM)

    Scenario() \
        .given(planned := _a_plan(was_syncing_itself=True)) \
        .when(attempting(lambda: whether_it_was_made(planned, platform, THIS_CLAIM,
                                                     NO_ACCOUNT))) \
        .then(all_of(
            it_was_refused_as(RollbackRefused),
            it_is_not_said_changed_since(),
            it_refused_as_the_write_does(
                lambda: roll_back_deployment(planned, platform, SOME_MARK, NO_ACCOUNT)
            ),
            _no_write_was_asked(platform)
        ))
