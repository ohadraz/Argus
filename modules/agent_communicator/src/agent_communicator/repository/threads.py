from __future__ import annotations

import psycopg

"""Which Slack conversation an incident is being told in.

Slack has no thread id: a reply names the timestamp of the message it is
replying to. So an incident's first message is its thread, and every line after
it has to find that timestamp again - in another pass, another process, another
day, which is why it is a row and not something held in memory.

Committing is the caller's, as in every repository here.
"""


def get(conn: psycopg.Connection, incident_id: str, channel: str) -> str | None:
    """The thread this incident is being told in, or nothing if it has none.

    A bare `get` because the pair is the identity: one conversation per
    incident per channel, looked up by both halves of its key.

    Nothing rather than an error for an incident nobody has posted about. That
    is the ordinary state of every incident until its first message lands, and
    the caller reads it as "open one" - raising would make the commonest path
    the exceptional one.
    """
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT ts "
            "  FROM slack_thread "
            " WHERE incident_id = %s "
            "   AND channel = %s",
            (incident_id, channel)
        )
        row = cursor.fetchone()

        return str(row[0]) if row is not None else None


def remember(conn: psycopg.Connection,
             incident_id: str,
             channel: str,
             ts: str) -> None:
    """Records the conversation an incident was opened in, once and for good.

    A second opening message - two relays at once, a pass repeated after a
    crash - writes nothing and leaves the first thread standing. The duplicate
    message is the price of at-least-once delivery; scattering the rest of the
    incident into a conversation nobody is reading is not, and that is what
    replacing the thread would do.
    """
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO slack_thread (incident_id, channel, ts) "
            "VALUES (%s, %s, %s) "
            "ON CONFLICT (incident_id, channel) DO NOTHING",
            (incident_id, channel, ts)
        )
