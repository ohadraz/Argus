from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from agent_mitigation import UndoAttempt, undo_change
from argus_core.db import connect
from argus_core.models.actor import Actor

from orchestrator.repository import actions, incidents

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
type ActionsOf = Callable[[str], list[actions.Action]]


class UndoChange(Protocol):
    """One recorded change, put back where it is still Argus's to put back."""

    def __call__(self, undo_descriptor: dict[str, object], /) -> UndoAttempt: ...


class RecordNote(Protocol):
    def __call__(
        self,
        incident_id: str,
        actor: Actor,
        action: str,
        result: str | None = None,
    ) -> None: ...


def _the_actions_of(incident_id: str) -> list[actions.Action]:
    with connect() as conn:
        return actions.get_by_incident(conn, incident_id)


def _record_note(incident_id: str,
                 actor: Actor,
                 action: str,
                 result: str | None = None) -> None:
    with connect() as conn:
        incidents.record_note(
            conn, incident_id, actor=actor, action=action, result=result
        )


def unwind_incident(incident_id: str,
                    actions_of: ActionsOf = _the_actions_of,
                    undo: UndoChange = undo_change,
                    record_note: RecordNote = _record_note) -> None:
    """Puts back every change the incident made, and says what became of each.

    Nothing is filtered by what the walk made of an action. A change the walk
    already put back reads as one somebody else changed - because the flag no
    longer holds what Argus wrote - so it is left alone by the same check that
    protects a human's deliberate change. That is what makes this safe to run
    over an incident that had already tidied up after itself, and safe to run
    twice.

    An action carrying no undo descriptor changed nothing: the gate refused it,
    or it could not be performed at all. Asking the provider about a flag nobody
    set would be inventing a change to undo.

    One flag that cannot be read does not stop the rest. This is the last thing
    that happens to an incident, and a failure that took the remaining changes
    with it would leave more behind rather than less.
    """
    for action in actions_of(incident_id):
        if not action.undo_descriptor:
            continue

        attempt = undo(action.undo_descriptor)
        record_note(
            incident_id,
            actor=Actor.ORCHESTRATOR,
            action=f"withdrawn: {attempt.outcome}",
            result=attempt.detail,
        )
