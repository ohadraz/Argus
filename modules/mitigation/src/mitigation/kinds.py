"""Each kind of action Argus takes, and each kind of change it puts back (spec
§7.3, §13).

One class per kind, holding everything that differs between kinds: the write
that performs it and the words for that write, the words for it where nothing
was done, what the wait has to see before the change is in force, and - for a
kind that leaves something behind - how that change is put back and how the
sentence ends when it was. The waiting and the judging are not here, because
they do not differ: `trying` asks every kind the same question of the same
numbers by the same rule.

Putting a change back is here rather than beside the walk for the reason it
was once a module of its own. One change, one answer, and nothing about who
asked. A refuted action puts back the change it made; a withdrawn incident puts
back every change it made. Both want the same conditional write and neither
wants the other's sequencing, so the capability lives here on its own and the
coordination lives with whoever holds the records.
"""

from __future__ import annotations

import logging
from functools import partial
from typing import Any, NamedTuple, Protocol, assert_never

from core import was_lost
from core.models import (
    AcceleratorPinUndo,
    AutoscalerUndo,
    DeploymentRollbackUndo,
    DiscardCacheEntries,
    FlagUndo,
    PinAutoscaler,
    PinToAccelerator,
    ReplicaUndo,
    RestartService,
    RevertFeatureFlag,
    RollBackDeployment,
    ScaleOut,
    UndoDescriptor,
)

from mitigation.actions import Action, UndoAttempt, Undone, state_name
from mitigation.tools import (
    Arrival,
    HasArrived,
    PerformingWrites,
    PuttingBack,
    RolloutReader,
    an_action_in_force_at_once,
)

__all__ = [
    "ActionKind",
    "DiscardCacheEntriesKind",
    "KindOf",
    "Performed",
    "PinAutoscalerKind",
    "PinToAcceleratorKind",
    "RestartServiceKind",
    "RevertFeatureFlagKind",
    "RollBackDeploymentKind",
    "ScaleOutKind",
    "UndoableKind",
    "UndoingKindOf",
    "arrival_of",
    "kind_of",
    "kind_undoing",
    "undo_change"
]

logger = logging.getLogger(__name__)


class Performed(NamedTuple):
    """What performing one action produced, in the two forms everything after
    it needs.

    `said` is the action in words, and it is built where the action's own
    fields are still in hand - every verdict below quotes it, and a detail
    assembled from an action three branches later is one that has to re-derive
    which kind it was.

    `undo_descriptor` is `None` for an action that changed no persistent state.
    Absent rather than empty: a restart leaves nothing behind, and there is no
    honest descriptor for nothing. What tells that apart from a change nobody
    accounted for is the kind, recorded on the row before the action ran.
    """

    said: str
    undo_descriptor: UndoDescriptor | None


class ActionKind[A](Protocol):
    """Everything about one kind of action that differs from every other kind.

    Separate from `UndoableKind` rather than a base of it, because two kinds
    leave nothing behind - a restart and a discard - and a kind made to answer
    how its change is put back would have to invent an answer for nothing.
    """

    def perform(self, action: A, writes: PerformingWrites, /) -> Performed:
        """Does the one thing this action is, and says what it did.

        The only place the kinds part company. Each kind names its own write and
        phrases its own account of it, because the two are one decision: the
        words a verdict quotes have to describe the call that was actually made.
        """
        ...

    def intent(self, action: A, /) -> str:
        """The action in words, for a failure that happened before it did
        anything.

        Separate from `Performed.said`, which reports what *was* done. The two
        differ in tense and in what they may claim: this one is quoted by an
        escalation, where nothing happened and a sentence saying it did would be
        a record of a change nobody made.
        """
        ...

    def arrival(self, action: A, rollouts: RolloutReader, /) -> HasArrived:
        """What the wait has to see before this action's change is in force."""
        ...


class UndoableKind[U](Protocol):
    """How one kind of change is put back, for a kind that leaves one."""

    def undo(self, descriptor: U, putting_back: PuttingBack, /) -> UndoAttempt:
        """Puts one change of this kind back, where it is still Argus's to put
        back, and says what became of it."""
        ...

    def put_back_as(self, descriptor: U, /) -> str:
        """How the sentence ends when a refuted change really was put back.

        Per kind, because the kinds end the sentence differently: a flag was put
        back *on* or *off*, and a deployment was put back *to* a revision. One
        phrasing covering both would have to be vague enough to say neither.
        """
        ...


