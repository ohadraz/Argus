"""Where a finished incident's record is filed, before anything can search it.

The walk's one write to long-term memory, and a row rather than the store. A row
is a write the fence can refuse: a walk paused past its lease, its run taken back,
files nothing over the record of the walk that holds the run now. The store
would take that write from anybody, and its upsert keyed on the incident would
keep whichever walk wrote last.

So the store is filled from these rows, by a process of its own (`delivering`),
and is a view of them rather than a second record. Each row carries the version
filed, moved on whenever what was tried changes, and beside it each collection
marks the version it last took. The difference is the work, the retry and the
backlog - a deliverer that was down finds everything it missed still waiting,
and memory switched on later finds every incident filed while it was off.

A mark per embedding model, because each model is a collection of its own
(`core.embedding.collection_for`). A model switched to finds every record
waiting for its collection, and one switched back to finds its own collection
where it left it. One mark shared between two would have two deliverers on two
models - as an upgrade runs them - each re-deliver every record the other had
just marked.

Each row says the shape its record was written in (`core.stored`). A deliverer
takes only the shapes it knows - one a newer release wrote waits for a
deliverer that knows it - and brings an older one up before it reads it. One
at a shape it knows that it still cannot read is parked (`park`) rather than
stopping every pass - under the deliverer that parked it, which passes over it
from then on. Every other deliverer still tries it, so the one a later release
starts, which may hold the step it needed, delivers it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import psycopg
from core.stored import REMEMBERED_INCIDENT, SHIPPED, Shapes, Unreadable, up_to_date
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


@dataclass(frozen=True)
class UnreadableRecord:
    """A filed record a deliverer could not bring up, and whose it is - which
    is what parking it needs."""

    incident_id: str
    unreadable: Unreadable


def file(conn: psycopg.Connection, record: RememberedIncident) -> None:
    """Files what this incident tried, for the store to be given.

    One row per incident, so a walk that was resumed files over its own record
    rather than beside it. A new version only where the record changed: a
    resume that composed the same record again owes the store nothing, and a
    version moved for it would embed and write the same record for every resume.

    Changed means its JSON or the shape it is written in. A record filed again
    by a release that writes another shape is a new version even where its JSON
    matches, and is delivered again - harmless, and the only way the row never
    holds new data under an old shape. Filing again clears a park as well, for
    every deliverer: the record parked is not the record there now.
    """
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO incident_memory (incident_id, record, shape)
            VALUES (%s, %s, %s)
            ON CONFLICT (incident_id) DO UPDATE SET
                record = EXCLUDED.record,
                shape = EXCLUDED.shape,
                parked_by = NULL,
                version = incident_memory.version + 1
            WHERE (incident_memory.record, incident_memory.shape)
                  IS DISTINCT FROM (EXCLUDED.record, EXCLUDED.shape)
            """,
            (record.incident_id, Jsonb(record.model_dump(mode="json")),
             SHIPPED.current(REMEMBERED_INCIDENT))
        )

    conn.commit()


def get_undelivered(conn: psycopg.Connection,
                    limit: int,
                    *,
                    deliverer: str,
                    embedded_with: str,
                    shapes: Shapes = SHIPPED) -> list[Filed | UnreadableRecord]:
    """The records the collection `embedded_with` builds does not hold yet,
    oldest first, at most `limit`.

    Oldest first, so a deliverer that fell behind catches up in the order the
    incidents ended. Bounded, so one pass embeds a batch and marks it before it
    starts on the next, rather than embedding everything before marking any.

    Only those at a shape `shapes` knows, and not parked by `deliverer`: a
    record a newer release wrote waits for a deliverer that knows it, and one
    another deliverer parked is tried again by this one. One that cannot be
    brought up comes back as what stopped it, in its place, for the caller to
    park - this reads, and writes nothing.
    """
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT filed.incident_id, filed.record, filed.shape, filed.version
            FROM incident_memory AS filed
            LEFT JOIN incident_memory_delivery AS taken
              ON taken.incident_id = filed.incident_id AND taken.embedded_with = %s
            WHERE COALESCE(taken.delivered_version, 0) < filed.version
              AND filed.parked_by IS DISTINCT FROM %s
              AND filed.shape <= %s
            ORDER BY filed.filed_at, filed.incident_id
            LIMIT %s
            """,
            (embedded_with, deliverer, shapes.current(REMEMBERED_INCIDENT), limit)
        )
        found = cursor.fetchall()

    return [_filed(str(incident_id), record, shape, version, shapes)
            for incident_id, record, shape, version in found]


def park(conn: psycopg.Connection, incident_id: str, deliverer: str) -> None:
    """Leaves the incident's record out of every pass `deliverer` makes, until
    it is filed anew.

    That deliverer's alone. Every release starts a deliverer of its own, so the
    one that adds the step a parked record needed - or mends one under the
    same shape - delivers what an older one parked, with no step of its own to
    put the parks back. A park moves to whichever deliverer made it last: one
    that a second deliverer cannot read either is that one's to pass over now.
    """
    with conn.cursor() as cursor:
        cursor.execute(
            "UPDATE incident_memory SET parked_by = %s WHERE incident_id = %s",
            (deliverer, incident_id)
        )

    conn.commit()


def record_delivered(conn: psycopg.Connection,
                     incident_id: str,
                     version: int,
                     embedded_with: str) -> None:
    """Records that the collection `embedded_with` builds holds this version of
    the incident's record.

    As far as `version` and no further, and never backwards. A record refiled
    after this version was read is a newer version the store has not seen, and
    it stays waiting; a mark arriving late for an older version changes nothing.
    That collection's mark alone: what another model's collection holds is
    another question.
    """
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO incident_memory_delivery (incident_id, embedded_with, delivered_version)
            VALUES (%s, %s, %s)
            ON CONFLICT (incident_id, embedded_with) DO UPDATE SET
                delivered_version = EXCLUDED.delivered_version
            WHERE incident_memory_delivery.delivered_version < EXCLUDED.delivered_version
            """,
            (incident_id, embedded_with, version)
        )

    conn.commit()


def _filed(incident_id: str,
           record: Any,
           shape: int,
           version: int,
           shapes: Shapes) -> Filed | UnreadableRecord:
    """The record a row holds, brought up to date, or what stopped it.

    Any failure, not a list of them: bringing a row up runs steps written for
    whatever an older release stored, and what one of them raises over a row
    it was not written for is not known in advance.
    """
    try:
        brought_up = up_to_date(REMEMBERED_INCIDENT, shape, record, shapes)

        return Filed(record=RememberedIncident.model_validate(brought_up), version=version)
    except Exception as failure:
        return UnreadableRecord(incident_id=incident_id, unreadable=Unreadable.of(failure))
