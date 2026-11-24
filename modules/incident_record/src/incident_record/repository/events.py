from __future__ import annotations

from typing import Any

import psycopg
from core.events import IncidentEvent, RecordedEvent, UnreadableEvent, parse_stored_event
from core.stored import SHIPPED, Shapes, Unreadable
from psycopg.types.json import Jsonb

# `RecordedEvent` and `UnreadableEvent` are kernel contracts, named here as well
# because this is the table they are read from and every caller of `get_since`
# already has this module open. The relay that follows the log names them from
# the kernel instead - it has no business holding a repository to hold a row.
__all__ = ["RecordedEvent", "UnreadableEvent", "get_by_incident", "get_since", "record"]


def record(conn: psycopg.Connection, event: IncidentEvent) -> None:
    """Writes one published event down, and writes nothing else.

    The subscriber's whole job. It appends here and touches no incident,
    hypothesis, action or timeline row, which is what leaves spec §7.1's
    single-writer rule intact as this table arrives: the incident's own state
    keeps the one writer it already had, and the account gets one of its own.

    The event is stored whole in `payload`; `kind`, `at` and `incident_id` are
    lifted out beside it because they are what the table is read by. Nothing
    reconstructs an event from those columns - `payload` is the record, and
    they are its index. Beside it too, the shape its kind is written in now,
    which is what a later release reads it as.

    Committing is the caller's, not this function's. An event is written either
    beside the decision it narrates - on that decision's own connection, so the
    two are one write - or on a connection opened for it alone, which commits
    when the block that opened it ends. Committing here would make the first of
    those impossible.
    """
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO incident_event (id, incident_id, kind, at, shape, payload) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (
                event.id,
                event.incident_id,
                event.kind,
                event.at,
                SHIPPED.current(event.kind),
                Jsonb(event.model_dump(mode="json"))
            )
        )


def get_since(conn: psycopg.Connection,
              seq: int,
              limit: int,
              shapes: Shapes = SHIPPED) -> list[RecordedEvent | UnreadableEvent]:
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

    An event that cannot be read comes back as what stopped it, in its place,
    rather than failing the batch - one bad row would otherwise hold back
    every event behind it for good. Whether to move past it is the reader's:
    one a newer release wrote is newer, and is not lost by waiting for it.
    """
    with conn.cursor() as cursor:
        cursor.execute(
            # `xmin` is the transaction that wrote the row; `pg_snapshot_xmin`
            # is the oldest transaction still in flight. Compared as numbers
            # because they are not the same type - a row's `xid` carries no
            # epoch and the snapshot's `xid8` does, which is a difference that
            # matters once the counter has wrapped around and never here.
            "SELECT seq, incident_id, kind, shape, payload "
            "  FROM incident_event "
            " WHERE seq > %s "
            "   AND xmin::text::bigint "
            "       < pg_snapshot_xmin(pg_current_snapshot())::text::bigint "
            "ORDER BY seq "
            " LIMIT %s",
            (seq, limit)
        )
        rows = cursor.fetchall()

    return [_recorded(seq_of_row, str(incident_id), kind, shape, payload, shapes)
            for seq_of_row, incident_id, kind, shape, payload in rows]


def get_by_incident(conn: psycopg.Connection,
                    incident_id: str,
                    shapes: Shapes = SHIPPED) -> list[IncidentEvent]:
    """One incident's account, in the order it was published.

    Ordered by `seq` rather than by `at`: two events can share a moment to the
    microsecond, and the order the narration is read in has to be the order
    things happened in rather than whichever of two identical timestamps a sort
    happened to put first.

    Each row comes back as the type it was published as, so a reader holds a
    `LogsRetrieved` rather than a dictionary it has to match on strings to
    interpret - brought up to the shape its kind is at now.

    Raises where a row cannot be read, or was written by a newer release: one
    incident's account read in part would be told wrong.
    """
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT kind, shape, payload "
            "  FROM incident_event "
            " WHERE incident_id = %s "
            "ORDER BY seq",
            (incident_id,)
        )
        return [parse_stored_event(kind, shape, payload, shapes)
                for kind, shape, payload in cursor.fetchall()]


def _recorded(seq: int,
              incident_id: str,
              kind: str,
              shape: int,
              payload: dict[str, Any],
              shapes: Shapes) -> RecordedEvent | UnreadableEvent:
    """The event at `seq`, or what stopped it being read.

    Any failure, not a list of them: bringing a row up runs steps written for
    whatever an older release stored, and what one of them raises over a row
    it was not written for is not known in advance.
    """
    try:
        return RecordedEvent(seq=seq, event=parse_stored_event(kind, shape, payload, shapes))
    except Exception as failure:
        return UnreadableEvent(seq=seq, incident_id=incident_id,
                               unreadable=Unreadable.of(failure))
