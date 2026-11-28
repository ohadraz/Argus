from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Final, assert_never

import psycopg
from core.models import (
    ActionProgress,
    ActionType,
    AlreadyClaimed,
    ClaimAnswer,
    Claimed,
    IncidentStatus,
    Planned,
    SubjectOpen,
    TakenAction,
    UndoDescriptor,
    Undone,
    Verdict,
    leaves_something_to_put_back,
    the_kind,
)
from core.stored import SHIPPED, UNDO_DESCRIPTOR, Shapes, up_to_date
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

# The index that holds one open change per subject (`rev_001_the_schema`), by
# the name a refusal of it carries.
_ONE_OPEN_CHANGE_PER_SUBJECT: Final = "action_open_once_per_subject_idx"
# How many times a claim refused for its subject is asked: once, and once more
# where the open change stopped being open before it could be named.
_ASKINGS_FOR_AN_OPEN_SUBJECT: Final = 2

# What an action is read from: every field of it, and the shape each of its two
# descriptors was written in.
_COLUMNS: Final = (
    "id, incident_id, hypothesis_id, type, subject, has_a_way_back, "
    "undo_descriptor, undo_shape, outcome, taken_at, progress, left_behind_known, "
    "undone, automated_sync_put_back, plan, plan_shape, since, performed_at, "
    "put_back_because"
)


class NoLongerOpen(Enum):
    """Which of an incident's changes stop being open on their subjects, and
    when each is written.

    `KINDS_WITH_NO_WAY_BACK` - a restart, a discard - at every settle of the
    incident's run: nothing of them stands, and a settled run finishes none it
    left in flight. `ROWS_OF_A_WITHDRAWN_INCIDENT` at that settle too, where the
    incident is withdrawn - asked of its status in the write itself: a
    withdrawn incident is neither resolved nor withdrawn again, so what its
    unwind left standing would otherwise be open for ever. `EVERY_ROW` where a
    person resolves the incident, and takes what it left standing into their
    hands.
    """

    KINDS_WITH_NO_WAY_BACK = "kinds-with-no-way-back"
    ROWS_OF_A_WITHDRAWN_INCIDENT = "rows-of-a-withdrawn-incident"
    EVERY_ROW = "every-row"


def claim(
    conn: psycopg.Connection,
    incident_id: str,
    hypothesis_id: str,
    action_type: ActionType,
    subject: str | None,
    at: datetime,
    *,
    planned: Planned[Any] | None = None
) -> ClaimAnswer:
    """Takes the right to act on one candidate, and answers with the claim's id
    where it got it (spec §11.1, §13); `AlreadyClaimed` where an earlier
    attempt holds the candidate; `SubjectOpen` where another change to the
    same subject may still stand. The id is what the action's writes are
    marked with, so the platform can say afterwards which action a change was.

    One open change per subject, across incidents, and the database refuses
    the second (`action_open_once_per_subject_idx`): two changes open on one
    subject undo each other - one's put-back takes the other's away, and one's
    wait measures the other's change. The candidate's own claim is asked
    first, as the insert's arbiter, so a walk resumed on its candidate is
    answered as already claimed, never as standing in its own way. Refused for
    the subject, the claim names the incident whose change is open there - this
    one's own included - and where that change stopped being open before it
    could be read, asks once more; refused again with none to name, it names
    none. The insert runs in a savepoint, so a refusal costs the caller's
    transaction nothing.

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

    `planned` is the change the claim is taken to make, worked out before it,
    and when the platform said what it was worked out from - one value, so the
    two are written together or not at all, here and by nothing after, for the
    reason `subject` is: a resumed walk finding the row asks the estate whether
    it is as the plan found it, as the plan asked for, or neither, and only a
    plan written before anything moved can be asked that. A second claim on a
    held candidate writes nothing, its plan included: the plan belongs to the
    claim that holds the candidate. Never into `undo_descriptor`, which says
    something of Argus's is out there and would send a withdrawal to put back a
    change never made. `None` for a kind that plans nothing.

    The realm the subject is a name in is the kind's platform
    (`ActionKind.platform`), written beside it: a flag and an application can be
    called alike, and only a change in the same realm is a change to the same
    thing.
    """
    realm = the_kind(action_type).platform if subject is not None else None
    columns = (
        incident_id,
        hypothesis_id,
        action_type,
        subject,
        realm,
        leaves_something_to_put_back(action_type),
        at,
        ActionProgress.CLAIMED,
        _as_column(planned.descriptor if planned is not None else None),
        _the_shape_of(planned.descriptor if planned is not None else None),
        planned.since if planned is not None else None
    )

    for _ in range(_ASKINGS_FOR_AN_OPEN_SUBJECT):
        try:
            return _inserted(conn, columns)
        except psycopg.errors.UniqueViolation as refused:
            if refused.diag.constraint_name != _ONE_OPEN_CHANGE_PER_SUBJECT:
                raise

        open_in = _where_it_is_open(conn, realm, subject)

        if open_in is not None:
            return SubjectOpen(open_in=open_in)

    return SubjectOpen(open_in=None)


