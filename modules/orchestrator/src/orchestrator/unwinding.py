from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from agent_mitigation import UndoAttempt, undo_change
from argus_core.db import Connections
from argus_core.models.actor import Actor
from argus_core.models.taken_action import TakenAction
from argus_core.models.undo_descriptor import UndoDescriptor
from argus_incidents.repository import incidents, taken_actions

"""Putting back everything an incident changed, once nobody wants it walked.

The other half of a withdrawal. Marking the incident stops the walk; this makes
stopping honest - a walk halted mid-flight has production in a state it chose
for a reason that no longer applies, and nobody but Argus knows what that state
replaced.

The undo itself belongs to `agent_mitigation`, which is where knowing how to put
a flag back belongs. What lives here is the process: which changes, in what
order, and where the answers are written down - none of which an agent can
decide, because all three need the records and the single writer that holds
them.
"""

# Where the incident's own changes are read from. A seam because the process
# this module is about - every change, in order, each one recorded - is
# assertable without a database behind it, and is the whole of what can go
# wrong here.
type TakenActionsOf = Callable[[str], list[TakenAction]]


class UndoChange(Protocol):
    """One recorded change, put back where it is still Argus's to put back."""

    def __call__(self, undo_descriptor: UndoDescriptor, /) -> UndoAttempt: ...


class RecordNote(Protocol):
    def __call__(
        self,
        incident_id: str,
        actor: Actor,
        action: str,
        result: str | None = None,
    ) -> None: ...


def taken_actions_from(connections: Connections) -> TakenActionsOf:
    """The incident's own changes, read through the connections given."""

    def the_taken_actions_of(incident_id: str) -> list[TakenAction]:
        with connections() as conn:
            return taken_actions.get_by_incident(conn, incident_id)

    return the_taken_actions_of


def notes_into(connections: Connections) -> RecordNote:
    """What became of each change, written through the connections given."""

    def record_note(incident_id: str,
                    actor: Actor,
                    action: str,
                    result: str | None = None) -> None:
        with connections() as conn:
            incidents.record_note(
                conn, incident_id, actor=actor, action=action, result=result
            )

    return record_note


def unwind_incident(incident_id: str,
                    taken_actions_of: TakenActionsOf,
                    record_note: RecordNote,
                    undo: UndoChange = undo_change) -> None:
    """Puts back every change the incident made, and says what became of each.

    Nothing is filtered by what the walk made of an action. A change the walk
    already put back is put back again, to the state it is already in: the only
    thing the provider's record shows since Argus wrote is Argus's own restore,
    which is nobody else's decision to protect. That is what makes this safe to
    run over an incident that had already tidied up after itself, and safe to
    run twice.

    An action carrying no undo descriptor changed nothing: the gate refused it,
    or it could not be performed at all. Asking the provider about a flag nobody
    set would be inventing a change to undo.

    One flag that cannot be read does not stop the rest. This is the last thing
    that happens to an incident, and a failure that took the remaining changes
    with it would leave more behind rather than less.
    """
    for taken_action in taken_actions_of(incident_id):
        if taken_action.undo_descriptor is None:
            continue

        attempt = undo(taken_action.undo_descriptor)
        record_note(
            incident_id,
            actor=Actor.ORCHESTRATOR,
            action=f"withdrawn: {attempt.outcome}",
            result=attempt.detail,
        )
