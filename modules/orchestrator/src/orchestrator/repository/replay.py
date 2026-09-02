from __future__ import annotations

import psycopg
from argus_core.replay import ReplayEntry
from psycopg.types.json import Jsonb

"""Where a call Argus made out of its own process is written down (spec §11.1).

`argus_core.replay` says what an entry is and how it is handed over; this is
the only thing that knows it ends up in Postgres. The same division as the
event stream, and for the same reason: the shared library cannot depend on the
module that owns the tables.

Writes here and touches nothing else, which is what leaves spec §7.1's
single-writer rule intact as this table arrives. The four domain tables keep
the one writer they had, `incident_event` has its own, and this has a third.
"""


def record(conn: psycopg.Connection, entry: ReplayEntry) -> None:
    """Writes one call down, and writes nothing else.

    Every field is a column rather than a payload with an index lifted out of
    it, which is where this parts company with `events.record`. An event is
    read whole by a page and its columns exist to find it by; an entry is read
    by a harness that aggregates over the columns themselves - latency across a
    run, calls per incident, one target against another. Only the two payloads
    stay opaque, because only they differ in shape from call to call.
    """
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO replay_log "
            "       (id, incident_id, call_type, target, request, response, "
            "        latency_ms, at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (
                entry.id,
                entry.incident_id,
                entry.call_type,
                entry.target,
                Jsonb(entry.request),
                Jsonb(entry.response),
                entry.latency_ms,
                entry.at,
            ),
        )
    conn.commit()


def get_by_incident(conn: psycopg.Connection, incident_id: str) -> list[ReplayEntry]:
    """Every call one incident made, in the order it made them.

    Ordered by `seq` rather than by `at`, as the event stream is: a loop takes
    several turns inside one second, and a conversation read back in whichever
    order two identical timestamps happened to sort is not a conversation.

    An incident that made no calls reads as an empty list rather than as
    nothing found. Escalating on retrieval alone never reaches a model, and
    that is a real path - a run with no calls is a fact about it, not a lookup
    that failed.
    """
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT id, incident_id, call_type, target, request, response, "
            "       latency_ms, at "
            "  FROM replay_log "
            " WHERE incident_id = %s "
            "ORDER BY seq",
            (incident_id,),
        )

        return [
            ReplayEntry(
                id=id,
                incident_id=incident_id,
                call_type=call_type,
                target=target,
                request=request,
                response=response,
                latency_ms=latency_ms,
                at=at,
            )
            for id, incident_id, call_type, target, request, response, latency_ms, at
            in cursor.fetchall()
        ]
