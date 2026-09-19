from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, field_validator

from argus_core.ids import UuidStr
from argus_core.models.action import UnreadVerdict, Verdict
from argus_core.models.undo_descriptor import UndoDescriptor


class TakenAction(BaseModel):
    id: UuidStr
    incident_id: UuidStr
    hypothesis_id: UuidStr | None
    type: str | None
    subject: str | None
    reversible: bool
    undo_descriptor: UndoDescriptor | None
    outcome: Verdict | UnreadVerdict | None
    taken_at: datetime

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