class KindOf(Protocol):
    """Which kind an action is, for a caller that takes one."""

    def __call__(self, action: Action, /) -> ActionKind[Any]: ...


class UndoingKindOf(Protocol):
    """Which kind puts a recorded change back, for a caller that puts one back."""

    def __call__(self, descriptor: UndoDescriptor, /) -> UndoableKind[Any]: ...


class RevertFeatureFlagKind:
    """Setting a flag to a state, and setting it back."""

    def perform(self, action: RevertFeatureFlag, writes: PerformingWrites, /) -> Performed:
        return Performed(
            said=f"set flag [{action.flag}] {state_name(action.enabled)}",
            undo_descriptor=writes.set_state(action.flag, action.enabled)
        )

    def intent(self, action: RevertFeatureFlag, /) -> str:
        return f"set flag [{action.flag}] {state_name(action.enabled)}"

    def arrival(self, action: RevertFeatureFlag, rollouts: RolloutReader, /) -> HasArrived:
        """Nothing to wait for: the target service reads its flags fresh on every
        request."""
        return an_action_in_force_at_once

    def undo(self, descriptor: FlagUndo, putting_back: PuttingBack, /) -> UndoAttempt:
        """Puts one flag back, where it is still Argus's to put back."""
        flag = descriptor.flag
        was_enabled = descriptor.was_enabled
        written_at = descriptor.written_at

        if written_at is None:
            logger.warning("flag change carries no write time", extra={"subject": flag})

            return UndoAttempt(
                subject=flag,
                outcome=Undone.NOT_ESTABLISHED,
                detail=(
                    "was not written: the change does not record when Argus made it, "
                    "so whether anybody has changed it since cannot be asked"
                ),
            )

        changed = putting_back.changed_from_outside(flag, written_at)

        if changed is None:
            logger.warning("outside change could not be established", extra={"subject": flag})

            return UndoAttempt(
                subject=flag,
                outcome=Undone.NOT_ESTABLISHED,
                detail=(
                    "was not written: whether anybody changed it since Argus set it "
                    "could not be established"
                ),
            )

        if changed:
            logger.info("flag left as found", extra={"subject": flag})

            return UndoAttempt(
                subject=flag,
                outcome=Undone.LEFT_AS_FOUND,
                detail=(
                    "was left as found: it has been changed from outside since Argus "
                    "set it"
                ),
            )

        try:
            putting_back.set_state(flag, was_enabled)
        except Exception as error:
            # A lost run is no failure to put this back: the incident is another
            # claim's walk, and the change is that walk's to put back or keep.
            if was_lost(error):
                raise

            logger.warning("restore failed", exc_info=True, extra={"subject": flag})

            return UndoAttempt(
                subject=flag,
                outcome=Undone.NOT_ESTABLISHED,
                detail=(
                    f"could not be put back {state_name(was_enabled)}: {error}"
                ),
            )

        return UndoAttempt(
            subject=flag,
            outcome=Undone.RESTORED,
            detail=f"was put back {state_name(was_enabled)}",
        )

    def put_back_as(self, descriptor: FlagUndo, /) -> str:
        return state_name(descriptor.was_enabled)


class RestartServiceKind:
    """Bringing a service back under a new process, which leaves nothing to put
    back."""

    def perform(self, action: RestartService, writes: PerformingWrites, /) -> Performed:
        restarted = writes.restart(action.service)

        return Performed(
            said=f"restarted [{restarted.service}]",
            # Nothing to put back. A restart changes no persistent state,
            # so there is no prior value to record and no descriptor that
            # would be true.
            undo_descriptor=None
        )

    def intent(self, action: RestartService, /) -> str:
        return f"restart [{action.service}]"

    def arrival(self, action: RestartService, rollouts: RolloutReader, /) -> HasArrived:
        """Nothing to wait for: a restart is answered with the new process's start
        time, so the tier that performed it has already waited."""
        return an_action_in_force_at_once


