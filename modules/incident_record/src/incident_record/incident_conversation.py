"""The incident's conversation: what people wrote in its thread, and what Argus
made of each message.

The reader of people's messages writes what it understood a message to mean,
who wrote it and what it offered them, and asks which messages nobody has
understood yet; the web application finds the message a press answers. What the
Investigator made of a lead is the walk's own write (`TheWalksWrites`), and the
leads themselves are read with the rest of the incident (`IncidentReads`).

Built two ways, as `IncidentReads` is: `incident_conversation_on` on a
connection its caller holds and commits, and `incident_conversation_over` for a
caller holding only where connections come from, each write its own unit of
work. Neither opens anything when it is built.
"""

from __future__ import annotations

from typing import Protocol

import psycopg
from core.models import Meaning, OfferedEnding, Reference, ThreadMessage
from postgres import Connections, unit_of_work

from incident_record.repository import conversation


class IncidentConversation(Protocol):
    """What people wrote in an incident's thread, as Argus keeps it."""

    def understood(self, message: Reference, meaning: Meaning, /) -> None:
        """Keeps what the message was understood to mean."""
        ...

    def named(self, message: Reference, person_name: str | None, /) -> None:
        """Keeps what the person who wrote the message is called."""
        ...

    def offered(self, message: Reference, ending: OfferedEnding, /) -> None:
        """Keeps the ending the message was offered."""
        ...

    def message(self, message: Reference, /) -> ThreadMessage | None:
        """The message by its own name, where one was written."""
        ...

    def not_understood(self, limit: int, /) -> list[ThreadMessage]:
        """Up to `limit` messages nobody has understood yet, oldest first."""
        ...


class _OnAConnection:
    """The conversation, on a connection somebody else holds and commits."""

    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def understood(self, message: Reference, meaning: Meaning, /) -> None:
        conversation.understood(self._conn, message, meaning)

    def named(self, message: Reference, person_name: str | None, /) -> None:
        conversation.named(self._conn, message, person_name)

    def offered(self, message: Reference, ending: OfferedEnding, /) -> None:
        conversation.offered(self._conn, message, ending)

    def message(self, message: Reference, /) -> ThreadMessage | None:
        return conversation.get(self._conn, message)

    def not_understood(self, limit: int, /) -> list[ThreadMessage]:
        return conversation.get_not_understood(self._conn, limit)


class _OverConnections:
    """The conversation, each call on a connection of its own from
    `connections` - every write its own unit of work."""

    def __init__(self, connections: Connections) -> None:
        self._connections = connections

    def understood(self, message: Reference, meaning: Meaning, /) -> None:
        with unit_of_work(self._connections) as conn:
            incident_conversation_on(conn).understood(message, meaning)

    def named(self, message: Reference, person_name: str | None, /) -> None:
        with unit_of_work(self._connections) as conn:
            incident_conversation_on(conn).named(message, person_name)

    def offered(self, message: Reference, ending: OfferedEnding, /) -> None:
        with unit_of_work(self._connections) as conn:
            incident_conversation_on(conn).offered(message, ending)

    def message(self, message: Reference, /) -> ThreadMessage | None:
        with self._connections() as conn:
            return incident_conversation_on(conn).message(message)

    def not_understood(self, limit: int, /) -> list[ThreadMessage]:
        with self._connections() as conn:
            return incident_conversation_on(conn).not_understood(limit)


def incident_conversation_on(conn: psycopg.Connection) -> IncidentConversation:
    """The incident's conversation, on `conn`, which the caller holds and
    commits."""
    return _OnAConnection(conn)


def incident_conversation_over(connections: Connections) -> IncidentConversation:
    """The incident's conversation for a caller holding only where connections
    come from - each call on a connection of its own, none opened until
    asked."""
    return _OverConnections(connections)
