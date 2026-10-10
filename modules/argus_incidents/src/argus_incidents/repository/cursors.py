"""Where each reader of the event log got to, kept so that a restart resumes.

Here beside the log it points into because more than one process follows the
log - the relay telling Slack, the intent agent understanding what people
wrote - and each is an agent that may not know another. A place kept inside one of them is
a place the other has to reimplement.

One row per reader, so each reader keeps its own pace, and the slower of two
never decides what the faster has already done.

Committing is the caller's, as in every repository here. A reader that acts
and then moves on wants both in whatever transaction it decides is one unit of
work, and committing here would take the choice away.
"""

from __future__ import annotations

import psycopg

# Where the log starts, and what a reader that has never looked is told. Zero
# rather than null so that no caller has to decide what "nowhere" means - one
# of them would decide it meant "now", which silently drops everything
# published before that reader first ran.
_THE_BEGINNING = 0


def get(conn: psycopg.Connection, reader: str) -> int:
    """The place a reader got to, or the beginning of the log if it never has.

    A bare `get` because `reader` is the identity: one row per reader, looked
    up by the name it delivers under.
    """
    with conn.cursor() as cursor:
        cursor.execute("SELECT seq FROM event_cursor WHERE reader = %s", (reader,))
        row = cursor.fetchone()

        return int(row[0]) if row is not None else _THE_BEGINNING


def advance(conn: psycopg.Connection, reader: str, seq: int) -> None:
    """Moves a reader on to the place it has now dealt with, and never back.

    Never back is the whole of the second clause. A batch delivered twice, or
    two relays running under one name, would otherwise wind the place backwards
    and say an hour of an incident over again. Delivery is at-least-once
    because a silent miss is worse than a repeat - but a repeat this can
    prevent is one it should.

    One statement rather than a read and a write, so that two readers of one
    name racing cannot both read the old place and both write from it.
    """
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO event_cursor (reader, seq) "
            "VALUES (%s, %s) "
            "ON CONFLICT (reader) DO UPDATE "
            "   SET seq = GREATEST(event_cursor.seq, EXCLUDED.seq), "
            "       updated_at = now()",
            (reader, seq)
        )