class RollBackDeploymentKind:
    """Returning a deployment to the revision it ran before, and putting it back
    on the one it was running."""

    def perform(self, action: RollBackDeployment, writes: PerformingWrites, /) -> Performed:
        rolled_back = writes.roll_back(action.application)

        return Performed(
            said=(
                # The revision it came *from*, which is what the descriptor
                # records and what a reader needs to know was undone - by
                # its commit, which a reader can look up, and not by the
                # platform's entry for it, which is an address nobody can
                # read once the history moves on. Where it went is "the
                # one before", by construction.
                f"rolled [{action.application}] back off revision "
                f"[{rolled_back.was_on_revision}]"
            ),
            undo_descriptor=rolled_back
        )

    def intent(self, action: RollBackDeployment, /) -> str:
        return f"roll [{action.application}] back to its previous revision"

    def arrival(self, action: RollBackDeployment, rollouts: RolloutReader, /) -> HasArrived:
        """Whether the revision a rollback returned to has reached every replica.

        One of the two kinds that change a Deployment, and so one of the two with
        a count to wait on - the revision reaching every replica, which is not the
        count a scale-out waits on.
        """
        return partial(self._how_the_revision_is_arriving, rollouts, action.application)

    def _how_the_revision_is_arriving(self, rollouts: RolloutReader, service: str) -> Arrival:
        """The revision's counts read as a state of arrival.

        Landed is asked first, and the order is the whole of it. A rolling update can
        be stopped after it has finished - every replica already on the new revision,
        nothing left to converge - and a pause read ahead of the counts would answer
        that such a change will never arrive, so Mitigation would report a mitigation
        that is in force on every replica as one that never applied, and wake somebody
        about it.

        The pause answers for a fleet that has *not* finished, which is the case it is
        read for. A rolling update nobody is advancing satisfies no count it has not
        already satisfied, so a caller told only "not yet" would wait for a
        convergence that is not coming - until its lease expired, leaving the change
        applied for another worker to find. Reported as a state rather than judged as a
        duration, which is what makes it readable here at all rather than a judgement
        §16 keeps out of this side.

        A platform reporting the Deployment failed - past the deadline it declares,
        or unable to create its pods - is not converging it either, and ends the
        wait the same way.
        """
        progress = rollouts(service)

        if progress.has_converged:
            return Arrival.ARRIVED

        if progress.is_paused or progress.has_failed:
            return Arrival.WILL_NOT_ARRIVE

        return Arrival.STILL_ARRIVING

    def undo(self,
             descriptor: DeploymentRollbackUndo,
             putting_back: PuttingBack, /) -> UndoAttempt:
        """Puts a rolled-back deployment back on the revision it was running, and
        restores the reconciliation the rollback had to suspend.

        Both, or it is not undone. The revision alone leaves a deployment that
        looks correct and receives nothing, which is worse than the state Argus
        found - so a half-restore is reported as not established, and escalates.

        Only where it is still Argus's, as with a flag - asked of the platform
        rather than of a change log, and by the write tier, which reads it inside
        the same held change that would write. Still Argus's is the newest history
        entry Argus's own, on the revision it rolled back to, with the running
        images that revision's; already back is counted as put back with nothing
        written; anything else is somebody's change, and nothing is written. See
        `_left_as_somebody_set_it` for what that is reported as.
        """
        application = descriptor.application

        try:
            restored = putting_back.restore_deployment(descriptor)
        except Exception as error:
            # A lost run is no failure to put this back: the incident is another
            # claim's walk, and the change is that walk's to put back or keep.
            if was_lost(error):
                raise

            logger.warning("restore failed", exc_info=True, extra={"subject": application})

            return UndoAttempt(
                subject=application,
                outcome=Undone.NOT_ESTABLISHED,
                detail=(
                    f"could not be put back on the revision at "
                    f"history entry [{descriptor.was_on_history_id}]: {error}"
                ),
            )

        if restored.left_because is not None:
            return _left_as_somebody_set_it(application, restored.left_because,
                                            restored.sync_still_suspended)

        if restored.revision_put_back and restored.automated_sync_put_back:
            return UndoAttempt(
                subject=application,
                outcome=Undone.RESTORED,
                detail=(
                    f"was put back on the revision at history "
                    f"entry [{descriptor.was_on_history_id}], and its "
                    f"automated sync was restored"
                ),
            )

        still_changed = ", ".join(
            what for what, put_back in (
                ("the revision it was running", restored.revision_put_back),
                ("automated sync", restored.automated_sync_put_back)
            ) if not put_back
        )
        logger.warning("change only partly put back",
                       extra={"subject": application, "still_changed": still_changed})

        return UndoAttempt(
            subject=application,
            outcome=Undone.NOT_ESTABLISHED,
            detail=(
                f"was only partly put back - {still_changed} "
                f"remains as Argus left it"
            ),
        )

    def put_back_as(self, descriptor: DeploymentRollbackUndo, /) -> str:
        return f"to revision [{descriptor.was_on_revision}]"


