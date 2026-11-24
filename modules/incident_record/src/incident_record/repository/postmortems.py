from __future__ import annotations

from datetime import datetime
from typing import Any, Final

import psycopg
from core.models import Postmortem, PostmortemDocument
from core.stored import POSTMORTEM, SHIPPED, Shapes, up_to_date
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from pydantic import BaseModel

# The document's columns, each named for the field it holds, said here rather
# than read off the model: a list read off the model would follow a field
# renamed and leave its column - and every row already in it - behind. Held to
# the model's fields by this module's suite, so a field renamed, added or
# dropped fails there, where a list nobody checked would leave one unwritten.
DOCUMENT_COLUMNS: Final = (
    "root_cause", "cause_in_plain_words", "executive_summary", "symptom",
    "customer_loss_estimate", "estimate_currency", "engineer_minutes", "responders",
    "paged", "responder_titles", "minutes_by_title", "tokens_spent", "assumptions",
    "pull_request", "recommended_action", "disproven_at", "leads", "impact", "detection",
    "trigger", "no_trigger", "resolution", "causal_chain", "contributing_factors",
    "hypotheses", "action_items", "lessons", "detection_lesson", "timeline",
    "changes_read", "log_messages_read", "deployment_changes_read", "code_read",
    "as_it_ran_read", "uses_outside_read", "cause_measured", "fix_branch_read",
    "deploys_reading", "flags_reading", "logs_reading", "review"
)
_WRITTEN: Final = ("incident_id", "created_at", "shape", *DOCUMENT_COLUMNS)
_READ: Final = ("id", "incident_id", "created_at", "shape", *DOCUMENT_COLUMNS)

_INSERT: Final = sql.SQL("INSERT INTO postmortem ({}) VALUES ({})").format(
    sql.SQL(", ").join(map(sql.Identifier, _WRITTEN)),
    sql.SQL(", ").join(sql.Placeholder() * len(_WRITTEN))
)
_SELECT: Final = sql.SQL("SELECT {} FROM postmortem WHERE incident_id = %s").format(
    sql.SQL(", ").join(map(sql.Identifier, _READ))
)


def _written(document: PostmortemDocument, field: str) -> object:
    """What one field is worth to postgres.

    The list- and model-valued fields are JSONB columns. psycopg sends a bare
    list as a postgres array, and refuses a pydantic model outright - so both
    are wrapped, and both are decided by the value rather than by a list of
    field names.

    Dumped as JSON rather than as Python, so a model carrying a moment or an
    enum - a lead's `written_at`, its standing - reaches the column as text
    the row model reads back, and a list of models is dumped one by one.
    """
    value = getattr(document, field)

    if isinstance(value, BaseModel):
        return Jsonb(value.model_dump(mode="json"))

    if isinstance(value, list):
        return Jsonb([item.model_dump(mode="json") if isinstance(item, BaseModel) else item
                      for item in value])

    return value


def record(conn: psycopg.Connection,
           incident_id: str,
           document: PostmortemDocument,
           *,
           at: datetime) -> None:
    """Writes the document the agent produced, in the shape this release
    writes it in.

    Takes the document rather than a mapping of its fields: a caller has no
    dict key to misspell.

    `at` is the moment of the event that says the document was written, so the
    page's author line and the account's line are one instant on one clock.
    """
    with conn.cursor() as cursor:
        cursor.execute(
            _INSERT,
            (incident_id, at, SHIPPED.current(POSTMORTEM),
             *(_written(document, column) for column in DOCUMENT_COLUMNS))
        )


def get_by_incident(conn: psycopg.Connection,
                    incident_id: str,
                    shapes: Shapes = SHIPPED) -> Postmortem | None:
    """Reads back the row, its document brought up to the shape it is at now.

    Every column of the document together, rather than one at a time: a step
    from one shape to the next may move a field from one column to another.
    Raises where it cannot be brought up, or was written by a newer release.
    """
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(_SELECT, (incident_id,))
        row = cursor.fetchone()

    return _a_postmortem(row, shapes) if row is not None else None


def _a_postmortem(row: dict[str, Any], shapes: Shapes) -> Postmortem:
    document = up_to_date(POSTMORTEM, row["shape"],
                          {column: row[column] for column in DOCUMENT_COLUMNS}, shapes)

    return Postmortem.model_validate({
        "id": row["id"], "incident_id": row["incident_id"], "created_at": row["created_at"],
        **document
    })