def _inserted(conn: psycopg.Connection, columns: tuple[Any, ...]) -> ClaimAnswer:
    """The claim's insert, in a savepoint of its own: claimed, or already
    claimed - and a refusal for the subject raised, with the savepoint rolled
    back and the caller's transaction as it was."""
    with conn.transaction(), conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO action (incident_id, hypothesis_id, type, subject, realm, "
            "                    has_a_way_back, taken_at, progress, plan, plan_shape, "
            "                    since) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (incident_id, hypothesis_id) "
            "WHERE hypothesis_id IS NOT NULL DO NOTHING "
            "RETURNING id",
            columns
        )
        claimed = cursor.fetchone()

    return AlreadyClaimed() if claimed is None else Claimed(action_id=str(claimed[0]))


def _where_it_is_open(conn: psycopg.Connection,
                      realm: str | None,
                      subject: str | None) -> str | None:
    """The incident whose change is open on the subject, or `None` where none
    is now."""
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT incident_id FROM action "
            " WHERE realm = %s AND subject = %s AND open_on_subject",
            (realm, subject)
        )
        found = cursor.fetchone()

    return None if found is None else str(found[0])


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
    automated_sync_put_back: bool | None = None
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
    a change put back after a refutation is a change that was still made. Except
    a row owing its put-back that is completed with no undo: the put-back never
    ran - a person ended the incident first - and `putting-back` is kept, as is
    why it was owed.

    And whether the descriptor is the whole of what the attempt left behind:
    what tells a refusal that asked for no change from one whose change
    request's answer was lost, which neither the verdict nor the progress
    can. Required, so a caller that forgot it cannot claim to know the estate.

    And what the attempt's own putting back did, where it put the change back
    after a refutation. `None` where it attempted none, which leaves the change
    to the cleanup after the incident - the safe reading for a caller that
    forgot to say.

    And whether that putting back left the sync Argus suspended as Argus found
    it, as the write tier answered: a put-back with two halves is not
    established where either fails, and `undone` cannot say which remains.
    `None` where nobody answered - the reading that leaves a sync Argus stopped
    said stopped.

    Committing is the caller's. The event reporting this verdict is written on
    the same connection, and a commit here would put the verdict beyond reach
    of the account before the account existed.
    """
    with conn.cursor() as cursor:
        cursor.execute(
            "UPDATE action SET outcome = %(outcome)s, undo_descriptor = %(undo)s, "
            "                  undo_shape = %(undo_shape)s, "
            "                  progress = CASE WHEN progress = %(owed)s "
            "                                   AND %(undone)s::text IS NULL "
            "                                  THEN %(owed)s ELSE %(progress)s END, "
            "                  left_behind_known = %(known)s, undone = %(undone)s, "
            "                  automated_sync_put_back = %(sync_put_back)s "
            " WHERE incident_id = %(incident)s AND hypothesis_id = %(hypothesis)s",
            {
                "outcome": outcome,
                "undo": _as_column(undo_descriptor),
                "undo_shape": _the_shape_of(undo_descriptor),
                "owed": ActionProgress.PUTTING_BACK,
                "progress": (ActionProgress.PERFORMED if performed
                             else ActionProgress.NOT_PERFORMED),
                "known": left_behind_known,
                "undone": undone,
                "sync_put_back": automated_sync_put_back,
                "incident": incident_id,
                "hypothesis": hypothesis_id
            }
        )


def advance(
    conn: psycopg.Connection,
    incident_id: str,
    hypothesis_id: str,
    to: ActionProgress,
    undo_descriptor: UndoDescriptor | None,
    *,
    performed_at: datetime | None = None
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

    `performed_at` is when the walk recorded the change made, on the walk's own
    clock - what a resumed walk dates the action by (its `acted_at`) where the
    walk that made it is gone. `None` for a resumed walk's answer that a dead
    worker's change landed: it was not there when the change was made, and its
    own clock now is no stand-in.

    Committing is the caller's, as `complete`'s is.
    """
    with conn.cursor() as cursor:
        cursor.execute(
            "UPDATE action SET progress = %s, undo_descriptor = %s, undo_shape = %s, "
            "                  performed_at = %s "
            " WHERE incident_id = %s AND hypothesis_id = %s AND progress = %s",
            (
                to,
                _as_column(undo_descriptor),
                _the_shape_of(undo_descriptor),
                performed_at,
                incident_id,
                hypothesis_id,
                ActionProgress.CLAIMED
            )
        )