class ScaleOutKind:
    """Giving a deployment more replicas than it has, and putting it back to the
    count it was running."""

    def perform(self, action: ScaleOut, writes: PerformingWrites, /) -> Performed:
        scaled = writes.scale_out(action.application)

        return Performed(
            said=(
                # The count it came *from*, which is what the descriptor
                # records and what a reader needs to know was undone. Where
                # it went is the tier's to have decided, and it reports that
                # figure nowhere a verdict can quote it.
                f"scaled [{action.application}] out from "
                f"[{scaled.was_replicas}] {_replicas(scaled.was_replicas)}"
            ),
            undo_descriptor=scaled
        )

    def intent(self, action: ScaleOut, /) -> str:
        return f"scale [{action.application}] out"

    def arrival(self, action: ScaleOut, rollouts: RolloutReader, /) -> HasArrived:
        """Whether the replicas a scale-out asked for are running.

        A different question from the rollback's and not a spelling of it. Every
        replica that exists can be on the right revision while half the replicas asked
        for have yet to start, so one answer would be wrong for one of the two actions
        - see `RolloutProgress`.
        """
        return partial(self._how_the_capacity_is_arriving, rollouts, action.application)

    def _how_the_capacity_is_arriving(self, rollouts: RolloutReader, service: str) -> Arrival:
        """The replica count read as a state of arrival, with no regard to a pause.

        A pause stops a new template rolling out, and nothing else: the deployment
        controller still scales a paused Deployment, across both sides of the split.
        So a held rollout says nothing about whether the replicas asked for are
        coming, and reading it here would escalate a scale-out the platform is in the
        middle of applying.

        A failure is what ends this wait instead: the platform saying it cannot
        create the pods, or has made no progress within the Deployment's deadline.
        Counts first here too, so replicas that all arrived before something else
        went wrong are an arrival.
        """
        progress = rollouts(service)

        if progress.has_every_replica_it_asked_for:
            return Arrival.ARRIVED

        return Arrival.WILL_NOT_ARRIVE if progress.has_failed else Arrival.STILL_ARRIVING

    def undo(self, descriptor: ReplicaUndo, putting_back: PuttingBack, /) -> UndoAttempt:
        """Puts a scaled-out deployment back to the count it was running, and
        restores the reconciliation the scale-out had to suspend.

        Both, or it is not undone, for the reason a rollback's undo needs both: the
        count alone leaves a deployment that looks correct and receives nothing, which
        is worse than the state Argus found - so a half-restore is reported as not
        established, and escalates.

        Only where the count is still Argus's, asked by the write tier as a
        rollback's is: still at the figure Argus asked for is put back, already at
        the figure Argus found is counted as put back with nothing written, and any
        other figure is somebody's change, with nothing written - see
        `_left_as_somebody_set_it`. A deployment an autoscaler sizes has no count of
        Argus's to put back: the count is the controller's, so the tier writes none
        and resumes the sync, and the change is restored with its count left to its
        autoscaler rather than to a figure nobody wrote.
        """
        application = descriptor.application

        try:
            restored = putting_back.restore_capacity(descriptor)
        except Exception as error:
            # A lost run is no failure to put this back: the incident is another
            # claim's walk, and the change is that walk's to put back or keep.
            if was_lost(error):
                raise

            logger.warning("restore failed", exc_info=True, extra={"subject": application})

            return UndoAttempt(
                subject=application,
                outcome=Undone.NOT_ESTABLISHED,
                detail=(
                    f"could not be put back to [{descriptor.was_replicas}] "
                    f"replica{'' if descriptor.was_replicas == 1 else 's'}: {error}"
                ),
            )

        if restored.left_because is not None:
            return _left_as_somebody_set_it(application, restored.left_because,
                                            restored.sync_still_suspended)

        if (restored.count_put_back and restored.automated_sync_put_back
                and restored.count_left_to_its_autoscaler):
            return UndoAttempt(
                subject=application,
                outcome=Undone.RESTORED,
                detail=(
                    "had its count left to its autoscaler, and its automated sync "
                    "was restored"
                ),
                said_as=(
                    "its count was left to its autoscaler and its automated sync "
                    "restored"
                )
            )

        if restored.count_put_back and restored.automated_sync_put_back:
            return UndoAttempt(
                subject=application,
                outcome=Undone.RESTORED,
                detail=(
                    f"was put back to [{descriptor.was_replicas}] "
                    f"replica{'' if descriptor.was_replicas == 1 else 's'}, and its "
                    f"automated sync was restored"
                ),
            )

        still_changed = ", ".join(
            what for what, put_back in (
                ("the number of replicas it was running", restored.count_put_back),
                ("automated sync", restored.automated_sync_put_back)
            ) if not put_back
        )
        logger.warning("change only partly put back",
                       extra={"subject": application, "still_changed": still_changed})

        return UndoAttempt(
            subject=application,
            outcome=Undone.NOT_ESTABLISHED,
            detail=(
                f"was only partly put back - {still_changed} "
                f"remains as Argus left it"
            ),
        )

    def put_back_as(self, descriptor: ReplicaUndo, /) -> str:
        return (f"to [{descriptor.was_replicas}] "
                f"{_replicas(descriptor.was_replicas)}")


