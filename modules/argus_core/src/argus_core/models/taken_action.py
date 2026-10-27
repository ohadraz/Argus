from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, field_validator

from argus_core.ids import UuidStr
from argus_core.models.action import UnreadVerdict, Verdict
from argus_core.models.undo_descriptor import UndoDescriptor


class ActionProgress(StrEnum):
    """How far an action got, as its row knows it.

    A fact of its own beside the verdict, because the verdict comes after the
    wait and the change comes before it - and the wait is where a worker dies.
    A row that learnt only at the end whether its change was made said nothing
    about the one attempt nobody else can account for.

    `claimed` is the row from its claim until anything more is known: the action
    about to be taken, or taken by a worker that stopped before it could say.
    `performed` is the change made, whatever came of it after. `not-performed`
    is an attempt that ended before the action itself was done - a platform that
    did not answer, an action with nowhere left to go, an incident a person
    ended first, a write that raised - though it may have changed something on
    the way, which the undo descriptor carries where Argus knows what was left.
    `unknown` is a claim no walk will ever answer: the
    resumed walk could not tell whether the change was made, or the run ended
    with the claim still open. It is final, so nothing later reads it as a claim
    still waiting on its walk.

    Spelt as a verdict is, hyphenated, since both are stored.
    """

    CLAIMED = "claimed"
    PERFORMED = "performed"
    NOT_PERFORMED = "not-performed"
    UNKNOWN = "unknown"


class TakenAction(BaseModel):
    id: UuidStr
    incident_id: UuidStr
    hypothesis_id: UuidStr | None
    type: str
    subject: str | None
    has_a_way_back: bool
    undo_descriptor: UndoDescriptor | None
    outcome: Verdict | UnreadVerdict | None
    taken_at: datetime
    # How far it got. A claim until anything more is written, which is every
    # row's state from the moment it exists.
    progress: ActionProgress = ActionProgress.CLAIMED

    @field_validator("outcome", mode="before")
    @classmethod
    def _the_outcome_this_row_records(cls,
                                      column: str | None
                                      ) -> Verdict | UnreadVerdict | None:
        """The column as a value, decided here and nowhere else.

        Every reader of this table comes through `class_row(TakenAction)`, so
        this is the edge between the text a row holds and the thing the walk,
        memory and the page each branch on. Converted by each of them instead,
        it was converted differently: one raised on a spelling it did not know
        and one passed the row over, which is two policies for one column and
        no way to tell which an incident got.

        `mode="before"` rather than a pass over the rows after the fetch: the
        cursor builds the model itself, so anything mapped afterwards would
        have to either give up `class_row` or walk every row again to change
        one field.

        A spelling no verdict has is kept rather than refused, because the row
        holding it is history and the incident holding *that* is one somebody
        is already looking at. Refusing it would take the dashboard, the
        postmortem and the undo down along with the one verdict nobody can
        read.
        """
        if column is None or isinstance(column, Verdict):
            return column

        try:
            return Verdict(column)
        except ValueError:
            return UnreadVerdict(column)