def plan_the_claim(conn: psycopg.Connection,
                   incident_id: str,
                   hypothesis_id: str,
                   planned: Planned[Any]) -> None:
    """Writes onto a claim written with no plan the plan a resumed walk is about
    to take its action on - before the write, so the plan the write compares
    with lives on the claim, as `claim` writes it for a walk that planned first.

    A claim is written with none where its plan was refused, and its worker died
    before recording the refusal; the resumed walk then plans for itself. Only
    onto a claim still `claimed` and still carrying no plan: a plan already on a
    claim is the one its write compares with, and is never written over.

    Committing is the caller's, as `advance`'s is.
    """
    with conn.cursor() as cursor:
        cursor.execute(
            "UPDATE action SET plan = %s, plan_shape = %s, since = %s "
            " WHERE incident_id = %s AND hypothesis_id = %s "
            "   AND progress = %s AND plan IS NULL",
            (
                _as_column(planned.descriptor),
                _the_shape_of(planned.descriptor),
                planned.since,
                incident_id,
                hypothesis_id,
                ActionProgress.CLAIMED
            )
        )


def owe_a_put_back(conn: psycopg.Connection,
                   incident_id: str,
                   hypothesis_id: str,
                   because: str) -> None:
    """A change made that the wait refuted, recorded as owed back before the
    walk's own put-back is attempted, with what the wait found.

    Written in between because that is where a worker can die with a change
    out there it already knows it must put back: a row left here says so, and
    why, where `performed` would send a resumed walk to watch it again.

    Only from `performed` with no outcome yet. A claim may never have changed
    anything, and a completed row - a confirmed change is `performed` too - is
    the attempt's own account, which a later write must not overwrite with
    something it never was. `because` is never cleared: `complete` moves the
    row on and keeps it.

    Committing is the caller's, as `advance`'s is.
    """
    with conn.cursor() as cursor:
        cursor.execute(
            "UPDATE action SET progress = %s, put_back_because = %s "
            " WHERE incident_id = %s AND hypothesis_id = %s "
            "   AND progress = %s AND outcome IS NULL",
            (
                ActionProgress.PUTTING_BACK,
                because,
                incident_id,
                hypothesis_id,
                ActionProgress.PERFORMED
            )
        )


def record_undone(conn: psycopg.Connection,
                  action_id: str,
                  undone: Undone,
                  *,
                  automated_sync_put_back: bool | None = None) -> None:
    """What the cleanup after an incident did with one change, on the change's
    own row.

    The row's `undone` is what the walk page shows, and what a second cleanup
    asks before putting a change back again. Written by the walk's own undo
    through `complete`; this is the same fact from the other thing that puts
    changes back, so a change a withdrawal put back reads as put back rather
    than as the step that stopped.

    Whether the sync came back is kept beside it, as `complete` keeps it - but
    a known return is never taken back. No put-back suspends sync, so a later
    `False` says only that that pass resumed nothing - a sync an earlier pass
    resumed, still coming back, or a read that failed - and `None` (a put-back
    that raised) says nothing. So `True` stays whatever follows, a later `True`
    replaces a `False` - a pass that resumed what an earlier one could not -
    `False` outlives a later `None`, and any answer fills a row that had none.

    By the row's own id, since the cleanup reads the rows it puts back and
    holds each one. Committing is the caller's.
    """
    with conn.cursor() as cursor:
        cursor.execute(
            "UPDATE action SET undone = %s, "
            # `false` orders below `true` and a NULL is passed over.
            "                  automated_sync_put_back = "
            "                      GREATEST(automated_sync_put_back, %s::boolean) "
            " WHERE id = %s",
            (undone, automated_sync_put_back, action_id)
        )