class PinAutoscalerKind:
    """Stopping a deployment's autoscaler scaling it down, and letting it move
    again."""

    def perform(self, action: PinAutoscaler, writes: PerformingWrites, /) -> Performed:
        pinned = writes.pin(action.application)

        return Performed(
            said=(
                # The floor it came *from*, named as the floor it came from
                # rather than as the floor it is now - which is the whole care
                # of this line. The descriptor records the prior floor, and a
                # sentence that used it to assert a present state would be
                # false the moment the pin succeeded: "scaling below three"
                # was already true before Argus acted.
                #
                # Where it went, by its number and not by the name of a
                # bound. The tier asks for whichever is smaller of the
                # autoscaler's declared ceiling and the most replicas Argus
                # may hold a deployment at - so "to its ceiling" is false
                # exactly where Argus's own cap was the binding one, and names
                # a figure belonging to somebody else's declaration rather
                # than to anything Argus wrote. The tier records what it
                # asked for, which is why this can say it.
                f"raised [{action.application}]'s autoscaler floor from "
                f"[{pinned.was_min_replicas}] {_replicas(pinned.was_min_replicas)} to "
                f"[{pinned.min_replicas_asked_for}]"
            ),
            undo_descriptor=pinned
        )

    def intent(self, action: PinAutoscaler, /) -> str:
        return f"stop [{action.application}]'s autoscaler scaling it down"

    def arrival(self, action: PinAutoscaler, rollouts: RolloutReader, /) -> HasArrived:
        """Nothing to wait for: an autoscaler's floor is a field on its own object
        rather than a state anything converges on."""
        return an_action_in_force_at_once

    def undo(self, descriptor: AutoscalerUndo, putting_back: PuttingBack, /) -> UndoAttempt:
        """Lets a pinned autoscaler move again, and restores the reconciliation the
        pin had to suspend.

        Both, or it is not undone, for the reason a scale-out's undo needs both: the
        floor alone leaves a deployment that looks correct and receives nothing, which
        is worse than the state Argus found - so a half-restore is reported as not
        established, and escalates.

        Only where the floor is still Argus's, asked by the write tier as a
        rollback's is: still at the floor Argus asked for is put back, already at
        the floor Argus found is counted as put back with nothing written, and any
        other floor - or an autoscaler no longer there - is somebody's change, with
        nothing written. See `_left_as_somebody_set_it`.

        Worth reading twice, because this is the one undo that starts something moving
        again rather than putting a value back: the count will begin oscillating within
        a cycle of this returning. That is the honest ending and not a failure - the
        repository still declares the autoscaler that flaps, so a withdrawal returns
        the shop to the incident, exactly as a withdrawn scale-out returns it to
        saturation.
        """
        application = descriptor.application

        try:
            restored = putting_back.restore_autoscaling(descriptor)
        except Exception as error:
            # A lost run is no failure to put this back: the incident is another
            # claim's walk, and the change is that walk's to put back or keep.
            if was_lost(error):
                raise

            logger.warning("restore failed", exc_info=True, extra={"subject": application})

            return UndoAttempt(
                subject=application,
                outcome=Undone.NOT_ESTABLISHED,
                detail=(
                    f"could not have its autoscaler floor put back to "
                    f"[{descriptor.was_min_replicas}]: {error}"
                ),
            )

        if restored.left_because is not None:
            return _left_as_somebody_set_it(application, restored.left_because,
                                            restored.sync_still_suspended)

        if restored.floor_put_back and restored.automated_sync_put_back:
            return UndoAttempt(
                subject=application,
                outcome=Undone.RESTORED,
                detail=(
                    f"had its autoscaler floor put back to "
                    f"[{descriptor.was_min_replicas}], and its automated sync "
                    f"restored"
                ),
            )

        still_changed = ", ".join(
            what for what, put_back in (
                ("the floor its autoscaler was holding", restored.floor_put_back),
                ("automated sync", restored.automated_sync_put_back)
            ) if not put_back
        )
        logger.warning("change only partly put back",
                       extra={"subject": application, "still_changed": still_changed})

        return UndoAttempt(
            subject=application,
            outcome=Undone.NOT_ESTABLISHED,
            detail=(
                f"was only partly put back - {still_changed} "
                f"remains as Argus left it"
            ),
        )

    def put_back_as(self, descriptor: AutoscalerUndo, /) -> str:
        return (
            f"to an autoscaler floor of "
            f"[{descriptor.was_min_replicas}] "
            f"{_replicas(descriptor.was_min_replicas)}"
        )


