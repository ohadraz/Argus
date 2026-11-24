"""What there is to read about one incident, read at one moment.

Every reader that composes an answer about an incident - the postmortem's
evidence, the incident's page, the walk asking what an earlier attempt staked -
reads it through this one role, so that what it reads is one incident and, on
one connection, one moment: its row, its account, its candidates, its actions,
what people told it, its write-ups and what its walk spent.

Built two ways, because readers hold two things. `incident_reads_on` reads on
a connection its caller already holds, so several reads describe the same
moment and nothing here commits; `incident_reads_over` is for a caller that
holds only where connections come from, and asks one question at a time, each
on a connection of its own. Neither opens anything when it is built.
"""

from __future__ import annotations

from typing import Protocol

import psycopg
from core.events import IncidentEvent
from core.models import (
    ExecutiveSynopsis,
    Hypothesis,
    Incident,
    Postmortem,
    TakenAction,
    ThreadMessage,
)
from postgres import Connections

from incident_record.repository import (
    conversation,
    events,
    hypotheses,
    incidents,
    postmortems,
    replay,
    synopses,
    taken_actions,
)


class IncidentReads(Protocol):
    """One incident, as there is to read about it."""

    def incident(self, incident_id: str, /) -> Incident | None:
        """The incident's own row, or `None` where there is no such incident."""
        ...

    def account(self, incident_id: str, /) -> list[IncidentEvent]:
        """Everything the incident's account says, in the order it was said."""
        ...

    def candidates(self, incident_id: str, /) -> list[Hypothesis]:
        """Every candidate the incident's rounds formed, in the order formed."""
        ...

    def actions(self, incident_id: str, /) -> list[TakenAction]:
        """Every action stored against the incident, with what each reached."""
        ...

    def action_for(self, incident_id: str, hypothesis_id: str, /) -> TakenAction | None:
        """The action claimed for one candidate of the incident, where one was."""
        ...

    def leads(self, incident_id: str, /) -> list[ThreadMessage]:
        """What people told the incident in its thread, as leads."""
        ...

    def postmortem(self, incident_id: str, /) -> Postmortem | None:
        """The incident's write-up, where one was written."""
        ...

    def synopsis(self, incident_id: str, /) -> ExecutiveSynopsis | None:
        """The incident's executive synopsis, where one was written."""
        ...

    def tokens_spent(self, incident_id: str, /) -> int:
        """How many tokens the incident's walk spent on the model."""
        ...


class _OnAConnection:
    """The reads, on a connection somebody else holds and commits."""

    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def incident(self, incident_id: str, /) -> Incident | None:
        return incidents.get(self._conn, incident_id)

    def account(self, incident_id: str, /) -> list[IncidentEvent]:
        return events.get_by_incident(self._conn, incident_id)

    def candidates(self, incident_id: str, /) -> list[Hypothesis]:
        return hypotheses.get_all_by_incident(self._conn, incident_id)

    def actions(self, incident_id: str, /) -> list[TakenAction]:
        return taken_actions.get_by_incident(self._conn, incident_id)

    def action_for(self, incident_id: str, hypothesis_id: str, /) -> TakenAction | None:
        return taken_actions.get_action_for_hypothesis(self._conn, incident_id, hypothesis_id)

    def leads(self, incident_id: str, /) -> list[ThreadMessage]:
        return conversation.get_leads_by_incident(self._conn, incident_id)

    def postmortem(self, incident_id: str, /) -> Postmortem | None:
        return postmortems.get_by_incident(self._conn, incident_id)

    def synopsis(self, incident_id: str, /) -> ExecutiveSynopsis | None:
        return synopses.get_by_incident(self._conn, incident_id)

    def tokens_spent(self, incident_id: str, /) -> int:
        return replay.get_tokens_spent(self._conn, incident_id)


class _OverConnections:
    """The reads, each on a connection of its own from `connections`."""

    def __init__(self, connections: Connections) -> None:
        self._connections = connections

    def incident(self, incident_id: str, /) -> Incident | None:
        with self._connections() as conn:
            return incident_reads_on(conn).incident(incident_id)

    def account(self, incident_id: str, /) -> list[IncidentEvent]:
        with self._connections() as conn:
            return incident_reads_on(conn).account(incident_id)

    def candidates(self, incident_id: str, /) -> list[Hypothesis]:
        with self._connections() as conn:
            return incident_reads_on(conn).candidates(incident_id)

    def actions(self, incident_id: str, /) -> list[TakenAction]:
        with self._connections() as conn:
            return incident_reads_on(conn).actions(incident_id)

    def action_for(self, incident_id: str, hypothesis_id: str, /) -> TakenAction | None:
        with self._connections() as conn:
            return incident_reads_on(conn).action_for(incident_id, hypothesis_id)

    def leads(self, incident_id: str, /) -> list[ThreadMessage]:
        with self._connections() as conn:
            return incident_reads_on(conn).leads(incident_id)

    def postmortem(self, incident_id: str, /) -> Postmortem | None:
        with self._connections() as conn:
            return incident_reads_on(conn).postmortem(incident_id)

    def synopsis(self, incident_id: str, /) -> ExecutiveSynopsis | None:
        with self._connections() as conn:
            return incident_reads_on(conn).synopsis(incident_id)

    def tokens_spent(self, incident_id: str, /) -> int:
        with self._connections() as conn:
            return incident_reads_on(conn).tokens_spent(incident_id)


def incident_reads_on(conn: psycopg.Connection) -> IncidentReads:
    """The incident's reads on `conn`, which the caller holds: every read made
    through it describes the moment that connection sees."""
    return _OnAConnection(conn)


def incident_reads_over(connections: Connections) -> IncidentReads:
    """The incident's reads for a caller holding only where connections come
    from - each read on a connection of its own, none opened until asked."""
    return _OverConnections(connections)
