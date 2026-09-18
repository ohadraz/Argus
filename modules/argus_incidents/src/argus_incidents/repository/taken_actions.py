from __future__ import annotations

import psycopg
from argus_core.models import ActionType, TakenAction, UndoDescriptor
from psycopg.rows import class_row
from psycopg.types.json import Jsonb


def claim(
    conn: psycopg.Connection,
    incident_id: str,
    hypothesis_id: str,
    action_type: ActionType,
    subject: str | None,
) -> bool:
    """Takes the right to act on one candidate, and says whether it got it
    (spec §11.1, §13).

    Written *before* the action is taken, which is what makes it a claim rather
    than a record: the unique index on the incident and the candidate is what
    refuses a second insert, so a walk resumed inside this node is told by the
    database that the action already belongs to an earlier attempt. Reading
    first and acting after would let two workers both find nothing and both
    act - the race the run's own claim already declines to call unlikely.

    The row carries no outcome yet, because nothing has happened yet.
    `complete` fills that in.

    `subject` is written here rather than there, and that is the point of its
    being on the claim: the claim is the write that happens *before* anything
    is done, and the one case this table exists to answer is a worker that
    stopped in between. A row found with no outcome has to say what change may
    be out there, and the alternative - recovering it afterwards from the undo
    descriptor of an action that may never have reached the provider - is the
    reconstruction the column exists to avoid.

    Nullable, because a candidate naming no subject is a real candidate: the
    walk already refuses to act on one, and a row is written for what was
    claimed rather than for what was well-formed.

    `hypothesis_id` is required rather than defaulted, because every caller has
    it: an action is taken *for* a candidate, and the node taking it is holding
    that candidate when it writes the row. A default would let a call site that
    does not know which candidate it is acting for compile, and the row it wrote
    would be indistinguishable from one where the association genuinely does not
    apply.

    `action_type` is the tag going in and a bare `str` coming back out, on
    `TakenAction`. That asymmetry is deliberate: every caller here is holding an
    action Argus is about to take, so nothing is lost by refusing a kind that
    does not exist - while a row already written is history, and one recorded
    before a tag was renamed still has to come back out of the table.
    """
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO action (incident_id, hypothesis_id, type, subject, reversible) "
            "VALUES (%s, %s, %s, %s, %s) "
            "ON CONFLICT (incident_id, hypothesis_id) "
            "WHERE hypothesis_id IS NOT NULL DO NOTHING",
            (incident_id, hypothesis_id, action_type, subject, True),
        )
        claimed = cursor.rowcount == 1
    conn.commit()

    return claimed


def complete(
    conn: psycopg.Connection,
    incident_id: str,
    hypothesis_id: str,
    outcome: str,
    undo_descriptor: UndoDescriptor | None,
) -> None:
    """Records what came of an action already claimed (spec §11.1, §13).

    An absent descriptor is stored as NULL: an action that never reached the
    provider changed nothing, and a row offering a way back from a change that
    was never made would send a human to undo it.

    The descriptor recorded is the one the write tier returned rather than the
    one proposed, since that is the account of what actually changed.

    Committing is the caller's. The event reporting this verdict is written on
    the same connection, and a commit here would put the verdict beyond reach
    of the account before the account existed.
    """
    with conn.cursor() as cursor:
        cursor.execute(
            "UPDATE action SET outcome = %s, undo_descriptor = %s "
            " WHERE incident_id = %s AND hypothesis_id = %s",
            (
                outcome,
                Jsonb(undo_descriptor.model_dump(mode="json"))
                if undo_descriptor is not None else None,
                incident_id,
                hypothesis_id,
            ),
        )


def record(
    conn: psycopg.Connection,
    incident_id: str,
    hypothesis_id: str,
    action_type: ActionType,
    subject: str | None,
    outcome: str,
    undo_descriptor: UndoDescriptor | None,
) -> None:
    """One action, claimed and completed in a single step.

    For a caller holding the whole story at once - which the walk does not: it
    claims before acting precisely so that a crash in between is visible. Kept
    because writing a finished action is a real thing to want, and expressing
    it as the two halves at every call site would spread the ordering rule
    across everything that writes one.
    """
    claim(conn, incident_id, hypothesis_id, action_type, subject)
    complete(conn, incident_id, hypothesis_id, outcome, undo_descriptor)


def get_action_for_hypothesis(conn: psycopg.Connection,
                              incident_id: str,
                              hypothesis_id: str) -> TakenAction | None:
    """The action claimed for one candidate, whether or not it finished.

    What a resumed walk asks. An `outcome` of `None` on the row it finds is the
    case that matters: the action was claimed and the worker holding it stopped
    before recording what happened, which is a question only the provider can
    answer.
    """
    with conn.cursor(row_factory=class_row(TakenAction)) as cursor:
        cursor.execute(
            "SELECT id, incident_id, hypothesis_id, type, subject, reversible, "
            "       tier, undo_descriptor, outcome, taken_at, approved_by "
            "  FROM action "
            " WHERE incident_id = %s AND hypothesis_id = %s",
            (incident_id, hypothesis_id),
        )

        return cursor.fetchone()


def get_by_incident(conn: psycopg.Connection, incident_id: str) -> list[TakenAction]:
    """Everything the walk did during an incident, in the order it did it.

    A walk's actions are a sequence - tried, undone, tried again - and read back
    in any other order they describe a different incident. `taken_at` carries
    that order; `id` does not, because a random uuid says nothing about when its
    row was written.
    """
    with conn.cursor(row_factory=class_row(TakenAction)) as cursor:
        cursor.execute(
            "SELECT id, incident_id, hypothesis_id, type, subject, reversible, "
            "       tier, undo_descriptor, outcome, taken_at, approved_by "
            "  FROM action "
            " WHERE incident_id = %s "
            "ORDER BY taken_at",
            (incident_id,),
        )
        return cursor.fetchall()
