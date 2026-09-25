"""Putting one recorded change back (spec §7.3, §13).

One change, one answer, and nothing about who asked. A refuted action puts back
the change it made; a withdrawn incident puts back every change it made. Both
want the same conditional write and neither wants the other's sequencing, so
the capability lives here on its own and the coordination lives with whoever
holds the records.
"""

from __future__ import annotations

from typing import assert_never

from argus_core.models import DeploymentRollbackUndo, FlagUndo, UndoDescriptor

from agent_mitigation.actions import UndoAttempt, Undone, state_name
from agent_mitigation.tools import (
    ChangedFromOutside,
    DeploymentRestorer,
    FlagSetter,
)

__all__ = ["undo_change"]


def undo_change(undo_descriptor: UndoDescriptor,
                changed_from_outside: ChangedFromOutside,
                set_state: FlagSetter,
                restore_deployment: DeploymentRestorer) -> UndoAttempt:
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

    Which of the two kinds of change this is decides everything below, and
    the tag is what decides it. A rollback sent to something that writes flags
    would be an undo writing to the wrong system entirely - which is what a
    single untagged shape made possible, and what the union exists to prevent.
    """
    match undo_descriptor:
        case FlagUndo():
            return _put_a_flag_back(
                undo_descriptor, changed_from_outside, set_state
            )
        case DeploymentRollbackUndo():
            return _put_a_deployment_back(undo_descriptor, restore_deployment)
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
