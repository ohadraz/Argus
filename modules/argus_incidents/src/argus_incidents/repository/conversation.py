"""What people wrote in an incident's thread, kept as part of its record.

The one input to an incident Argus did not produce. The event log says it
arrived; this is where whatever decides on it - the wait, the press, the agents
a lead reaches - reads it, because an account that could change an outcome
would be a participant (`argus_core.events`).

A message is written once. The chat platform retries a delivery it believes
went unanswered, and its own name for the message is the row's key, so the
second write writes nothing and says so.
"""

from __future__ import annotations

from typing import Any

import psycopg
from argus_core.models import (
    Meaning,
    Offer,
    OfferedEnding,
    Reference,
    Standing,
    ThreadMessage,
    Weighing,
)

_COLUMNS = ("incident_id, source, kind, value, person_id, person_name, text, written_at, "
            "meaning, offered_ending, offer_expired, standing, standing_reason")


def write(conn: psycopg.Connection, written: ThreadMessage) -> bool:
    """Records the message, and says whether this was the write that recorded
    it.

    No commit: the message and the account of its arrival are one transaction,
    or a crash between them leaves one without the other.
    """
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO thread_message "
            "    (incident_id, source, kind, value, person_id, text, written_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT DO NOTHING",
            (written.incident_id,
             written.message.source,
             written.message.kind,
             written.message.value,
             written.person_id,
             written.text,
             written.written_at)
        )

        return cursor.rowcount == 1


def understood(conn: psycopg.Connection, message: Reference, meaning: Meaning) -> None:
    """Records what the message was understood to mean, and commits.

    Committed here, unlike the write: nothing is written with it, and the
    account of it is published after, where a failure costs the timeline a
    line and the record nothing.
    """
    with conn.cursor() as cursor:
        cursor.execute(
            "UPDATE thread_message SET meaning = %s "
            " WHERE source = %s AND kind = %s AND value = %s",
            (meaning, message.source, message.kind, message.value)
        )

    conn.commit()


def named(conn: psycopg.Connection, message: Reference, person_name: str | None) -> None:
    """Records what the chat platform calls the message's writer, or that it
    could not say, and commits - for `understood`'s reason."""
    with conn.cursor() as cursor:
        cursor.execute(
            "UPDATE thread_message SET person_name = %s "
            " WHERE source = %s AND kind = %s AND value = %s",
            (person_name, message.source, message.kind, message.value)
        )

    conn.commit()


def offered(conn: psycopg.Connection, message: Reference, ending: OfferedEnding) -> None:
    """Records that the message's writer was offered this ending, and commits -
    for `understood`'s reason."""
    with conn.cursor() as cursor:
        cursor.execute(
            "UPDATE thread_message SET offered_ending = %s "
            " WHERE source = %s AND kind = %s AND value = %s",
            (ending, message.source, message.kind, message.value)
        )

    conn.commit()


def expired(conn: psycopg.Connection, message: Reference) -> None:
    """Records that the offer made on this message has expired, and commits -
    for `understood`'s reason."""
    with conn.cursor() as cursor:
        cursor.execute(
            "UPDATE thread_message SET offer_expired = true "
            " WHERE source = %s AND kind = %s AND value = %s",
            (message.source, message.kind, message.value)
        )

    conn.commit()


def weighed(conn: psycopg.Connection, message: Reference, weighing: Weighing) -> None:
    """Records what the Investigator made of a lead, in place of anything it
    made of it before, and commits - for `understood`'s reason."""
    with conn.cursor() as cursor:
        cursor.execute(
            "UPDATE thread_message SET standing = %s, standing_reason = %s "
            " WHERE source = %s AND kind = %s AND value = %s",
            (weighing.standing, weighing.reason,
             message.source, message.kind, message.value)
        )

    conn.commit()


def get(conn: psycopg.Connection, message: Reference) -> ThreadMessage | None:
    """The message the chat platform calls by this name, or `None`."""
    with conn.cursor() as cursor:
        cursor.execute(
            f"SELECT {_COLUMNS} FROM thread_message "
            " WHERE source = %s AND kind = %s AND value = %s",
            (message.source, message.kind, message.value)
        )
        row = cursor.fetchone()

    return _a_message_from(row) if row is not None else None


def get_all_by_incident(conn: psycopg.Connection, incident_id: str) -> list[ThreadMessage]:
    """Everything people wrote in this incident's thread, in the order they
    wrote it."""
    with conn.cursor() as cursor:
        cursor.execute(
            f"SELECT {_COLUMNS} FROM thread_message "
            " WHERE incident_id = %s "
            " ORDER BY written_at, source, kind, value",
            (incident_id,)
        )

        return [_a_message_from(row) for row in cursor.fetchall()]


def get_leads_by_incident(conn: psycopg.Connection, incident_id: str) -> list[ThreadMessage]:
    """This incident's leads - what people told it as information - in the
    order they wrote them."""
    with conn.cursor() as cursor:
        cursor.execute(
            f"SELECT {_COLUMNS} FROM thread_message "
            " WHERE incident_id = %s AND meaning = %s "
            " ORDER BY written_at, source, kind, value",
            (incident_id, Meaning.INFORMATION)
        )

        return [_a_message_from(row) for row in cursor.fetchall()]


def get_not_understood(conn: psycopg.Connection, limit: int) -> list[ThreadMessage]:
    """Up to `limit` messages nobody has understood yet, in every incident,
    oldest first.

    In the order people wrote them, because a message understood out of order
    can be offered after a later one that changed it.
    """
    with conn.cursor() as cursor:
        cursor.execute(
            f"SELECT {_COLUMNS} FROM thread_message "
            " WHERE meaning IS NULL "
            " ORDER BY written_at, source, kind, value "
            " LIMIT %s",
            (limit,)
        )

        return [_a_message_from(row) for row in cursor.fetchall()]


def _a_message_from(row: tuple[Any, ...]) -> ThreadMessage:
    """One row, in the order `_COLUMNS` names them, as the message it is."""
    (incident_id, source, kind, value, person_id, person_name, text, written_at, meaning,
     offered_ending, offer_expired, standing, standing_reason) = row

    return ThreadMessage(incident_id=str(incident_id),
                         message=Reference(source=source, kind=kind, value=value),
                         person_id=person_id,
                         person_name=person_name,
                         text=text,
                         written_at=written_at,
                         meaning=Meaning(meaning) if meaning is not None else None,
                         # Validated rather than constructed, so a stored ending
                         # no press can bring about is refused on the way out.
                         offer=(Offer.model_validate({"ending": offered_ending,
                                                      "expired": offer_expired})
                                if offered_ending is not None else None),
                         weighing=(Weighing(standing=Standing(standing), reason=standing_reason)
                                   if standing is not None else None))
