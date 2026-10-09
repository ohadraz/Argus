"""What other tools call an incident, written down and found again.

A tool's later word about an incident - a person resolving it in the paging
tool that woke them - arrives carrying that tool's names for it and none of
Argus's. What this owes its readers is that a name, once given to an incident,
finds that incident and no other, and that a name nobody gave finds nothing.

Names are never moved, only added. A name already held is the same name
arriving again - a re-fired alert, a webhook delivered twice - and the incident
that had it keeps it.
"""

from __future__ import annotations

from collections.abc import Iterable

import psycopg
from argus_core.models import Reference


def add(conn: psycopg.Connection,
        incident_id: str,
        references: Iterable[Reference]) -> None:
    """Gives the incident these names, leaving any name already held where it
    is.

    No commit: the caller's transaction is the one the names belong to. An
    alert's names are written with the incident they open, and an incident
    whose names arrived without it would be names for nothing.
    """
    with conn.cursor() as cursor:
        cursor.executemany(
            "INSERT INTO incident_reference (incident_id, source, kind, value) "
            "VALUES (%s, %s, %s, %s) "
            "ON CONFLICT (source, kind, value) DO NOTHING",
            [
                (incident_id, reference.source, reference.kind, reference.value)
                for reference in references
            ]
        )


def get_values_for(conn: psycopg.Connection, incident_id: str, kind: str) -> list[str]:
    """Every name of this kind the incident is known by.

    The other direction from `get_incident_by_values`: what Argus asks another
    tool with, where nothing has linked the tool's own incident to this one yet.
    """
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT value FROM incident_reference "
            " WHERE incident_id = %s AND kind = %s "
            " ORDER BY recorded_at, value",
            (incident_id, kind)
        )

        return [str(value) for (value,) in cursor.fetchall()]


def get_incident_by_values(conn: psycopg.Connection,
                           kind: str,
                           values: Iterable[str]) -> str | None:
    """The incident holding any of these names of this kind, or `None`.

    Several values because a tool hands back every name its own incident
    carries, and only one of them need be Argus's. Matched within a kind, never
    across: two tools can hand out the same string, and a name matched without
    its kind reaches whichever incident happens to share a spelling.

    Any source, though. The kind says what the name is for - a key stamped on
    what was sent to a paging tool - and the paging tool cannot know which
    monitor stamped it.
    """
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT incident_id FROM incident_reference "
            " WHERE kind = %s AND value = ANY(%s) "
            " LIMIT 1",
            (kind, list(values))
        )
        row = cursor.fetchone()

    return str(row[0]) if row is not None else None
