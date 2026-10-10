"""Following the event log: what has been published since a place, and the
place itself, kept in the row that outlives the reader.

Every process that follows the log reads it through these two seams - the
relay telling Slack, the intent agent understanding what people wrote - and
neither knows the other exists. Here rather than in either, because they are agents that may not
know each other, and the seams are a fact about the log rather than about what
any one reader does with it.

A connection per call rather than one held open. A reader spends almost all of
its life asleep between looks, and a connection held across that is a
transaction-less session pinning a snapshot for nothing - which for a reader is
worse than idle, because a reader holding an old transaction cannot see what
has committed since (`events.get_since`).
"""

from __future__ import annotations

from typing import Protocol

from argus_core import Connections
from argus_core.events import RecordedEvent

from argus_incidents.repository import cursors, events


class Backlog(Protocol):
    """What has been published since a place, oldest first and capped.

    A reader's whole view of the log: no incident to ask about, because a
    reader follows everything rather than watching one thing.
    """

    def __call__(self, since: int, batch: int, /) -> list[RecordedEvent]: ...


class Place(Protocol):
    """Where a reader got to, kept somewhere that outlives the process.

    Two methods rather than a value passed in and out, because the keeping is
    the point: a reader that returned its new place and trusted its caller to
    store it would lose everything the moment a caller forgot.
    """

    def where(self) -> int: ...

    def move_to(self, seq: int, /) -> None: ...


def events_since(connections: Connections) -> Backlog:
    """The log, read through the repository that owns it.

    A function returning one rather than a function taking both, for the reason
    `publishing.events_into` works that way: what a reader depends on is a
    backlog - a place and a batch - and the database has no business appearing
    in the signature of the thing that decides what to do with what it read.
    """

    def read_since(since: int, batch: int, /) -> list[RecordedEvent]:
        with connections() as conn:
            return events.get_since(conn, since, batch)

    return read_since


def place_for(connections: Connections, reader: str) -> Place:
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
        """Moves the place on, and commits it before the next event is dealt
        with.

        Its own transaction, deliberately: a reader acts and then records that
        it acted, and a place still sitting uncommitted when the next action
        fails is a place that never moved at all.
        """
        with self._connections() as conn:
            cursors.advance(conn, self._reader, seq)