def no_longer_open(conn: psycopg.Connection,
                   incident_id: str,
                   at: datetime,
                   *,
                   which: NoLongerOpen) -> None:
    """The incident's changes `which` names stop being open on their subjects
    at `at`, so another incident may claim them (spec §11.1).

    Only rows not already stopped: the first moment is the one kept. A
    withdrawn incident's are asked of the incident's status in this statement
    rather than by a read before it, so a withdrawal landing in between is
    seen. Committing is the caller's.
    """
    match which:
        case NoLongerOpen.KINDS_WITH_NO_WAY_BACK:
            statement = (
                "UPDATE action SET open_until = %(at)s "
                " WHERE incident_id = %(incident)s AND open_until IS NULL "
                "   AND NOT has_a_way_back"
            )
        case NoLongerOpen.ROWS_OF_A_WITHDRAWN_INCIDENT:
            statement = (
                "UPDATE action SET open_until = %(at)s "
                " WHERE incident_id = %(incident)s AND open_until IS NULL "
                "   AND EXISTS (SELECT 1 FROM incident "
                "                WHERE incident.id = action.incident_id "
                "                  AND incident.status = %(withdrawn)s)"
            )
        case NoLongerOpen.EVERY_ROW:
            statement = (
                "UPDATE action SET open_until = %(at)s "
                " WHERE incident_id = %(incident)s AND open_until IS NULL"
            )
        case _:
            assert_never(which)

    with conn.cursor() as cursor:
        cursor.execute(statement, {"at": at, "incident": incident_id,
                                   "withdrawn": IncidentStatus.WITHDRAWN})


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
            (ActionProgress.UNKNOWN, incident_id, ActionProgress.CLAIMED)
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
    automated_sync_put_back: bool | None = None,
    planned: Planned[Any] | None = None
) -> None:
    """One action, claimed and completed in a single step.

    For a caller holding the whole story at once - which the walk does not: it
    claims before acting precisely so that a crash in between is visible. Kept
    because writing a finished action is a real thing to want, and expressing
    it as the two halves at every call site would spread the ordering rule
    across everything that writes one.

    Raises `ValueError` where the claim writes nothing - the candidate already
    claimed, or another change open on the subject: a caller writing a
    finished action whole means it to be there, and completing a row that was
    never written would build one that isn't.
    """
    answered = claim(conn, incident_id, hypothesis_id, action_type, subject, at,
                     planned=planned)

    if not isinstance(answered, Claimed):
        raise ValueError(
            f"the action on [{subject}] for candidate [{hypothesis_id}] was not "
            f"claimed: {answered!r}"
        )

    complete(conn, incident_id, hypothesis_id, outcome, undo_descriptor, performed,
             left_behind_known=left_behind_known, undone=undone,
             automated_sync_put_back=automated_sync_put_back)


def get_action_for_hypothesis(conn: psycopg.Connection,
                              incident_id: str,
                              hypothesis_id: str,
                              shapes: Shapes = SHIPPED) -> TakenAction | None:
    """The action claimed for one candidate, whether or not it finished.

    What a resumed walk asks. An `outcome` of `None` on the row it finds is the
    case that matters: the action was claimed and the worker holding it stopped
    before recording what happened, which is a question only the provider can
    answer.
    """
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            f"SELECT {_COLUMNS} "
            "  FROM action "
            " WHERE incident_id = %s AND hypothesis_id = %s",
            (incident_id, hypothesis_id)
        )
        row = cursor.fetchone()

    return _an_action(row, shapes) if row is not None else None


def get_by_incident(conn: psycopg.Connection,
                    incident_id: str,
                    shapes: Shapes = SHIPPED) -> list[TakenAction]:
    """Everything the walk did during an incident, in the order it did it.

    A walk's actions are a sequence - tried, undone, tried again - and read back
    in any other order they describe a different incident. `taken_at` carries
    that order; `id` does not, because a random uuid says nothing about when its
    row was written.

    Each brought up to the shape its descriptors are at now, and raising where
    one cannot be: an incident's actions read in part would be told wrong, and
    a put-back read wrong would put back the wrong thing.
    """
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            f"SELECT {_COLUMNS} "
            "  FROM action "
            " WHERE incident_id = %s "
            "ORDER BY taken_at",
            (incident_id,)
        )
        rows = cursor.fetchall()

    return [_an_action(row, shapes) for row in rows]


def _as_column(undo_descriptor: UndoDescriptor | None) -> Jsonb | None:
    """A descriptor as a column stores it - the change made, or the plan - NULL
    where there is none."""
    return (Jsonb(undo_descriptor.model_dump(mode="json"))
            if undo_descriptor is not None else None)


def _the_shape_of(undo_descriptor: UndoDescriptor | None) -> int | None:
    """The shape a descriptor is written in, beside it - NULL where it is."""
    return SHIPPED.current(UNDO_DESCRIPTOR) if undo_descriptor is not None else None


def _an_action(row: dict[str, Any], shapes: Shapes) -> TakenAction:
    """The action a row of `_COLUMNS` holds, each descriptor brought up to
    date before it is read."""
    plan_shape = row.pop("plan_shape")
    undo_shape = row.pop("undo_shape")

    return TakenAction.model_validate({
        **row,
        "plan": _brought_up(row["plan"], plan_shape, shapes),
        "undo_descriptor": _brought_up(row["undo_descriptor"], undo_shape, shapes)
    })


def _brought_up(descriptor: Any, shape: int | None, shapes: Shapes) -> Any:
    """A descriptor brought up to the shape it is at now - absent where none
    was written."""
    if descriptor is None or shape is None:
        return descriptor

    return up_to_date(UNDO_DESCRIPTOR, shape, descriptor, shapes)
