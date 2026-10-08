"""Putting one recorded change back (spec §7.3, §13).

One change, one answer, and nothing about who asked. A refuted action puts back
the change it made; a withdrawn incident puts back every change it made. Both
want the same conditional write and neither wants the other's sequencing, so
the capability lives here on its own and the coordination lives with whoever
holds the records.
"""

from __future__ import annotations

from typing import assert_never

from argus_core.models import (
    AcceleratorPinUndo,
    AutoscalerUndo,
    DeploymentRollbackUndo,
    FlagUndo,
    ReplicaUndo,
    UndoDescriptor,
)

from agent_mitigation.actions import UndoAttempt, Undone, state_name
from agent_mitigation.tools import (
    AcceleratorPinRestorer,
    AutoscalingRestorer,
    CapacityRestorer,
    ChangedFromOutside,
    DeploymentRestorer,
    FlagSetter,
)

__all__ = ["undo_change"]


def undo_change(undo_descriptor: UndoDescriptor,
                changed_from_outside: ChangedFromOutside,
                set_state: FlagSetter,
                restore_deployment: DeploymentRestorer,
                restore_capacity: CapacityRestorer,
                restore_autoscaling: AutoscalingRestorer,
                restore_accelerator_pin: AcceleratorPinRestorer) -> UndoAttempt:
    """Puts one recorded change back, where it is still Argus's to put back.

    The capability, on its own: one change, one answer. Which changes to undo,
    in what order, and where the answers are written down belong to whoever
    holds the records - a refuted action asks for its own, and a withdrawn
    incident asks for every change it made. Sequencing them here would put a
    coordinator inside an agent, and a database behind it.

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

    Which kind of change this is decides everything below, and the tag is what
    decides it. A rollback sent to something that writes flags would be an undo
    writing to the wrong system entirely - which is what a single untagged shape
    made possible, and what the union exists to prevent. One restorer per kind
    that has one, beside the branch that calls it: a further kind of change is a
    seam on this signature and a branch here, rather than two parameters on
    whoever performs an action.
    """
    match undo_descriptor:
        case FlagUndo():
            return _put_a_flag_back(
                undo_descriptor, changed_from_outside, set_state
            )
        case DeploymentRollbackUndo():
            return _put_a_deployment_back(undo_descriptor, restore_deployment)
        case ReplicaUndo():
            return _put_a_size_back(undo_descriptor, restore_capacity)
        case AutoscalerUndo():
            return _put_a_floor_back(undo_descriptor, restore_autoscaling)
        case AcceleratorPinUndo():
            return _put_a_card_pin_back(undo_descriptor, restore_accelerator_pin)
        case _:
            assert_never(undo_descriptor)


def _put_a_deployment_back(undo_descriptor: DeploymentRollbackUndo,
                           restore: DeploymentRestorer) -> UndoAttempt:
    """Puts a rolled-back deployment back on the revision it was running, and
    restores the reconciliation the rollback had to suspend.

    Both, or it is not undone. The revision alone leaves a deployment that
    looks correct and receives nothing, which is worse than the state Argus
    found - so a half-restore is reported as not established, and escalates.

    No "changed from outside" check, unlike a flag. The platform's history is
    append-only and a rollback is addressed to an entry in it, so there is no
    value here somebody could have overwritten between Argus writing and Argus
    reading - the question a flag has to ask does not arise.
    """
    application = undo_descriptor.application

    try:
        restored = restore(undo_descriptor)
    except Exception as error:
        return UndoAttempt(
            subject=application,
            outcome=Undone.NOT_ESTABLISHED,
            detail=(
                f"[{application}] could not be put back on the revision at "
                f"history entry [{undo_descriptor.was_on_history_id}]: {error}"
            ),
        )

    if restored.revision_put_back and restored.automated_sync_put_back:
        return UndoAttempt(
            subject=application,
            outcome=Undone.RESTORED,
            detail=(
                f"[{application}] was put back on the revision at history "
                f"entry [{undo_descriptor.was_on_history_id}], and its "
                f"automated sync was restored"
            ),
        )

    still_changed = ", ".join(
        what for what, put_back in (
            ("the revision it was running", restored.revision_put_back),
            ("automated sync", restored.automated_sync_put_back)
        ) if not put_back
    )

    return UndoAttempt(
        subject=application,
        outcome=Undone.NOT_ESTABLISHED,
        detail=(
            f"[{application}] was only partly put back - {still_changed} "
            f"remains as Argus left it"
        ),
    )