class DiscardCacheEntriesKind:
    """Throwing away cached figures that disagree with their records, which owes
    no undo."""

    def perform(self, action: DiscardCacheEntries, writes: PerformingWrites, /) -> Performed:
        discarded = writes.discard(action.keys)

        return Performed(
            said=(
                # The store's figure and never the number of keys asked for.
                # This is the one action confirmed from its own answer, so a
                # sentence quoting what was requested would report a discard
                # that removed nothing as one that removed everything - and
                # nothing downstream watches a series that could contradict
                # it.
                f"discarded [{discarded.discarded}] of "
                f"[{action.service}]'s stale cached figures"
            ),
            # The one action that changes something persistent and still
            # records no way back. A restart records none because it changed
            # nothing to record; this changed something and there is nothing
            # to restore, because the figures were a copy of records it never
            # touched. A descriptor here would promise to write the stale
            # values back, which is a promise to recreate the incident.
            undo_descriptor=None
        )

    def intent(self, action: DiscardCacheEntries, /) -> str:
        # Figures thrown away, never data deleted or a cache cleared. What
        # goes is a copy and the records behind it are untouched, so a verb
        # suggesting otherwise would describe an action a reader should be
        # alarmed by - in a line that exists to explain why Argus is *not*
        # doing it again.
        return f"discard [{action.service}]'s stale cached figures"

    def arrival(self, action: DiscardCacheEntries, rollouts: RolloutReader, /) -> HasArrived:
        """Nothing to wait for: a discard is answered with how many entries went -
        the store has already done it by the time it says so, and nothing converges
        on an absence."""
        return an_action_in_force_at_once


