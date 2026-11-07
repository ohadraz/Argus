"""Where a finished incident's record is filed, before anything can search it.

The walk's one write to long-term memory, and a row rather than the store. A row
is a write the fence can refuse: a walk paused past its lease, its run taken back,
files nothing over the record of the walk that holds the run now. The store
would take that write from anybody, and its upsert keyed on the incident would
keep whichever walk wrote last.

So the store is filled from these rows, by a process of its own (`delivering`),
and is a view of them rather than a second record. Each row carries two
versions: the one filed, moved on whenever what was tried changes, and the one
the store last took. The difference is the work, the retry and the backlog - a
deliverer that was down finds everything it missed still waiting, and memory
switched on later finds every incident filed while it was off.
"""

from __future__ import annotations

import psycopg
from psycopg.types.json import Jsonb
from pydantic import BaseModel

from incident_memory.records import RememberedIncident


class Filed(BaseModel):
    """A record as it was filed, and which of its versions this is.

    The version travels with the record, because what a deliverer marks is the
    version it kept - and marking whatever the row says by the time the store
    answers would mark a record refiled in between as one the store holds.
    """

    record: RememberedIncident
    version: int


def file(conn: psycopg.Connection, record: RememberedIncident) -> None:
    """Files what this incident tried, for the store to be given.

    One row per incident, so a walk that was resumed files over its own record
    rather than beside it. A new version only where the record changed: a
    resume that composed the same record again owes the store nothing, and a
    version moved for it would embed and write the same record for every resume.
    """
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO incident_memory (incident_id, record)
            VALUES (%s, %s)
            ON CONFLICT (incident_id) DO UPDATE SET
                record = EXCLUDED.record,
                version = incident_memory.version + 1
            WHERE incident_memory.record IS DISTINCT FROM EXCLUDED.record
            """,
            (record.incident_id, Jsonb(record.model_dump(mode="json")))
        )

    conn.commit()


def get_undelivered(conn: psycopg.Connection, limit: int) -> list[Filed]:
    """The records the store does not hold yet, oldest first, at most `limit`.

    Oldest first, so a deliverer that fell behind catches up in the order the
    incidents ended. Bounded, so one pass embeds a batch and marks it before it
    starts on the next, rather than embedding everything before marking any.
    """
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT record, version
            FROM incident_memory
            WHERE delivered_version < version
            ORDER BY filed_at, incident_id
            LIMIT %s
            """,
            (limit,)
        )
        found = cursor.fetchall()

    return [
        Filed(record=RememberedIncident.model_validate(record), version=version)
        for record, version in found
    ]


def record_delivered(conn: psycopg.Connection, incident_id: str, version: int) -> None:
    """Records that the store holds this version of the incident's record.

    As far as `version` and no further, and never backwards. A record refiled
    after this version was read is a newer version the store has not seen, and
    it stays waiting; a mark arriving late for an older version changes nothing.
    """
    with conn.cursor() as cursor:
        cursor.execute(
            """
            UPDATE incident_memory SET delivered_version = %s
            WHERE incident_id = %s AND delivered_version < %s
            """,
            (version, incident_id, version)
        )

    conn.commit()
