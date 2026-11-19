"""Rolling a deployment back through the platform (spec §7.3, §12.1).

The write tier's third action. Everything above the port sees an application
name going in and a record of what changed coming back.

The deployment rather than its configuration, because a revision carries the
code and the configuration it shipped with and the platform returns both
together. So one tool answers a configuration changed into a broken state and
new code that broke it alike; which of the two it was is the mode the
Investigator named, and it decides what fix remains, not what is called here.

Shaped like Argo CD's own rollback, which re-syncs the application to an entry
in its own deployment history. That is what makes this admissible as a generic
mitigation rather than an infrastructure change somebody has to approve - the
revision it applies was reviewed and ran before, so Argus is replaying
somebody's change rather than authoring one. Nothing is written to the
repository the revision came from, and nothing here may write one.

Several asks of the platform rather than one, because its own rules make it so.
It is asked two facts nobody above this port holds: which entry is currently
deployed, and whether it is reconciling the application itself. Automated sync
is then suspended, because a real Argo CD *refuses* a rollback while it is on
and would in any case re-apply the revision being rolled away from at the next
pass. Only then is the rollback asked for. How each is asked is the platform
port's adapter's, and nothing here names a route.

Which is also why this mitigates without resolving, and why the descriptor it
returns records two things. The repository still holds the change that caused
the incident - a values file or the source, according to what broke - and the
deployment is merely no longer running it, with reconciliation off so that it
stays that way. Both have to be put back by a withdrawal, and only this module
ever knew either. It records the revision it rolled back to beside them, which
is what that withdrawal compares the platform against.

A withdrawal puts back only what is still Argus's, and reads the platform before
it writes to find out. Still Argus's is the newest entry in the history being
Argus's own rollback - by the account Argus signs in as, of the revision it went
to - and the Deployment running the images the platform renders for that
revision. The images because a `kubectl set image` or a `rollout undo` leaves no
entry in the history and changes exactly them; images alone because the live
template carries defaulted fields git never states. A deployment already back on
the revision Argus found, running what that renders, needs no rollback. Anything
else is somebody's change since, and is left as they set it - with the
reconciliation Argus suspended left suspended too, because resuming it would
have the platform re-apply git over them. What is read decides it; the marks on
the platform's objects are not read.

What this cannot see is a hand edit that leaves every image alone - an
environment variable changed with `kubectl edit` - which reads as Argus's. An
admission webhook that rewrites images reads as a person's change on every
rollback, which overwrites nothing and escalates each one. And resuming the
reconciliation re-applies git to every object of the application, so a person's
change to another of its objects, made while Argus held it off, is reverted with
it.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import Enum, auto
from typing import Final

from core.mcp_transport import (
    a_change_made_since,
    a_refusal_saying_what_it_left,
    an_exhausted_action,
    with_what_it_left,
)
from core.models import (
    ChangeFound,
    DeploymentRestored,
    DeploymentRollbackUndo,
    Made,
    NotMade,
    Planned,
)
from deployment_platform import (
    DeploymentPlatformError,
    DeploymentPlatformWrites,
    DeploymentRecord,
    Mark,
    MarkedObject,
    RequestedSync,
    SyncOperations,
    SyncPhase,
    SyncRun,
)

from write_mcp_server.refusing import a_platform_refusal, no_claim_to_compare_with
from write_mcp_server.sync_switch import (
    Switch,
    suspend_where_it_is_to_be,
    the_switch,
    this_claim_s_suspension_stands,
)

logger = logging.getLogger(__name__)

# Where a run stands that was stopped - being terminated, or ended so. Somebody
# stops one, or the platform's own sync timeout where one is set; a stop of the
# timeout's that takes more than one pass ends in the same words a person's
# does, so the two are not told apart, and neither is written over.
_STOPPED: Final = frozenset({SyncPhase.TERMINATING, SyncPhase.TERMINATED})
# What a stopped run is said as having been: who stopped it is not known.
_STOPPED_BY: Final = "by somebody or by the platform's own sync timeout where one is set"
# Why nobody can say whose a rollback is whose newest entry is Argus's own, at a
# revision it did not roll back to: Argus's account is Argus's, whichever walk or
# person used it, so it is no change of somebody else's - and not this rollback.
_ARGUS_S_ACCOUNT_ELSEWHERE: Final = "Argus's account at a revision this rollback did not go to"


class RollbackStanding(Enum):
    """Where a rollback stands that nobody else has changed since."""

    # The rollback Argus made is still what the platform runs.
    STILL_ARGUS_S = auto()
    # The deployment is already on the revision Argus found it on.
    ALREADY_BACK = auto()
    # The platform is running a sync nobody else asked for and that is not this
    # rollback - its own, or Argus's to another revision - which a put-back
    # cannot be asked beside.
    MID_SYNC = auto()
    # Argus's own rollback, asked or running and not yet in the history: Argus's
    # change on its way, and nothing a put-back can be asked beside either.
    UNDER_WAY = auto()


class NoEarlierRevision(Exception):
    """The application has nothing to roll back to.

    Raised rather than answered with a no-op, and raised *before* anything is
    changed. An application on its first deployment has no earlier entry, and
    a caller told "done" would record a mitigation that never happened and
    then judge the service against it.

    Marked as an exhausted action, as a scale-out past the ceiling is: the
    action has nowhere to go and nothing was touched, so the walk tries its
    next explanation rather than reaching a human, and what it records says
    nothing was changed.
    """


class RollbackRefused(Exception):
    """The platform would not perform the rollback."""


def _refusing(said: str, error: DeploymentPlatformError, *,
              asked_to_change: bool,
              left_behind: DeploymentRollbackUndo | None = None
              ) -> RollbackRefused:
    """This module's refusal, marked as `a_platform_refusal` marks it.

    `left_behind` is what the failure cost, where it cost anything. A platform
    that refuses after reconciliation was suspended has left this application
    un-reconciled and recorded nowhere else, so the suspension travels on every
    refusal after it - a caller told only that the rollback failed would pass
    over the application believing the estate untouched.
    """
    return RollbackRefused(a_platform_refusal(
        said, error, asked_to_change=asked_to_change, left_behind=left_behind
    ))


def plan_rollback(application: str,
                  platform: DeploymentPlatformWrites) -> Planned[DeploymentRollbackUndo]:
    """The rollback of `application` to make, worked out and dated - and nothing
    changed.

    The entry returned to is worked out from the history alone, the way
    `argocd app rollback APPNAME` chooses with its id omitted, once the history
    is read for what it is. The platform adds an entry on every full sync, so a
    run of entries of one revision is one deployment, and the entry returned to
    is the last of the run before the one running. Where the running revision
    appears earlier in the history, the newest run is itself a return - a
    rollback already made, whoever made it, or a revision deployed again - and
    rolling back from it would roll forward to what that return went away from,
    so it is refused as having nothing earlier to return to. Nobody's account is
    read for that.

    Dated by the platform's clock, read before anything it dates. An application
    with nothing to return to raises here, before a claim is written for it.
    """
    try:
        since = platform.now(application)
        history = platform.deployments_of(application)
    except DeploymentPlatformError as error:
        raise _refusing(f"could not read [{application}]: {error}", error,
                        asked_to_change=False) from error

    previous = _the_entry_to_return_to(history)

    if previous is None:
        raise NoEarlierRevision(
            an_exhausted_action(
                f"[{application}] has no revision before the one it is running that "
                f"a rollback could return to, so there is nothing to roll back to"
            )
        )

    running = history[-1]

    try:
        was_syncing_itself = platform.is_syncing_itself(application)
    except DeploymentPlatformError as error:
        raise _refusing(
            f"could not read whether [{application}] syncs itself: {error}", error,
            asked_to_change=False
        ) from error

    return Planned(
        descriptor=DeploymentRollbackUndo(
            application=application,
            was_on_history_id=running.history_id,
            was_on_revision=running.revision,
            rolled_back_to_revision=previous.revision,
            rolled_back_to_history_id=previous.history_id,
            was_syncing_itself=was_syncing_itself
        ),
        since=since
    )


def roll_back_deployment(planned: Planned[DeploymentRollbackUndo],
                         platform: DeploymentPlatformWrites,
                         mark: Mark,
                         argus_account: str) -> DeploymentRollbackUndo:
    """Makes the rollback `planned` describes, where the platform still stands as
    the plan found it, and reports what that cost.

    The suspension carries `mark`. The rollback cannot: the platform records
    under whose account it was made - `argus_account`, for Argus's - and its
    request has nowhere to put more.

    Every comparison is made before anything is written. The plan is first held
    to this tier's own rule: the entry it returns to has to be the one the rule
    gives over the history up to the entry it found running, holding the
    revision it names - anything else is refused plainly, nothing written.

    Then the platform is compared with it, from the plan's `since` on. Running
    the revision the plan found, with no entry since by any named account and no
    sync asked by one, is written - to the entry the plan names, never one worked
    out again. This rollback already made is answered with the plan and nothing
    written: running the revision the plan returns to with an entry of it since
    by Argus's account and by no other, or - before the platform has written that
    entry - a sync to it asked by Argus's account and not yet finished, or one
    running or finished since the plan. A sync of Argus's that failed is not
    made, and leaves nothing behind it. Anything else is somebody's change since
    - a named account's entry since the plan among it, even where the running
    revision has come back to the one found; a sync another account asked for
    that is still being run, or started since the plan however it ended; and
    this rollback's own sync being terminated or ended by termination - by
    somebody, or by the platform's own sync timeout where one is set, which
    ends in the same words - which says the rollback was asked: refused with
    nothing written.

    Every refusal after the platform is read carries the plan where this
    claim's suspension or rollback shows part of it landed, so a re-ask finding
    this claim's work out there never says it left nothing. An entry naming nobody is the
    platform's own sync, and is no change of anybody's - but a sync of its own
    still being run is refused plainly, nothing written, because a rollback asked
    beside it can only come back as an answer nobody can read. The sync switch is
    held to the same rule (`sync_switch`).

    With no `argus_account` to look for, Argus's own entries cannot be told from
    anybody's. Where no named account has deployed or asked for a sync since the
    plan, the rollback is written as above; where one has, nobody can say whose
    it was, and the refusal says nothing it cannot establish - not marked as
    known, and carrying the suspension where this claim's still stands.

    The answer is the plan dated, on the platform's own clock, by when the
    change was made: the rollback's answer, for one written here; for one
    already made, Argus's entry in the history, else the start of the sync
    Argus asked for, else nothing - a sync still only asked has no moment yet.
    `None` is unknown, never a time.

    Raises rather than half-succeeding. A platform that refuses the rollback
    after sync was suspended leaves the suspension in place and says so -
    quietly restoring it would hide a state somebody has to know about.
    """
    descriptor = planned.descriptor
    application = descriptor.application
    target_entry, compared = _compared_with_the_plan(planned, platform, mark, argus_account)

    if compared.made:
        logger.info("deployment already rolled back", extra={
            "application": application, "to_history_id": target_entry
        })
        return descriptor.model_copy(update={"written_at": compared.made_at})

    suspend_where_it_is_to_be(application, compared.switch, platform, mark, _refusing_a_change)

    try:
        answered_at = platform.roll_back(application, target_entry)
    except DeploymentPlatformError as error:
        logger.warning("rollback refused", extra={
            "application": application, "sync_suspended": descriptor.was_syncing_itself
        })
        raise _refusing(
            f"[{application}] could not be rolled back to history entry "
            f"[{target_entry}]: {error}",
            error,
            asked_to_change=True,
            left_behind=descriptor if descriptor.was_syncing_itself else None
        ) from error

    logger.info("deployment rolled back", extra={
        "application": application,
        "from_history_id": descriptor.was_on_history_id,
        "to_history_id": target_entry
    })

    return descriptor.model_copy(update={"written_at": answered_at})


def whether_it_was_made(planned: Planned[DeploymentRollbackUndo],
                        platform: DeploymentPlatformWrites,
                        action_id: str | None,
                        argus_account: str
                        ) -> Made[DeploymentRollbackUndo] | NotMade[DeploymentRollbackUndo]:
    """Whether the rollback `planned` describes was made - the write's own
    compare on the plan, made, as the plan found it, or changed since, with the
    write left out, for a walk resumed after the worker that claimed it died.
    Not `what_became_of_the_rollback`, which asks a different question of a
    different moment.

    Made is answered with what the write would answer, dated as it dates it:
    by Argus's entry, else by the start of Argus's run of it, else `None` for a
    rollback the platform has taken and not yet started. Running the revision
    the plan found, with nothing of this rollback's in the history or under
    way, is nothing landed - carrying the plan where this claim's suspension of
    the sync stands, since that is the claim's all the same, and nothing where
    it does not. Anything else is refused exactly as the write refuses it on
    the same estate, since the two are one compare - an empty `argus_account`
    among it.

    `action_id` is the claim the sync switch is compared under, as the write's
    mark is; a call naming none is refused plainly, as `scaling`'s read refuses
    one. Writes nothing.
    """
    if action_id is None:
        raise RollbackRefused(no_claim_to_compare_with(
            f"the rollback of [{planned.descriptor.application}]"
        ))

    _, compared = _compared_with_the_plan(planned, platform, action_id, argus_account)

    if not compared.made:
        return NotMade[DeploymentRollbackUndo](left_behind=compared.left_behind)

    return Made[DeploymentRollbackUndo](
        descriptor=planned.descriptor.model_copy(update={"written_at": compared.made_at}),
        made_at=compared.made_at
    )


@dataclass(frozen=True)
class _Compared:
    """A rollback's plan held against what was found: where the sync switch
    stands, whether the rollback is already made - and when the platform says
    it was, where it says - or still to make, and what of the claim's is out
    there."""

    switch: Switch
    made: bool
    made_at: datetime | None
    left_behind: DeploymentRollbackUndo | None


def _compared_with_the_plan(planned: Planned[DeploymentRollbackUndo],
                            platform: DeploymentPlatformWrites,
                            claim: Mark | str,
                            argus_account: str) -> tuple[int, _Compared]:
    """What the platform is now, held against `planned` for `claim` - every
    comparison `roll_back_deployment` makes before it writes, raising as it
    raises - with the entry the rollback returns to. The write and the claimed
    read share it, so the two cannot come to read one estate two ways."""
    descriptor = planned.descriptor
    application = descriptor.application
    target_revision = descriptor.rolled_back_to_revision
    target_entry = descriptor.rolled_back_to_history_id

    if target_revision is None or target_entry is None:
        raise RollbackRefused(a_refusal_saying_what_it_left(
            f"the rollback of [{application}] names no entry to return to"
        ))

    try:
        history = platform.deployments_of(application)
        operations = platform.sync_operations_of(application)
        syncing_now = platform.is_syncing_itself(application)
        switch_marked_by = platform.mark_on(application, MarkedObject.APPLICATION)
    except DeploymentPlatformError as error:
        raise _refusing(
            f"could not read what [{application}] is now: {error}", error,
            asked_to_change=False
        ) from error

    # What of this claim's is out there is worked out before any refusal that
    # follows the reads, so every one of them carries it: the suspension under
    # this claim's mark, and the rollback itself - asked and not yet finished,
    # running or done, or in the history.
    requested, last_run = operations.requested, operations.last_run
    suspension_stands = this_claim_s_suspension_stands(
        descriptor.was_syncing_itself, syncing_now, switch_marked_by, claim
    )
    asked = _asked_by_argus(operations, target_revision, argus_account)
    run = _run_by_argus_since(operations, target_revision, argus_account, planned.since)
    rollback_under_way = asked or run is not None

    try:
        since_the_plan = [entry for entry in history
                          if datetime.fromisoformat(entry.deployed_at) >= planned.since]
    except ValueError as error:
        landed = rollback_under_way or suspension_stands
        raise RollbackRefused(a_refusal_saying_what_it_left(
            f"[{application}]'s history says a time that is not one: {error}",
            descriptor if landed else None
        )) from error

    named_since = [entry for entry in since_the_plan if entry.initiated_by]
    this_rollback_s = [entry for entry in named_since
                       if argus_account and entry.initiated_by == argus_account
                       and entry.revision == target_revision]
    # Asked, running or done - or stopped, which only a sync that was asked can
    # be: the change itself has been made, whatever came of it after.
    stopped = (last_run is not None and last_run.started_at >= planned.since
               and (last_run.revision, last_run.initiated_by) == (target_revision, argus_account)
               and bool(argus_account) and last_run.phase in _STOPPED)
    performed = bool(this_rollback_s) or rollback_under_way or stopped
    left_behind = descriptor if performed or suspension_stands else None

    the_rule_s = _the_entry_to_return_to(
        [entry for entry in history if entry.history_id <= descriptor.was_on_history_id]
    )

    if the_rule_s is None or (the_rule_s.history_id, the_rule_s.revision) != (
            target_entry, target_revision):
        raise RollbackRefused(a_refusal_saying_what_it_left(
            f"the rollback of [{application}] asks to return to entry [{target_entry}] "
            f"of revision [{target_revision}], which is not the entry before the one it "
            f"found running",
            left_behind
        ))

    # The platform's own sync, still being run: nobody's change, and nothing to
    # roll back beside - the platform refuses a rollback asked while it runs,
    # in words that say nothing of what lands.
    if requested is not None and requested.initiated_by is None:
        raise RollbackRefused(a_refusal_saying_what_it_left(
            f"[{application}] is in the middle of a sync of its own, to revision "
            f"[{requested.revision}], and a rollback asked beside it could not be "
            f"told apart from it",
            left_behind
        ))

    named_sync_since = (
        (requested is not None and requested.initiated_by is not None)
        or (last_run is not None and last_run.initiated_by is not None
            and last_run.started_at >= planned.since)
    )

    if not argus_account and (named_since or named_sync_since):
        raise RollbackRefused(with_what_it_left(
            f"[{application}] has {_who_deployed(named_since)} since the plan"
            f"{_and_who_asked(requested)}, and with no account of Argus's to look "
            f"for, nobody can say whether any of it was this rollback",
            left_behind
        ))

    somebody_s = [entry for entry in named_since if entry not in this_rollback_s]
    somebody_asked = (requested is not None and requested.initiated_by is not None
                      and not asked)
    # A sync another account started since the plan, however it ended; and this
    # rollback's own sync being terminated or ended by termination, which only
    # somebody does.
    somebody_ran = stopped or (
        last_run is not None and last_run.started_at >= planned.since
        and last_run.initiated_by is not None and last_run.initiated_by != argus_account
    )
    running = history[-1].revision if history else None

    switch = the_switch(descriptor.was_syncing_itself, syncing_now, switch_marked_by, claim)
    nobody_else_s = not somebody_s and not somebody_asked and not somebody_ran
    made = nobody_else_s and (
        (bool(this_rollback_s) and running == target_revision)
        # The history gains its entry only once the sync finishes.
        or (rollback_under_way
            and running in (target_revision, descriptor.was_on_revision))
    )
    still_as_found = (nobody_else_s and not this_rollback_s and not rollback_under_way
                      and running == descriptor.was_on_revision)

    if switch is Switch.CHANGED_SINCE or not (made or still_as_found) or (
            made and switch is Switch.TO_SUSPEND):
        raise RollbackRefused(a_change_made_since(
            f"[{application}] is running revision [{running}] with "
            f"{_who_deployed(somebody_s)} since the plan"
            f"{_and_who_asked(requested) if somebody_asked else ''}"
            f"{_and_who_ran(last_run) if somebody_ran else ''}, and "
            f"{'is' if syncing_now else 'is not'} syncing itself, which is not where "
            f"the rollback from [{descriptor.was_on_revision}] to [{target_revision}] "
            f"found it or would leave it",
            left_behind,
            performed=performed
        ))

    return target_entry, _Compared(
        switch=switch,
        made=made,
        made_at=_when_argus_s_rollback_landed(this_rollback_s, run) if made else None,
        left_behind=left_behind
    )


def _when_argus_s_rollback_landed(entries: list[DeploymentRecord],
                                  run: SyncRun | None) -> datetime | None:
    """When the platform says this rollback, already made, was made - on its own
    clock: its history entry where it has written one, else when it started the
    sync Argus asked for, else `None` for a sync still only asked.

    The first entry, as the change is dated by its first landing. Never the mark's
    moment, which is Argus's clock.
    """
    if entries:
        return datetime.fromisoformat(entries[0].deployed_at)

    return run.started_at if run is not None else None


def _asked_by_argus(operations: SyncOperations, revision: str, argus_account: str) -> bool:
    """Whether the sync asked and not yet finished is one to `revision` asked by
    `argus_account` - which, pending, is the rollback whose answer was lost."""
    requested = operations.requested

    return bool(argus_account) and requested is not None and (
        requested.revision, requested.initiated_by) == (revision, argus_account)


def _run_by_argus_since(operations: SyncOperations,
                        revision: str,
                        argus_account: str,
                        since: datetime) -> SyncRun | None:
    """The last sync the platform ran, where it is one to `revision` asked by
    `argus_account`, started at or after `since`, and running or done - a sync
    that failed made nothing, and one terminated - by somebody, or by the
    platform's own sync timeout where one is set - is not Argus's to read as
    done."""
    run = operations.last_run

    if not argus_account or run is None:
        return None

    if (run.revision, run.initiated_by) != (revision, argus_account):
        return None

    if run.started_at < since or run.phase not in (SyncPhase.RUNNING, SyncPhase.SUCCEEDED):
        return None

    return run


def _and_who_asked(requested: RequestedSync | None) -> str:
    """A sync somebody asked for that is still being run, as a sentence adds it."""
    if requested is None:
        return ""

    return (f" and a sync to [{requested.revision}] asked by [{requested.initiated_by}] "
            f"still being run")


def _and_who_ran(run: SyncRun | None) -> str:
    """A sync somebody started since the plan, as a sentence adds it."""
    if run is None:
        return ""

    return (f" and a sync to [{run.revision}] by [{run.initiated_by}] started since, "
            f"now [{run.phase.name.lower()}]")


def _the_entry_to_return_to(history: list[DeploymentRecord]) -> DeploymentRecord | None:
    """The entry a rollback from the newest of `history` returns to: the last of
    the run before the one running - or `None` where there is none, or where the
    newest run is itself a return to a revision earlier in the history."""
    runs = _runs_of(history)

    if len(runs) < 2 or runs[-1].revision in {run.revision for run in runs[:-1]}:
        return None

    return runs[-2]


def _runs_of(history: list[DeploymentRecord]) -> list[DeploymentRecord]:
    """The last entry of each run of one revision, oldest first: consecutive
    entries of one revision are one deployment synced more than once."""
    runs: list[DeploymentRecord] = []

    for entry in history:
        if runs and runs[-1].revision == entry.revision:
            runs[-1] = entry
        else:
            runs.append(entry)

    return runs


def _who_deployed(entries: list[DeploymentRecord]) -> str:
    """The accounts named on `entries`, as a sentence says them."""
    if not entries:
        return "no deployment by anybody else"

    accounts = ", ".join(sorted({f"[{entry.initiated_by}]" for entry in entries}))

    return f"deployments by {accounts}"


def _refusing_a_change(said: str, error: DeploymentPlatformError) -> RollbackRefused:
    """This module's refusal of a change it asked for, with nothing before it
    left behind."""
    return _refusing(said, error, asked_to_change=True)


def restore_deployment(descriptor: DeploymentRollbackUndo,
                       platform: DeploymentPlatformWrites,
                       mark: Mark,
                       argus_account: str) -> DeploymentRestored:
    """Puts back both of the things a rollback changed, where they are still
    Argus's, and says which it managed - the resumed sync carrying `mark`, as
    the suspension did.

    A pair rather than an exception, because a restore can half-succeed and
    the half that fails is the quiet one: a deployment whose revision is back
    looks right from every angle a reader has, while receiving nothing
    anybody ships to it because the reconciliation Argus suspended is still
    suspended. The caller turns the pair into a verdict; this reports facts.

    The platform is read before anything is written, and what it says decides
    how much is. A rollback still Argus's - the newest entry made by
    `argus_account`, of the revision recorded as rolled back to, and the
    Deployment running what that revision renders - is put back. A deployment
    already back on the revision Argus found, running what that renders, needs
    no rollback, and counts as put back. Anything else is somebody's change
    since: nothing is written, sync is not resumed, and the answer says what was
    found and whether Argus's suspension still stands. A sync of Argus's -
    the rollback or an earlier put-back - that is being terminated or has been
    is among it: somebody stops a sync, or the platform's own sync timeout where
    one is set, in the same words, and a put-back asked beside a person's stop
    would overrule what they did. Writing over it would be this module deciding
    that somebody else's change should not stand, which is not its question to
    answer.

    A read that never came back writes nothing and claims nothing - neither
    half back, nothing found - and neither does a descriptor recorded without
    the revision it rolled back to, nor an empty `argus_account`, since whose
    the newest entry is cannot be asked without both. A put-back made blind is
    the one the check exists to prevent. Nor does a platform in the middle of a
    sync of its own, or of Argus's rollback not yet finished: nobody else's
    change, and nothing a rollback can be asked beside.

    The revision first and reconciliation second, which is the order the
    platform allows: automated sync refuses a rollback, so re-enabling it
    before returning to the earlier entry would make the second step
    impossible.
    """
    application = descriptor.application
    rolled_back_to = descriptor.rolled_back_to_revision

    if rolled_back_to is None:
        logger.error("restore check impossible", extra={
            "application": application, "missing": "rolled_back_to_revision"
        })
        return _said(_nothing_established(), application)

    # No history entry is ever made by nobody, so with no account to look for,
    # Argus's own rollback would read as somebody else's and be left standing.
    if not argus_account:
        logger.error("restore check impossible", extra={
            "application": application, "missing": "argus_account"
        })
        return _said(_nothing_established(), application)

    try:
        found = what_became_of_the_rollback(descriptor, platform, argus_account)
    except DeploymentPlatformError:
        logger.error("restore check failed", exc_info=True,
                     extra={"application": application, "read": "the deployment"})
        return _said(_nothing_established(), application)

    if isinstance(found, str):
        return _left_as_somebody_set_it(found, descriptor, platform)

    if found in (RollbackStanding.MID_SYNC, RollbackStanding.UNDER_WAY):
        # Nobody else's change, and nothing that can be put back while it runs:
        # the put-back goes to a person, as one that could not be made does.
        logger.warning("restore impossible mid-sync", extra={"application": application})
        return _said(_nothing_established(), application)

    if found is RollbackStanding.ALREADY_BACK:
        # Already where Argus found it, whoever put it there: nothing is written
        # for the revision, and it counts as put back.
        revision = True
    else:
        revision = _tried(
            application, "revision",
            lambda: platform.roll_back(application, descriptor.was_on_history_id)
        )

    if not descriptor.was_syncing_itself:
        # It was already off when Argus found it, so leaving it off *is* the
        # restore. Turning it on because that is the usual arrangement would be
        # Argus starting something it did not stop.
        return _said(
            DeploymentRestored(revision_put_back=revision, automated_sync_put_back=True),
            application
        )

    return _said(
        DeploymentRestored(
            revision_put_back=revision,
            automated_sync_put_back=_tried(
                application, "automated sync",
                lambda: platform.resume_sync(application, mark)
            )
        ),
        application
    )


def what_became_of_the_rollback(descriptor: DeploymentRollbackUndo,
                                platform: DeploymentPlatformWrites,
                                argus_account: str) -> RollbackStanding | str:
    """Where the rollback `descriptor` records stands now, or - where it is
    somebody's change since - what was found, said.

    One check for its two callers - the put-back, before it writes anything,
    and a walk resumed after the worker that made the rollback died, before it
    watches it again - so the two cannot come to read one platform two ways.

    Reads the syncs first, the last run before the request. A sync of Argus's
    to either revision this rollback names that somebody is terminating or has
    terminated is their change, said as what was found - read off the run
    first, because the platform keeps the request while a run is terminated,
    and the request alone would read as Argus's change on its way. A put-back
    somebody stopped is not already back. The history gains its entry only when
    a sync finishes, so a sync of Argus's already asked for or running shows
    only there: one back to the revision Argus found is the put-back whose
    answer was lost, taken as the revision put back rather than asked again; one
    to the revision the rollback went to is the rollback itself still under way;
    Argus's to any other revision, and the platform's own, are nobody else's
    change and nothing a put-back can be asked beside. A sync somebody else
    asked for and that is still being run is their change. Then the history,
    then the images: the Deployment's, and those the platform renders for the
    revision the newest entry says it should be on.

    The newest entry is Argus's rollback only where it is of the revision the
    descriptor records as rolled back to, so a descriptor recorded without one
    finds none - its callers ask without it no question. One by Argus's account
    at another revision is not this rollback, and is said so. With no
    `argus_account`, no entry is Argus's. Raises `DeploymentPlatformError` where
    any read fails, so the caller can write nothing on it.
    """
    found = _what_became_of(descriptor, platform.sync_operations_of(descriptor.application),
                            platform, argus_account)

    return found.said if isinstance(found, _ArgusSAccountElsewhere) else found


def still_argus_s(descriptor: DeploymentRollbackUndo,
                  platform: DeploymentPlatformWrites,
                  argus_account: str) -> ChangeFound:
    """Whether the rollback `descriptor` records is still as Argus left it, for
    a walk resumed after the worker that made it died - answered from
    `what_became_of_the_rollback`, the put-back's own check.

    Still Argus's, or Argus's own rollback still under way - whose arrival the
    watch waits on - is Argus's to watch. Already back where Argus found it,
    the platform reconciling the application again, a sync of Argus's somebody
    is terminating or has terminated, or anything else of somebody else's, is a
    change since, saying what was found; so is a rollback whose run of Argus's
    failed of itself, with no entry of it and the deployment not on it - said as
    that, rather than read as somebody having put it back. The platform in a
    sync of its own or of Argus's to another revision, a newest entry by Argus's
    account at a revision this rollback did not go to, a read that never came
    back, a rollback recorded without the revision it went to, and no account
    of Argus's to look for are questions nobody can answer. Writes nothing.
    """
    application = descriptor.application

    if descriptor.rolled_back_to_revision is None:
        return ChangeFound(
            still_argus_s=None,
            found=f"the rollback of [{application}] was recorded without the revision it "
                  f"went to"
        )

    # No history entry is ever made by nobody, so with no account to look for,
    # Argus's own rollback would read as somebody else's.
    if not argus_account:
        return ChangeFound(
            still_argus_s=None,
            found=f"with no account of Argus's to look for, whose the newest deployment "
                  f"of [{application}] is cannot be said"
        )

    try:
        operations = platform.sync_operations_of(application)
        found = _what_became_of(descriptor, operations, platform, argus_account)
        syncing_now = platform.is_syncing_itself(application)
    except DeploymentPlatformError as error:
        logger.warning("still-argus-s check failed", exc_info=True,
                       extra={"application": application})
        return ChangeFound(still_argus_s=None,
                           found=f"could not read what [{application}] is now: {error}")

    # The platform reconciling the application again re-applies git over the
    # rollback at its next pass, as it does over a patch kind's change: not
    # Argus's to watch any more, whoever turned it on.
    if syncing_now:
        return ChangeFound(
            still_argus_s=False,
            found=f"[{application}] is syncing itself again"
                  f"{'' if isinstance(found, RollbackStanding) else f', and {_in_words(found)}'}"
        )

    if found is RollbackStanding.STILL_ARGUS_S or found is RollbackStanding.UNDER_WAY:
        return ChangeFound(still_argus_s=True)

    if found is RollbackStanding.MID_SYNC:
        return ChangeFound(
            still_argus_s=None,
            found=f"[{application}] is in the middle of a sync that is not this rollback, "
                  f"and what it lands is not known yet"
        )

    if isinstance(found, _ArgusSAccountElsewhere):
        return ChangeFound(still_argus_s=None, found=found.said)

    failed = _argus_s_failed_run(descriptor, operations, argus_account)

    if failed is not None:
        return ChangeFound(
            still_argus_s=False,
            found=f"the rollback's run failed: the platform's last sync of [{application}] "
                  f"to revision [{descriptor.rolled_back_to_revision}], asked by Argus, "
                  f"ended [{failed.phase.name.lower()}], and no deployment of it was made"
        )

    if isinstance(found, str):
        return ChangeFound(still_argus_s=False, found=found)

    return ChangeFound(
        still_argus_s=False,
        found=f"[{application}] is already back on revision "
              f"[{descriptor.was_on_revision}], where Argus found it"
    )


def _what_became_of(descriptor: DeploymentRollbackUndo,
                    operations: SyncOperations,
                    platform: DeploymentPlatformWrites,
                    argus_account: str) -> RollbackStanding | str | _ArgusSAccountElsewhere:
    """`what_became_of_the_rollback`, over the syncs `operations` already read -
    with a newest entry by Argus's account at another revision kept apart from
    somebody's change, for `still_argus_s` to say nobody can answer it."""
    application = descriptor.application
    rolled_back_to = descriptor.rolled_back_to_revision
    requested, run = operations.requested, operations.last_run

    # A sync of Argus's being terminated or terminated - as the write reads it.
    # Being terminated, the run comes before the request, which the platform
    # keeps for it. Ended, the platform has cleared its request, so a request
    # standing beside it was asked after it, and says what is happening now.
    if (argus_account and run is not None
            and (run.phase is SyncPhase.TERMINATING
                 or (run.phase is SyncPhase.TERMINATED and requested is None))):
        if (run.revision, run.initiated_by) == (rolled_back_to, argus_account):
            return (
                f"the sync of [{application}] to revision [{rolled_back_to}] that Argus's "
                f"rollback asked for was {_stopped(run.phase)}, {_STOPPED_BY}"
            )

        if (run.revision, run.initiated_by) == (descriptor.was_on_revision, argus_account):
            return (
                f"the sync of [{application}] back to revision "
                f"[{descriptor.was_on_revision}] that Argus's put-back asked for was "
                f"{_stopped(run.phase)}, {_STOPPED_BY}"
            )

    if requested is not None and (requested.revision, requested.initiated_by) == (
            descriptor.was_on_revision, argus_account):
        return RollbackStanding.ALREADY_BACK

    if requested is not None:
        if argus_account and (requested.revision, requested.initiated_by) == (
                rolled_back_to, argus_account):
            return RollbackStanding.UNDER_WAY

        # The platform's own sync, or one of Argus's to neither revision this
        # rollback names: nobody else's change, and nothing to put back beside.
        if requested.initiated_by in (None, argus_account):
            return RollbackStanding.MID_SYNC

        return (
            f"a sync of [{application}] to revision [{requested.revision}], asked by "
            f"[{requested.initiated_by}], is still being run"
        )

    if run is not None and run.phase is SyncPhase.RUNNING and argus_account:
        if (run.revision, run.initiated_by) == (descriptor.was_on_revision, argus_account):
            return RollbackStanding.ALREADY_BACK

        if (run.revision, run.initiated_by) == (rolled_back_to, argus_account):
            return RollbackStanding.UNDER_WAY

    history = platform.deployments_of(application)

    if not history:
        return f"the platform records no deployment of [{application}] at all"

    newest = history[-1]

    if bool(argus_account) and rolled_back_to is not None and (
            newest.revision, newest.initiated_by) == (rolled_back_to, argus_account):
        return _by_its_images(application, rolled_back_to, RollbackStanding.STILL_ARGUS_S,
                              platform)

    if newest.revision == descriptor.was_on_revision:
        return _by_its_images(application, descriptor.was_on_revision,
                              RollbackStanding.ALREADY_BACK, platform)

    if argus_account and newest.initiated_by == argus_account:
        return _ArgusSAccountElsewhere(
            said=f"the newest deployment of [{application}] is by "
                 f"{_ARGUS_S_ACCOUNT_ELSEWHERE}: revision [{newest.revision}], where the "
                 f"rollback went to [{rolled_back_to}]"
        )

    return (
        f"the newest deployment of [{application}] is of revision "
        f"[{newest.revision}], made by [{newest.initiated_by or 'an unnamed account'}] "
        f"rather than by Argus's own rollback"
    )


