"""The executive synopsis as a row: written once per incident, read back whole.

Built as `postmortems` is, from the models' own field names, so a field added to
the synopsis is written and read without this file being touched.
"""

from __future__ import annotations

from datetime import datetime
from typing import Final

import psycopg
from argus_core.models import ExecutiveSynopsis, ExecutiveSynopsisDocument
from psycopg.rows import class_row
from psycopg.types.json import Jsonb
from pydantic import BaseModel

_DOCUMENT_FIELDS: Final = tuple(ExecutiveSynopsisDocument.model_fields)
_WRITTEN: Final = ("incident_id", "created_at", *_DOCUMENT_FIELDS)
_READ: Final = tuple(ExecutiveSynopsis.model_fields)

_INSERT: Final = (
    f"INSERT INTO executive_synopsis ({', '.join(_WRITTEN)}) "
    f"VALUES ({', '.join(['%s'] * len(_WRITTEN))})"
)
_SELECT: Final = (
    f"SELECT {', '.join(_READ)} FROM executive_synopsis WHERE incident_id = %s"
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
    """Writes the synopsis the step produced, dated by the moment of the event
    that says it was written."""
    with conn.cursor() as cursor:
        cursor.execute(
            _INSERT,
            (incident_id, at, *(_written(synopsis, field) for field in _DOCUMENT_FIELDS))
        )
    conn.commit()


def get_by_incident(conn: psycopg.Connection, incident_id: str) -> ExecutiveSynopsis | None:
    """Reads back the incident's synopsis, or `None` where none was written."""
    with conn.cursor(row_factory=class_row(ExecutiveSynopsis)) as cursor:
        cursor.execute(_SELECT, (incident_id,))
        return cursor.fetchone()
