from __future__ import annotations

import psycopg
from argus_core.events import IncidentEvent, parse_event
from psycopg.types.json import Jsonb
from pydantic import BaseModel


class RecordedEvent(BaseModel):
    """One event as the log holds it: what was published, and where it sits.

    The place travels with the event because a reader following the log has to
    keep it. Where `get_by_incident` answers a question about an incident -
    whose answer is complete the moment it is given - a relay's question is
    "what has happened since", and the only thing that can be asked again is
    the place it got to.
    """

    seq: int
    event: IncidentEvent


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

    Committing is the caller's, not this function's. An event is written either
    beside the decision it narrates - on that decision's own connection, so the
    two are one write - or on a connection opened for it alone, which commits
    when the block that opened it ends. Committing here would make the first of
    those impossible.
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
                Jsonb(event.model_dump(mode="json"))
            )
        )


def get_since(conn: psycopg.Connection, seq: int, limit: int) -> list[RecordedEvent]:
    """What has been published since a reader last looked, oldest first.

    Across every incident rather than within one, because what reads this is
    following the log itself: a relay delivering an incident's account
    somewhere else has no incident in hand to ask about, only the place it got
    to last time.

    Oldest first and capped at `limit`, which is the same decision twice: a
    reader that has fallen an hour behind catches up a batch at a time, and it
    catches up in the order things happened, so that stopping halfway leaves it
    behind rather than leaves a hole. `seq` is exclusive - a reader hands back
    the place of the last event it dealt with, and gets what follows it.

    An event whose transaction has not landed holds back everything behind it,
    and that is the whole reason for the second condition. A place is handed
    out when a row is inserted and the row becomes visible when its transaction
    commits: a walk publishing inside its decision's transaction can hold place
    10 while the intake endpoint commits place 11 on its own connection. A
    reader that delivered 11 would move its cursor past a line nobody would
    ever see - and a line silently missed is the one failure a relay exists to
    prevent, where a line delivered late costs nothing.

    So a row is only old enough to read once no transaction older than it can
    still commit. The reader should not be holding a write transaction of its
    own while it asks: its own place would be the oldest in flight, and it
    would hold back everything published after it started.
    """
    with conn.cursor() as cursor:
        cursor.execute(
            # `xmin` is the transaction that wrote the row; `pg_snapshot_xmin`
            # is the oldest transaction still in flight. Compared as numbers
            # because they are not the same type - a row's `xid` carries no
            # epoch and the snapshot's `xid8` does, which is a difference that
            # matters once the counter has wrapped around and never here.
            "SELECT seq, payload "
            "  FROM incident_event "
            " WHERE seq > %s "
            "   AND xmin::text::bigint "
            "       < pg_snapshot_xmin(pg_current_snapshot())::text::bigint "
            "ORDER BY seq "
            " LIMIT %s",
            (seq, limit)
        )
        return [
            RecordedEvent(seq=seq_of_row, event=parse_event(payload))
            for seq_of_row, payload in cursor.fetchall()
        ]


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
            (incident_id,)
        )
        return [parse_event(row[0]) for row in cursor.fetchall()]