@dataclass(frozen=True)
class _ArgusSAccountElsewhere:
    """A newest entry by Argus's own account, at a revision this rollback did
    not go to: not this rollback, and not somebody else's change either -
    `said`, what was found."""

    said: str


def _in_words(found: str | _ArgusSAccountElsewhere) -> str:
    """What was found, said."""
    return found.said if isinstance(found, _ArgusSAccountElsewhere) else found


def _stopped(phase: SyncPhase) -> str:
    """How far somebody's stop of a run has got, as a sentence says it."""
    return "being terminated" if phase is SyncPhase.TERMINATING else "terminated"


def _argus_s_failed_run(descriptor: DeploymentRollbackUndo,
                        operations: SyncOperations,
                        argus_account: str) -> SyncRun | None:
    """The platform's last run, where it is Argus's sync to the revision the
    rollback went to and it failed or errored - a rollback that never landed,
    whatever the history shows instead."""
    run = operations.last_run

    if run is None or run.phase not in (SyncPhase.FAILED, SyncPhase.ERROR):
        return None

    if (run.revision, run.initiated_by) != (descriptor.rolled_back_to_revision, argus_account):
        return None

    return run


def _by_its_images(application: str,
                   revision: str,
                   standing: RollbackStanding,
                   platform: DeploymentPlatformWrites) -> RollbackStanding | str:
    """`standing`, where the Deployment runs the images `revision` renders - or,
    where it runs others, what it runs, said: something other than a deployment
    set them, and left no entry in the history doing it."""
    running = platform.images_running(application)
    rendered = platform.images_at(application, revision)

    if running == rendered:
        return standing

    return (
        f"[{application}] runs {_listed(running)}, where revision [{revision}] "
        f"renders {_listed(rendered)} - images set since without a deployment"
    )


