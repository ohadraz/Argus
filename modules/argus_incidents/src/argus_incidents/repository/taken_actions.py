from __future__ import annotations

from datetime import datetime

import psycopg
from argus_core.models import (
    ActionProgress,
    ActionType,
    TakenAction,
    UndoDescriptor,
    Undone,
    Verdict,
    leaves_something_to_put_back,
)
from psycopg.rows import class_row
from psycopg.types.json import Jsonb


def claim(
    conn: psycopg.Connection,
    incident_id: str,
    hypothesis_id: str,
    action_type: ActionType,
    subject: str | None,
    at: datetime,
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

    `complete` holds the same asymmetry for the outcome, and reading it out is
    where the two halves meet: a spelling Argus can write is a spelling Argus
    reads, so the one state a reader cannot resolve is a row this version did
    not write.

    Whether the action leaves anything to put back is derived from the kind
    rather than taken as an argument, because it *is* the kind: passing it
    would let a caller write a row claiming a restart can be restored. It is
    written with the claim, before anything happens, for the reason `subject`
    is - the row this table exists for is one a worker stopped after writing,
    and its `undo_descriptor` is then NULL either because there was never
    anything to record or because nobody got to record it.

    `at` is when the claim is written, on the caller's clock rather than the
    database's: every other instant of the incident is the caller's, a replay's
    simulated one included. It is not when the action was taken - the claim is
    written before the agent taking it is called in - and a reader dating the
    action asks its announcement (`when_it_was_taken`).
    """
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO action (incident_id, hypothesis_id, type, subject, "
            "                    has_a_way_back, taken_at, progress) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (incident_id, hypothesis_id) "
            "WHERE hypothesis_id IS NOT NULL DO NOTHING",
            (
                incident_id,
                hypothesis_id,
                action_type,
                subject,
                leaves_something_to_put_back(action_type),
                at,
                ActionProgress.CLAIMED,
            ),
        )
        claimed = cursor.rowcount == 1
    conn.commit()

    return claimed


def complete(
    conn: psycopg.Connection,
    incident_id: str,
    hypothesis_id: str,
    outcome: Verdict,
    undo_descriptor: UndoDescriptor | None,
    performed: bool = True,
    *,
    left_behind_known: bool,
    undone: Undone | None = None,
) -> None:
    """Records what came of an action already claimed (spec §11.1, §13), and
    whether it was performed at all.

    A `Verdict` going in, for the reason `claim` takes an `ActionType`: every
    caller is holding the verdict its own attempt just reached, so nothing is
    lost by refusing a spelling that means nothing - and what that buys the
    readers is the guarantee that an outcome none of them can resolve was
    written by a version that is gone, rather than by this one this morning.

    An absent descriptor is stored as NULL: an action that never reached the
    provider changed nothing, and a row offering a way back from a change that
    was never made would send a human to undo it.

    The descriptor recorded is the one the write tier returned rather than the
    one proposed, since that is the account of what actually changed.

    Whether it was performed is written again here, over whatever `advance`
    wrote when the change was made: this is the attempt's own whole account, and
    a change put back after a refutation is a change that was still made.

    And whether the descriptor is the whole of what the attempt left behind:
    what tells a refusal that asked for no change from one whose change
    request's answer was lost, which neither the verdict nor the progress
    can. Required, so a caller that forgot it cannot claim to know the estate.

    And what the attempt's own putting back did, where it put the change back
    after a refutation. `None` where it attempted none, which leaves the change
    to the cleanup after the incident - the safe reading for a caller that
    forgot to say.

    Committing is the caller's. The event reporting this verdict is written on
    the same connection, and a commit here would put the verdict beyond reach
    of the account before the account existed.
    """
    with conn.cursor() as cursor:
        cursor.execute(
            "UPDATE action SET outcome = %s, undo_descriptor = %s, progress = %s, "
            "                  left_behind_known = %s, undone = %s "
            " WHERE incident_id = %s AND hypothesis_id = %s",
            (
                outcome,
                _as_column(undo_descriptor),
                ActionProgress.PERFORMED if performed else ActionProgress.NOT_PERFORMED,
                left_behind_known,
                undone,
                incident_id,
                hypothesis_id,
            ),
        )


def advance(
    conn: psycopg.Connection,
    incident_id: str,
    hypothesis_id: str,
    to: ActionProgress,
    undo_descriptor: UndoDescriptor | None,
) -> None:
    """Moves a claim on to what has since been learnt about it, and leaves any
    row that already says more alone.

    Two moments write it. The change being made, before the wait: a worker that
    dies during the wait leaves a row saying so, with what puts it back - the
    one thing a withdrawal or a failed run's unwinding has to go on. And a
    resumed walk that asked whether a dead worker's change landed: the answer,
    or that there is none to be had.

    Only from `claimed`. A completed row is the attempt's own account, and
    `unknown` is final - a later write about a claim must not overwrite either
    with less than they say.

    Whether what the attempt left is known is not written here. It is the
    attempt's own account, which only `complete` gives: a resumed walk's
    answer that the change landed comes without the descriptor that went with
    the dead worker, and a row moved to `unknown` is one nobody answered.

    Committing is the caller's, as `complete`'s is.
    """
    with conn.cursor() as cursor:
        cursor.execute(
            "UPDATE action SET progress = %s, undo_descriptor = %s "
            " WHERE incident_id = %s AND hypothesis_id = %s AND progress = %s",
            (
                to,
                _as_column(undo_descriptor),
                incident_id,
                hypothesis_id,
                ActionProgress.CLAIMED,
            ),
        )


def settle_claims(conn: psycopg.Connection, incident_id: str) -> None:
    """Every claim of the incident's still open becomes `unknown`.

    For the moment no walk will write the incident's rows again - its run
    settled, failed or finished - so a claim still open there will never be
    answered, and left as it is it reads as an action still in flight.

    Committing is the caller's: it is written beside the run's settling, and
    the two are one moment.
    """
    with conn.cursor() as cursor:
        cursor.execute(
            "UPDATE action SET progress = %s WHERE incident_id = %s AND progress = %s",
            (ActionProgress.UNKNOWN, incident_id, ActionProgress.CLAIMED),
        )


def record(
    conn: psycopg.Connection,
    incident_id: str,
    hypothesis_id: str,
    action_type: ActionType,
    subject: str | None,
    outcome: Verdict,
    undo_descriptor: UndoDescriptor | None,
    at: datetime,
    performed: bool = True,
    *,
    left_behind_known: bool,
    undone: Undone | None = None,
) -> None:
    """One action, claimed and completed in a single step.

    For a caller holding the whole story at once - which the walk does not: it
    claims before acting precisely so that a crash in between is visible. Kept
    because writing a finished action is a real thing to want, and expressing
    it as the two halves at every call site would spread the ordering rule
    across everything that writes one.
    """
    claim(conn, incident_id, hypothesis_id, action_type, subject, at)
    complete(conn, incident_id, hypothesis_id, outcome, undo_descriptor, performed,
             left_behind_known=left_behind_known, undone=undone)


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
            "SELECT id, incident_id, hypothesis_id, type, subject, has_a_way_back, "
            "       undo_descriptor, outcome, taken_at, progress, left_behind_known, "
            "       undone "
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
            "SELECT id, incident_id, hypothesis_id, type, subject, has_a_way_back, "
            "       undo_descriptor, outcome, taken_at, progress, left_behind_known, "
            "       undone "
            "  FROM action "
            " WHERE incident_id = %s "
            "ORDER BY taken_at",
            (incident_id,),
        )
        return cursor.fetchall()


def _as_column(undo_descriptor: UndoDescriptor | None) -> Jsonb | None:
    """A descriptor as the column stores it, NULL where there is none."""
    return (Jsonb(undo_descriptor.model_dump(mode="json"))
            if undo_descriptor is not None else None)
