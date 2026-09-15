from __future__ import annotations

from typing import Final

import psycopg
from argus_core.models import Postmortem, PostmortemDocument
from psycopg.rows import class_row
from psycopg.types.json import Jsonb

# Neither statement below names a column. Both are built from the models' own
# field names, which is what `class_row` already required of the SELECT and what
# nothing required of the INSERT - so the two lists, kept by hand, were free to
# disagree with each other and with the document they carry.
_DOCUMENT_FIELDS: Final = tuple(PostmortemDocument.model_fields)
_WRITTEN: Final = ("incident_id", *_DOCUMENT_FIELDS)
_READ: Final = tuple(Postmortem.model_fields)

_INSERT: Final = (
    f"INSERT INTO postmortem ({', '.join(_WRITTEN)}) "
    f"VALUES ({', '.join(['%s'] * len(_WRITTEN))})"
)
_SELECT: Final = (
    f"SELECT {', '.join(_READ)} FROM postmortem WHERE incident_id = %s"
)


def _written(document: PostmortemDocument, field: str) -> object:
    """What one field is worth to postgres.

    The list-valued fields are JSONB columns, and psycopg sends a bare list as a
    postgres array. Decided by the value rather than by a list of field names,
    so a list added to the document arrives as JSON without being enrolled here.
    """
    value = getattr(document, field)
    return Jsonb(value) if isinstance(value, list) else value


def record(
    conn: psycopg.Connection, incident_id: str, document: PostmortemDocument
) -> None:
    """Writes the document the agent produced.

    Takes the document rather than a mapping of its fields, and names no columns
    of its own: a field added to the document is written without this file being
    touched, and a caller has no dict key to misspell.

    What remains is a field with no column, and that fails on the next write -
    the INSERT names something postgres does not have. Before, it failed
    nowhere: the field was simply never persisted.
    """
    with conn.cursor() as cursor:
        cursor.execute(
            _INSERT,
            (incident_id, *(_written(document, field) for field in _DOCUMENT_FIELDS))
        )
    conn.commit()


def get_by_incident(conn: psycopg.Connection, incident_id: str) -> Postmortem | None:
    """Reads back the row, as the row model.

    Selects the model's fields by name for the same reason `record` writes them:
    `class_row` matches columns to fields by name anyway, so a hand-written list
    could only ever be a chance to get one wrong.
    """
    with conn.cursor(row_factory=class_row(Postmortem)) as cursor:
        cursor.execute(_SELECT, (incident_id,))
        return cursor.fetchone()