def _listed(images: dict[str, str]) -> str:
    """Each container and its image, in a stable order."""
    return ", ".join(f"[{container}] on [{image}]" for container, image in sorted(images.items()))


def _left_as_somebody_set_it(because: str,
                             descriptor: DeploymentRollbackUndo,
                             platform: DeploymentPlatformWrites) -> DeploymentRestored:
    """The answer for a rollback somebody changed since: nothing written, sync
    not resumed, `because` said - and whether the reconciliation Argus
    suspended still stands, read from the platform.

    Read rather than taken from the descriptor, because only the platform knows:
    a person who reverted in git and turned sync back on has ended Argus's
    suspension themselves, and sync that was off before Argus came was never
    Argus's to have suspended. A read that fails here establishes nothing, and
    the answer claims nothing.
    """
    application = descriptor.application

    try:
        syncing_now = platform.is_syncing_itself(application)
    except DeploymentPlatformError:
        logger.error("restore check failed", exc_info=True,
                     extra={"application": application, "read": "automated sync"})
        return _said(_nothing_established(), application)

    return _said(
        DeploymentRestored(
            revision_put_back=False,
            automated_sync_put_back=False,
            left_because=because,
            sync_still_suspended=descriptor.was_syncing_itself and not syncing_now
        ),
        application
    )


def _nothing_established() -> DeploymentRestored:
    """The answer where whose the rollback is could not be found out: nothing
    written, neither half back, nothing found."""
    return DeploymentRestored(revision_put_back=False, automated_sync_put_back=False)


def _said(restored: DeploymentRestored, application: str) -> DeploymentRestored:
    """`restored`, once the log has been told how much of it there is."""
    if restored.left_because is not None:
        logger.warning("deployment left as somebody set it", extra={
            "application": application,
            "found": restored.left_because,
            "sync_still_suspended": restored.sync_still_suspended
        })
    elif restored.revision_put_back and restored.automated_sync_put_back:
        logger.info("deployment restored", extra={"application": application})
    else:
        logger.warning("deployment not fully restored", extra={
            "application": application,
            "revision_put_back": restored.revision_put_back,
            "automated_sync_put_back": restored.automated_sync_put_back
        })

    return restored


def _tried(application: str, step: str, call: Callable[[], object]) -> bool:
    try:
        call()
    except Exception:
        logger.error("restore step failed", exc_info=True,
                     extra={"application": application, "step": step})
        return False

    return True
