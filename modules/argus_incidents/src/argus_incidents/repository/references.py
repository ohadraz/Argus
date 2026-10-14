"""What other tools call an incident, written down and found again.

A tool's later word about an incident - a person resolving it in the paging
tool that woke them - arrives carrying that tool's names for it and none of
Argus's. What this owes its readers is that a name, once given to an incident,
finds that incident - and, for the kinds below that are shared, every other
incident holding it - and that a name nobody gave finds nothing.

Names are never moved, only added. Most are one incident's alone, and one
already held is the same name arriving again - a webhook delivered twice - so
the incident that had it keeps it. Three kinds are shared by design (see the
schema), because the tools handing them out cannot tell Argus's incidents
apart, and a name of those kinds finds every incident holding it.
"""

from __future__ import annotations

from collections.abc import Iterable

import psycopg
from argus_core.models import Incident, Reference
from psycopg.rows import class_row

_GIVE_A_NAME = (
    "INSERT INTO incident_reference (incident_id, source, kind, value) "
    "VALUES (%s, %s, %s, %s) "
    "ON CONFLICT DO NOTHING"
)


def add(conn: psycopg.Connection,
        incident_id: str,
        references: Iterable[Reference]) -> None:
    """Gives the incident these names, leaving any name already held where it
    is.

    No commit: the caller's transaction is the one the names belong to. An
    alert's names are written with the incident they open, and an incident
    whose names arrived without it would be names for nothing.

    A conflict on any of the table's keys writes nothing, not only on the name
    itself: an incident's second thread in a channel is a name nobody holds,
    and the first thread still stands.
    """
    with conn.cursor() as cursor:
        cursor.executemany(
            _GIVE_A_NAME,
            [
                (incident_id, reference.source, reference.kind, reference.value)
                for reference in references
            ]
        )


def get_values_for(conn: psycopg.Connection, incident_id: str, kind: str) -> list[str]:
    """Every name of this kind the incident is known by.

    The other direction from `get_incidents_by_values`: what Argus asks another
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


def get_incidents_by_values(conn: psycopg.Connection,
                            kind: str,
                            values: Iterable[str]) -> list[Incident]:
    """Every incident holding any of these names of this kind, in no order.

    Several values because a tool hands back every name its own incident
    carries, and only one of them need be Argus's. Matched within a kind, never
    across: two tools can hand out the same string, and a name matched without
    its kind reaches whichever incident happens to share a spelling.

    Any source, though. The kind says what the name is for - a key stamped on
    what was sent to a paging tool - and the paging tool cannot know which
    monitor stamped it.

    Every holder rather than one, because some kinds have several: every
    firing of an alert group pages under the group's one key. Which of them a
    tool meant is the caller's to decide - from when each was going on, which
    is why each comes back whole - and a lookup that picked one would decide
    it by whichever row the database happened to read first.
    """
    with conn.cursor(row_factory=class_row(Incident)) as cursor:
        cursor.execute(
            "SELECT id, alert_payload, status, created_at, ended_at, trace_context "
            "  FROM incident "
            " WHERE id IN (SELECT incident_id FROM incident_reference "
            "               WHERE kind = %s AND value = ANY(%s))",
            (kind, list(values))
        )

        return cursor.fetchall()
