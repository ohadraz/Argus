"""What other tools call an incident, given and found again.

A chat platform's thread and offers, a paging tool's incident and keys, a
monitor's firings: each tool's later word about an incident arrives carrying
its own names for it and none of Argus's. This is the one role that gives an
incident those names and finds incidents by them, for every process that hears
from such a tool - the relay, the walk's sources and the web application alike.

Built two ways, as `IncidentReads` is: `incident_names_on` on a connection its
caller holds and commits, and `incident_names_over` for a caller holding only
where connections come from, each call its own unit of work. Neither opens
anything when it is built.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

import psycopg
from core.models import IncidentStanding, RecordedReference, Reference
from postgres import Connections, unit_of_work

from incident_record.repository import references


class IncidentNames(Protocol):
    """What other tools call an incident."""

    def give(self, incident_id: str, names: Iterable[Reference], /) -> None:
        """Gives the incident these names, leaving any name already held where
        it is."""
        ...

    def values_for(self, incident_id: str, kind: str, /) -> list[str]:
        """Every name of this kind the incident is known by."""
        ...

    def first_of_kind(self, incident_id: str, kind: str, /) -> RecordedReference | None:
        """The first name of this kind the incident was given, and when."""
        ...

    def incidents_known_as(self, kind: str, values: Iterable[str], /) -> list[IncidentStanding]:
        """Every incident holding any of these names of this kind - from any
        source, since a paging tool cannot know which monitor stamped a key."""
        ...


class _OnAConnection:
    """The names, on a connection somebody else holds and commits."""

    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def give(self, incident_id: str, names: Iterable[Reference], /) -> None:
        references.add(self._conn, incident_id, names)

    def values_for(self, incident_id: str, kind: str, /) -> list[str]:
        return references.get_values_for(self._conn, incident_id, kind)

    def first_of_kind(self, incident_id: str, kind: str, /) -> RecordedReference | None:
        return references.get_first_by_kind(self._conn, incident_id, kind)

    def incidents_known_as(self, kind: str, values: Iterable[str], /) -> list[IncidentStanding]:
        return references.get_incidents_by_values(self._conn, kind, values)


class _OverConnections:
    """The names, each call on a connection of its own from `connections`."""

    def __init__(self, connections: Connections) -> None:
        self._connections = connections

    def give(self, incident_id: str, names: Iterable[Reference], /) -> None:
        with unit_of_work(self._connections) as conn:
            incident_names_on(conn).give(incident_id, names)

    def values_for(self, incident_id: str, kind: str, /) -> list[str]:
        with self._connections() as conn:
            return incident_names_on(conn).values_for(incident_id, kind)

    def first_of_kind(self, incident_id: str, kind: str, /) -> RecordedReference | None:
        with self._connections() as conn:
            return incident_names_on(conn).first_of_kind(incident_id, kind)

    def incidents_known_as(self, kind: str, values: Iterable[str], /) -> list[IncidentStanding]:
        with self._connections() as conn:
            return incident_names_on(conn).incidents_known_as(kind, values)


def incident_names_on(conn: psycopg.Connection) -> IncidentNames:
    """The incident's names, on `conn`, which the caller holds and commits."""
    return _OnAConnection(conn)


def incident_names_over(connections: Connections) -> IncidentNames:
    """The incident's names for a caller holding only where connections come
    from - each call on a connection of its own, none opened until asked."""
    return _OverConnections(connections)
