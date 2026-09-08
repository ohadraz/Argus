"""Putting one recorded change back (spec §7.3, §13).

One change, one answer, and nothing about who asked. A refuted action puts back
the change it made; a withdrawn incident puts back every change it made. Both
want the same conditional write and neither wants the other's sequencing, so
the capability lives here on its own and the coordination lives with whoever
holds the records.
"""

from __future__ import annotations

from argus_core.models.undo_descriptor import UndoDescriptor

from agent_mitigation.actions import UndoAttempt, Undone, state_name
from agent_mitigation.tools import (
    ChangedFromOutside,
    FlagSetter,
    set_flag,
    somebody_else_changed_flag_since,
)

__all__ = ["undo_change"]


def undo_change(undo_descriptor: UndoDescriptor,
                set_state: FlagSetter = set_flag,
                changed_from_outside: ChangedFromOutside =
                    somebody_else_changed_flag_since) -> UndoAttempt:
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
    """
    flag = undo_descriptor.flag
    was_enabled = undo_descriptor.was_enabled
    written_at = undo_descriptor.written_at

    if written_at is None:
        return UndoAttempt(
            flag=flag,
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
            flag=flag,
            outcome=Undone.NOT_ESTABLISHED,
            detail=(
                f"whether anybody changed flag [{flag}] since Argus set it could "
                f"not be established, so it was not written"
            ),
        )

    if changed:
        return UndoAttempt(
            flag=flag,
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
            flag=flag,
            outcome=Undone.NOT_ESTABLISHED,
            detail=(
                f"flag [{flag}] could not be put back "
                f"{state_name(was_enabled)}: {error}"
            ),
        )

    return UndoAttempt(
        flag=flag,
        outcome=Undone.RESTORED,
        detail=f"flag [{flag}] was put back {state_name(was_enabled)}",
    )
