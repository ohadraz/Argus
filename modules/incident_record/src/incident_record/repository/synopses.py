"""The executive synopsis as a row: one per incident, read back whole.

Built as `postmortems` is: its columns said here, each named for the field it
holds, and read back brought up to the shape the synopsis is at now.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Final

import psycopg
from core.models import ExecutiveSynopsis, ExecutiveSynopsisDocument
from core.stored import EXECUTIVE_SYNOPSIS, SHIPPED, Shapes, up_to_date
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from pydantic import BaseModel

# Said here rather than read off the model, and held to it by this module's
# suite, for the reasons `postmortems` gives.
DOCUMENT_COLUMNS: Final = (
    "cost_by_title", "responder_cost_estimate", "responder_cost_minimum",
    "responder_cost_maximum", "responder_cost_currency", "response_cost_basis", "overview",
    "withheld_because", "response_shared"
)
_WRITTEN: Final = ("incident_id", "created_at", "shape", *DOCUMENT_COLUMNS)
_READ: Final = ("id", "incident_id", "created_at", "shape", *DOCUMENT_COLUMNS)

_INSERT: Final = sql.SQL("INSERT INTO executive_synopsis ({}) VALUES ({})").format(
    sql.SQL(", ").join(map(sql.Identifier, _WRITTEN)),
    sql.SQL(", ").join(sql.Placeholder() * len(_WRITTEN))
)
_SELECT: Final = sql.SQL("SELECT {} FROM executive_synopsis WHERE incident_id = %s").format(
    sql.SQL(", ").join(map(sql.Identifier, _READ))
)


def _written(synopsis: ExecutiveSynopsisDocument, field: str) -> object:
    """What one field is worth to postgres: a list as JSONB, each model in it
    dumped as JSON so its amounts reach the column as text the row reads back."""
    value = getattr(synopsis, field)

    if isinstance(value, list):
        return Jsonb([item.model_dump(mode="json") if isinstance(item, BaseModel) else item
                      for item in value])

    return value


def record(conn: psycopg.Connection,
           incident_id: str,
           synopsis: ExecutiveSynopsisDocument,
           *,
           at: datetime) -> None:
    """Writes the synopsis the step produced, in the shape this release writes
    it in, dated by the moment of the event that says it was written -
    replacing any the incident already has, as a postmortem is replaced."""
    with conn.cursor() as cursor:
        cursor.execute("DELETE FROM executive_synopsis WHERE incident_id = %s",
                       (incident_id,))
        cursor.execute(
            _INSERT,
            (incident_id, at, SHIPPED.current(EXECUTIVE_SYNOPSIS),
             *(_written(synopsis, column) for column in DOCUMENT_COLUMNS))
        )


def get_by_incident(conn: psycopg.Connection,
                    incident_id: str,
                    shapes: Shapes = SHIPPED) -> ExecutiveSynopsis | None:
    """Reads back the incident's synopsis, or `None` where none was written -
    brought up to the shape it is at now, and raising where it cannot be."""
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(_SELECT, (incident_id,))
        row = cursor.fetchone()

    return _a_synopsis(row, shapes) if row is not None else None


def _a_synopsis(row: dict[str, Any], shapes: Shapes) -> ExecutiveSynopsis:
    synopsis = up_to_date(EXECUTIVE_SYNOPSIS, row["shape"],
                          {column: row[column] for column in DOCUMENT_COLUMNS}, shapes)

    return ExecutiveSynopsis.model_validate({
        "id": row["id"], "incident_id": row["incident_id"], "created_at": row["created_at"],
        **synopsis
    })
