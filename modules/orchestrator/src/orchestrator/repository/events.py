from __future__ import annotations

import psycopg
from argus_core.events import IncidentEvent, parse_event
from psycopg.types.json import Jsonb


def record(conn: psycopg.Connection, event: IncidentEvent) -> None:
    """Writes one published event down, and writes nothing else.

    The subscriber's whole job. It appends here and touches no incident,
    hypothesis, action or timeline row, which is what leaves spec §7.1's
    single-writer rule intact as this table arrives: the incident's own state
    keeps the one writer it already had, and the account gets one of its own.

    The event is stored whole in `payload`; `kind`, `at` and `incident_id` are
    lifted out beside it because they are what the table is read by. Nothing
    reconstructs an event from those columns - `payload` is the record, and
    they are its index.
    """
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO incident_event (id, incident_id, kind, at, payload) "
            "VALUES (%s, %s, %s, %s, %s)",
            (
                event.id,
                event.incident_id,
                event.kind,
                event.at,
                Jsonb(event.model_dump(mode="json")),
            ),
        )
    conn.commit()


def get_by_incident(conn: psycopg.Connection, incident_id: str) -> list[IncidentEvent]:
    """One incident's account, in the order it was published.

    Ordered by `seq` rather than by `at`: two events can share a moment to the
    microsecond, and the order the narration is read in has to be the order
    things happened in rather than whichever of two identical timestamps a sort
    happened to put first.

    Each row comes back as the type it was published as, so a reader holds a
    `LogsRetrieved` rather than a dictionary it has to match on strings to
    interpret.
    """
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT payload "
            "  FROM incident_event "
            " WHERE incident_id = %s "
            "ORDER BY seq",
            (incident_id,),
        )
        return [parse_event(row[0]) for row in cursor.fetchall()]