def _put_a_size_back(undo_descriptor: ReplicaUndo,
                     restore: CapacityRestorer) -> UndoAttempt:
    """Puts a scaled-out deployment back to the count it was running, and
    restores the reconciliation the scale-out had to suspend.

    Both, or it is not undone, for the reason a rollback's undo needs both: the
    count alone leaves a deployment that looks correct and receives nothing, which
    is worse than the state Argus found - so a half-restore is reported as not
    established, and escalates.

    No "changed from outside" check, as with a rollback and unlike a flag. What
    this writes is a replica count through the platform's own action, and a count
    somebody else changed meanwhile is a count this is about to set to the figure
    Argus found - which is the restore, not an overwrite of somebody's decision.
    """
    application = undo_descriptor.application

    try:
        restored = restore(undo_descriptor)
    except Exception as error:
        return UndoAttempt(
            subject=application,
            outcome=Undone.NOT_ESTABLISHED,
            detail=(
                f"[{application}] could not be put back to "
                f"[{undo_descriptor.was_replicas}] replicas: {error}"
            ),
        )

    if restored.count_put_back and restored.automated_sync_put_back:
        return UndoAttempt(
            subject=application,
            outcome=Undone.RESTORED,
            detail=(
                f"[{application}] was put back to "
                f"[{undo_descriptor.was_replicas}] replicas, and its automated "
                f"sync was restored"
            ),
        )

    still_changed = ", ".join(
        what for what, put_back in (
            ("the number of replicas it was running", restored.count_put_back),
            ("automated sync", restored.automated_sync_put_back)
        ) if not put_back
    )

    return UndoAttempt(
        subject=application,
        outcome=Undone.NOT_ESTABLISHED,
        detail=(
            f"[{application}] was only partly put back - {still_changed} "
            f"remains as Argus left it"
        ),
    )


def _put_a_floor_back(undo_descriptor: AutoscalerUndo,
                      restore: AutoscalingRestorer) -> UndoAttempt:
    """Lets a pinned autoscaler move again, and restores the reconciliation the
    pin had to suspend.

    Both, or it is not undone, for the reason a scale-out's undo needs both: the
    floor alone leaves a deployment that looks correct and receives nothing, which
    is worse than the state Argus found - so a half-restore is reported as not
    established, and escalates.

    No "changed from outside" check, as with a rollback and a scale-out and unlike
    a flag. What this writes is one field of the autoscaler through the platform's
    own patch, and a floor somebody else moved meanwhile is a floor this is about
    to set to the figure Argus found - which is the restore, not an overwrite of
    somebody's decision.

    Worth reading twice, because this is the one undo that starts something moving
    again rather than putting a value back: the count will begin oscillating within
    a cycle of this returning. That is the honest ending and not a failure - the
    repository still declares the autoscaler that flaps, so a withdrawal returns
    the shop to the incident, exactly as a withdrawn scale-out returns it to
    saturation.
    """
    application = undo_descriptor.application

    try:
        restored = restore(undo_descriptor)
    except Exception as error:
        return UndoAttempt(
            subject=application,
            outcome=Undone.NOT_ESTABLISHED,
            detail=(
                f"[{application}]'s autoscaler floor could not be put back to "
                f"[{undo_descriptor.was_min_replicas}]: {error}"
            ),
        )

    if restored.floor_put_back and restored.automated_sync_put_back:
        return UndoAttempt(
            subject=application,
            outcome=Undone.RESTORED,
            detail=(
                f"[{application}]'s autoscaler floor was put back to "
                f"[{undo_descriptor.was_min_replicas}], and its automated sync "
                f"was restored"
            ),
        )

    still_changed = ", ".join(
        what for what, put_back in (
            ("the floor its autoscaler was holding", restored.floor_put_back),
            ("automated sync", restored.automated_sync_put_back)
        ) if not put_back
    )

    return UndoAttempt(
        subject=application,
        outcome=Undone.NOT_ESTABLISHED,
        detail=(
            f"[{application}] was only partly put back - {still_changed} "
            f"remains as Argus left it"
        ),
    )