class PinToAcceleratorKind:
    """Holding a deployment's pods to one card, and letting them off it."""

    def perform(self, action: PinToAccelerator, writes: PerformingWrites, /) -> Performed:
        held = writes.pin_to_accelerator(action.application, action.accelerator)

        return Performed(
            said=(
                # Where the pods were held before, because that is what a
                # withdrawal puts back - and "held to the V100" alone reads
                # as though they had been held to something else.
                f"held [{action.application}]'s pods to [{action.accelerator}], "
                f"where they had been held to "
                f"{_the_card_in_words(held.was_pinned_to)}"
            ),
            undo_descriptor=held
        )

    def intent(self, action: PinToAccelerator, /) -> str:
        return f"hold [{action.application}]'s pods to [{action.accelerator}]"

    def arrival(self, action: PinToAccelerator, rollouts: RolloutReader, /) -> HasArrived:
        """Nothing to wait for: a pin to a card is in force once the platform holds
        the selector, with no count of replicas to reach - the pods moving off the
        card is what the rule that paged is watched for."""
        return an_action_in_force_at_once

    def undo(self, descriptor: AcceleratorPinUndo, putting_back: PuttingBack, /) -> UndoAttempt:
        """Lets a deployment's pods off the card Argus held them to - back onto the
        card somebody else had chosen, or onto any card - and restores the
        reconciliation the pin had to suspend.

        Both, or it is not undone, for the reason every undo under a GitOps
        controller needs both. And only where the pin is still Argus's, asked by
        the write tier as a rollback's is: still holding the card Argus chose is
        put back, already back to what Argus found is counted as put back with
        nothing written, and any other selector is somebody's change, with nothing
        written. See `_left_as_somebody_set_it`.

        Letting go moves nothing by itself. The pods stay where the pin put them
        until something reschedules them, so a withdrawal leaves the shop well rather
        than returning it to the incident - unlike a withdrawn autoscaler pin.
        """
        application = descriptor.application

        try:
            restored = putting_back.restore_accelerator_pin(descriptor)
        except Exception as error:
            # A lost run is no failure to put this back: the incident is another
            # claim's walk, and the change is that walk's to put back or keep.
            if was_lost(error):
                raise

            logger.warning("restore failed", exc_info=True, extra={"subject": application})

            return UndoAttempt(
                subject=application,
                outcome=Undone.NOT_ESTABLISHED,
                detail=f"could not have its pods let off their card: {error}",
            )

        if restored.left_because is not None:
            return _left_as_somebody_set_it(application, restored.left_because,
                                            restored.sync_still_suspended)

        if restored.pin_put_back and restored.automated_sync_put_back:
            return UndoAttempt(
                subject=application,
                outcome=Undone.RESTORED,
                detail=(
                    f"had its pods let off [{descriptor.pinned_to}], and its "
                    f"automated sync restored"
                ),
            )

        still_changed = ", ".join(
            what for what, put_back in (
                ("the card its pods are held to", restored.pin_put_back),
                ("automated sync", restored.automated_sync_put_back)
            ) if not put_back
        )
        logger.warning("change only partly put back",
                       extra={"subject": application, "still_changed": still_changed})

        return UndoAttempt(
            subject=application,
            outcome=Undone.NOT_ESTABLISHED,
            detail=(
                f"was only partly put back - {still_changed} "
                f"remains as Argus left it"
            ),
        )

    def put_back_as(self, descriptor: AcceleratorPinUndo, /) -> str:
        # Two endings, and a sentence saying "let go" for both would report
        # a pin somebody else had set as one removed.
        if descriptor.was_pinned_to is None:
            return "to letting its pods run on any card"

        return f"to holding its pods to [{descriptor.was_pinned_to}]"


# One of each, and the only ones there are: a kind holds nothing, so every
# action of a kind is taken by the same instance.
_REVERT_FEATURE_FLAG = RevertFeatureFlagKind()
_RESTART_SERVICE = RestartServiceKind()
_ROLL_BACK_DEPLOYMENT = RollBackDeploymentKind()
_SCALE_OUT = ScaleOutKind()
_PIN_AUTOSCALER = PinAutoscalerKind()
_DISCARD_CACHE_ENTRIES = DiscardCacheEntriesKind()
_PIN_TO_ACCELERATOR = PinToAcceleratorKind()


def kind_of(action: Action) -> ActionKind[Any]:
    """The kind that takes `action`.

    A `match` rather than a table, with `assert_never` on the remaining branch,
    so that a further kind of action is a type error here rather than an action
    performed by falling through to whichever branch happened to be last.
    """
    match action:
        case RevertFeatureFlag():
            return _REVERT_FEATURE_FLAG
        case RestartService():
            return _RESTART_SERVICE
        case RollBackDeployment():
            return _ROLL_BACK_DEPLOYMENT
        case ScaleOut():
            return _SCALE_OUT
        case PinAutoscaler():
            return _PIN_AUTOSCALER
        case PinToAccelerator():
            return _PIN_TO_ACCELERATOR
        case DiscardCacheEntries():
            return _DISCARD_CACHE_ENTRIES
        case _:
            assert_never(action)


