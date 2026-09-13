from __future__ import annotations

from argus_core.db import Connections
from argus_incidents.repository import events
from argus_incidents.repository.events import RecordedEvent

from agent_communicator.relaying import SLACK_RELAY, Backlog, Place
from agent_communicator.repository import cursors

"""The relay's log and its place, plugged into the database they live in.

`relaying` says what a relay does; this says where it reads from. The whole of
the module's contact with a connection, and it writes no SQL of its own: the
repositories in `argus_incidents` own the tables, and this asks them.

A connection per call rather than one held open. A relay spends almost all of
its life asleep between looks, and a connection held across that is a
transaction-less session pinning a snapshot for nothing - which for this reader
is worse than idle, because a reader holding an old transaction cannot see what
has committed since (`events.get_since`).
"""


def events_since(connections: Connections) -> Backlog:
    """The log, read through the repository that owns it.

    A function returning one rather than a function taking both, for the reason
    `publishing.events_into` works that way: what the relay depends on is a
    backlog - a place and a batch - and the database has no business appearing
    in the signature of the thing that decides what gets said.
    """

    def read_since(since: int, batch: int, /) -> list[RecordedEvent]:
        with connections() as conn:
            return events.get_since(conn, since, batch)

    return read_since


def place_for(connections: Connections, reader: str = SLACK_RELAY) -> Place:
    """Where this reader got to, kept in the row that outlives it."""
    return _AKeptPlace(connections, reader)


class _AKeptPlace:
    """A place in the log, read and moved through the cursor repository.

    A class rather than two functions because the two halves are one thing: a
    reader that could be asked where it is without being able to move, or the
    other way round, is half a bookmark.
    """

    def __init__(self, connections: Connections, reader: str) -> None:
        self._connections = connections
        self._reader = reader

    def where(self) -> int:
        with self._connections() as conn:
            return cursors.get(conn, self._reader)

    def move_to(self, seq: int, /) -> None:
        """Moves the place on, and commits it before the next line is said.

        Its own transaction, deliberately: the relay delivers and then records
        that it delivered, and a place still sitting uncommitted when the next
        delivery fails is a place that never moved at all.
        """
        with self._connections() as conn:
            cursors.advance(conn, self._reader, seq)
