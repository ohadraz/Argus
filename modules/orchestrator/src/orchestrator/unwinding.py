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

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from agent_mitigation import UndoAttempt
from argus_core import Connections
from argus_core.events import ChangeUndone, Publisher, nobody, publish
from argus_core.models import (
    TakenAction,
    UndoDescriptor,
    Undone,
    changes_something_persistent,
    leaves_something_to_put_back,
    the_identity_recorded,
)
from argus_incidents.repository import taken_actions

# Where the incident's own changes are read from. A seam because the process
# this module is about - every change, in order, each one recorded - is
# assertable without a database behind it, and is the whole of what can go
# wrong here.
type TakenActionsOf = Callable[[str], list[TakenAction]]


class UndoChange(Protocol):
    """One recorded change, put back where it is still Argus's to put back."""

    def __call__(self, undo_descriptor: UndoDescriptor, /) -> UndoAttempt: ...


def _changed_something_and_owed_nothing_back(taken_action: TakenAction) -> bool:
    """Whether this row is the one silence worth breaking.

    Both predicates, because either alone gets a row wrong. A kind that leaves
    something to put back and recorded no descriptor is a change nobody
    accounted for, and a line here would claim something was deliberately left
    - so the first question has to be asked and answered no. A kind that
    changes nothing persistent is the restart, which has nothing to say.
    What is left is the kind that changed something it cannot put back.

    Asked of the kind the row recorded rather than of `has_a_way_back`. The
    column was written from the kind, and on a row old enough it was written
    by a version that spelled the kinds differently - so the kind is the
    authority and the column is its copy. A kind this version cannot read at
    all is passed over, as it is everywhere else a stored tag is resolved: an
    incident whose actions predate the vocabulary is history, and history is
    not something to invent a line about.
    """
    recorded = the_identity_recorded(taken_action.type, taken_action.subject or "")

    if recorded is None:
        return False

    return (not leaves_something_to_put_back(recorded.action_type)
            and changes_something_persistent(recorded.action_type))


def taken_actions_from(connections: Connections) -> TakenActionsOf:
    """The incident's own changes, read through the connections given."""

    def the_taken_actions_of(incident_id: str) -> list[TakenAction]:
        with connections() as conn:
            return taken_actions.get_by_incident(conn, incident_id)

    return the_taken_actions_of


def unwind_incident(incident_id: str,
                    taken_actions_of: TakenActionsOf,
                    undo: UndoChange,
                    publisher: Publisher = nobody) -> None:
    """Puts back every change the incident made, and says what became of each.

    Nothing is filtered by what the walk made of an action. A change the walk
    already put back is put back again, to the state it is already in: the only
    thing the provider's record shows since Argus wrote is Argus's own restore,
    which is nobody else's decision to protect. That is what makes this safe to
    run over an incident that had already tidied up after itself, and safe to
    run twice.

    Three kinds of action have no descriptor to act on, and they are not the
    same thing. One leaves nothing to put back at all - a restart changes no
    persistent state, so there is no change out there and nothing an undo could
    address. One is of a kind that does leave something, and recorded no
    descriptor: the gate refused it, or it never reached the provider. Neither
    is reported as an undo that failed, because asking the provider about a
    flag nobody set would be inventing a change to undo.

    The third changed something and owes nothing back. A discard of stale
    cached figures removed a copy of records it never touched, so there is no
    descriptor by design rather than by accident - writing those figures back
    would recreate the incident. That one is *said*, where the other two are
    passed over in silence, and the difference is what a person reading a
    withdrawn incident can act on: silence here would be the same silence an
    action that never happened produces, and the two send a reader to opposite
    places.

    One flag that cannot be read does not stop the rest. This is the last thing
    that happens to an incident, and a failure that took the remaining changes
    with it would leave more behind rather than less.
    """
    for taken_action in taken_actions_of(incident_id):
        if not taken_action.has_a_way_back or taken_action.undo_descriptor is None:
            if _changed_something_and_owed_nothing_back(taken_action):
                publish(
                    ChangeUndone(
                        incident_id=incident_id,
                        subject=taken_action.subject or "",
                        outcome=Undone.NO_UNDO_WAS_OWED,
                        detail=(
                            "what it removed was derived from records it never "
                            "touched, so there was nothing of Argus's to write "
                            "back"
                        )
                    ),
                    publisher
                )

            continue

        attempt = undo(taken_action.undo_descriptor)
        publish(
            ChangeUndone(
                incident_id=incident_id,
                subject=attempt.subject,
                outcome=attempt.outcome,
                detail=attempt.detail
            ),
            publisher
        )