def _put_a_card_pin_back(undo_descriptor: AcceleratorPinUndo,
                         restore: AcceleratorPinRestorer) -> UndoAttempt:
    """Lets a deployment's pods off the card Argus held them to - back onto the
    card somebody else had chosen, or onto any card - and restores the
    reconciliation the pin had to suspend.

    Both, or it is not undone, for the reason every undo under a GitOps
    controller needs both. No "changed from outside" check, as with the
    autoscaler's pin: what this writes is one selector through the platform's
    own patch, and setting it to what Argus found is the restore.

    Letting go moves nothing by itself. The pods stay where the pin put them
    until something reschedules them, so a withdrawal leaves the shop well rather
    than returning it to the incident - unlike a withdrawn autoscaler pin.
    """
    application = undo_descriptor.application

    try:
        restored = restore(undo_descriptor)
    except Exception as error:
        return UndoAttempt(
            subject=application,
            outcome=Undone.NOT_ESTABLISHED,
            detail=f"[{application}]'s pods could not be let off their card: {error}",
        )

    if restored.pin_put_back and restored.automated_sync_put_back:
        return UndoAttempt(
            subject=application,
            outcome=Undone.RESTORED,
            detail=(
                f"[{application}]'s pods were let off [{undo_descriptor.pinned_to}], "
                f"and its automated sync was restored"
            ),
        )

    still_changed = ", ".join(
        what for what, put_back in (
            ("the card its pods are held to", restored.pin_put_back),
            ("automated sync", restored.automated_sync_put_back)
        ) if not put_back
    )

    return UndoAttempt(
        subject=application,
        outcome=Undone.NOT_ESTABLISHED,
        detail=(
            f"[{application}] was only partly put back - {still_changed} "
            f"remains as Argus left it"
        ),
    )


def _put_a_flag_back(undo_descriptor: FlagUndo,
                     changed_from_outside: ChangedFromOutside,
                     set_state: FlagSetter) -> UndoAttempt:
    """Puts one flag back, where it is still Argus's to put back."""
    flag = undo_descriptor.flag
    was_enabled = undo_descriptor.was_enabled
    written_at = undo_descriptor.written_at

    if written_at is None:
        return UndoAttempt(
            subject=flag,
            outcome=Undone.NOT_ESTABLISHED,
            detail=(
                f"flag [{flag}] was not written: the change does not record when "
                f"Argus made it, so whether anybody has changed it since cannot "
                f"be asked"
            ),
        )

    changed = changed_from_outside(flag, written_at)

    if changed is None:
        return UndoAttempt(
            subject=flag,
            outcome=Undone.NOT_ESTABLISHED,
            detail=(
                f"whether anybody changed flag [{flag}] since Argus set it could "
                f"not be established, so it was not written"
            ),
        )

    if changed:
        return UndoAttempt(
            subject=flag,
            outcome=Undone.LEFT_AS_FOUND,
            detail=(
                f"flag [{flag}] was left as found: it has been changed from "
                f"outside since Argus set it"
            ),
        )

    try:
        set_state(flag, was_enabled)
    except Exception as error:
        return UndoAttempt(
            subject=flag,
            outcome=Undone.NOT_ESTABLISHED,
            detail=(
                f"flag [{flag}] could not be put back "
                f"{state_name(was_enabled)}: {error}"
            ),
        )

    return UndoAttempt(
        subject=flag,
        outcome=Undone.RESTORED,
        detail=f"flag [{flag}] was put back {state_name(was_enabled)}",
    )