def kind_undoing(descriptor: UndoDescriptor) -> UndoableKind[Any]:
    """The kind that puts the change `descriptor` records back.

    The tag decides it, and the tag alone. A rollback sent to something that
    writes flags would be an undo writing to the wrong system entirely - which
    is what a single untagged shape made possible, and what the union exists to
    prevent. `assert_never` on the remaining branch, for the reason `kind_of`
    has one.
    """
    match descriptor:
        case FlagUndo():
            return _REVERT_FEATURE_FLAG
        case DeploymentRollbackUndo():
            return _ROLL_BACK_DEPLOYMENT
        case ReplicaUndo():
            return _SCALE_OUT
        case AutoscalerUndo():
            return _PIN_AUTOSCALER
        case AcceleratorPinUndo():
            return _PIN_TO_ACCELERATOR
        case _:
            assert_never(descriptor)


def undo_change(undo_descriptor: UndoDescriptor, putting_back: PuttingBack) -> UndoAttempt:
    """Puts one recorded change back, where it is still Argus's to put back.

    The capability, on its own: one change, one answer. Which changes to undo,
    in what order, and where the answers are written down belong to whoever
    holds the records - a refuted action asks for its own, and a withdrawn
    incident asks for every change it made. Sequencing them here would put a
    coordinator inside the Mitigator, and a database behind it.

    Conditional, and that is the whole of why this is not a bare `set_state`.
    Somebody who has changed the flag since Argus set it changed it
    deliberately, and a restore that overwrote them would replace a decision
    with a state nobody chose - while claiming to be tidying up after itself.

    The state the descriptor records is what gets written, rather than the
    inverse of what the flag reads now: the descriptor is the record of what
    actually changed, and re-deriving it from a live reading would restore
    whatever happens to be true at the moment of the read.

    Nothing raises. An unwind runs over every change an incident made, and one
    flag nobody can read must not stop the others being put back.

    Which kind of change this is decides everything the kind then does, and the
    tag is what decides it - see `kind_undoing`. One restorer per kind that has
    one, on the `PuttingBack` every kind is handed: a further kind of change is
    a member there and a kind here, rather than two parameters on whoever
    performs an action.
    """
    return kind_undoing(undo_descriptor).undo(undo_descriptor, putting_back)


def arrival_of(action: Action, *, rollouts: RolloutReader) -> HasArrived:
    """Which arrival this action has to wait for, chosen by what it changes.

    Five of the seven kinds have nothing to wait for, each for a reason of its
    own that comes to the same thing - every one of them says its reason on its
    `arrival`. The two that change a Deployment's size or revision wait on
    different counts - the revision reaching every replica, and the replicas
    asked for existing - which is why this dispatches rather than handing one
    check to all seven. A single check would either make five actions wait for a
    rollout nobody started, or let the two that matter be judged on minutes their
    change was not in force for.

    Here rather than at the caller that assembles the walk, because the caller
    holds a bound `take_action` and not the action - the kind is only known at the
    moment one is taken. `kind_of` is exhaustive, so a further kind of action is a
    type error rather than an action silently judged as though it had arrived.
    """
    return kind_of(action).arrival(action, rollouts)


def _left_as_somebody_set_it(subject: str, found: str, sync_still_suspended: bool) -> UndoAttempt:
    """A change to a deployment the write tier found somebody else's since, and
    so wrote nothing to - said in the tier's own words for what it found.

    Two answers, decided on what the tier read rather than on what Argus found
    before it acted. Where the reconciliation Argus suspended still stands,
    resuming it would have the platform re-apply git over the person's change,
    so the tier left the suspension too: something of Argus's is still in place,
    and the change is left standing for a person to decide. Where nothing of
    Argus's stands - sync was off before Argus came, or the person turned it
    back on themselves - the change is left as found, as a flag somebody changed
    is.
    """
    if sync_still_suspended:
        logger.warning("change left standing", extra={"subject": subject, "found": found})

        return UndoAttempt(
            subject=subject,
            outcome=Undone.LEFT_STANDING,
            detail=(
                f"was somebody else's since ({found}), so it was left as they set it "
                f"- and the reconciliation Argus suspended still stands, because "
                f"resuming it would overwrite them"
            )
        )

    logger.info("change left as found", extra={"subject": subject, "found": found})

    return UndoAttempt(
        subject=subject,
        outcome=Undone.LEFT_AS_FOUND,
        detail=f"was left as found: {found}"
    )


def _replicas(count: int) -> str:
    return "replica" if count == 1 else "replicas"


def _the_card_in_words(card: str | None) -> str:
    return "no card" if card is None else f"[{card}]"
