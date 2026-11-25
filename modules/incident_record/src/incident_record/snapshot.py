"""One incident, every part of it read once.

A reader that composes one answer of the whole incident - the postmortem's
evidence - reads its row, its account, its candidates, its actions, its leads and
its thread together. Read part by part as each is wanted, the account alone was
read ten times for one postmortem, and two reads of it could disagree.

Here rather than in `core.models`, where a value two modules name would usually
live: it holds the account's events, and `core.events` imports `core.models`, so
a snapshot there would close a cycle. Its readers depend on this package
already.
"""

from __future__ import annotations

from dataclasses import dataclass

import psycopg
from core.events import IncidentEvent
from core.models import (
    CHAT_THREAD,
    Hypothesis,
    Incident,
    RecordedReference,
    TakenAction,
    ThreadMessage,
)

from incident_record.incident_names import incident_names_on
from incident_record.incident_reads import incident_reads_on


@dataclass(frozen=True)
class IncidentSnapshot:
    """Everything one incident left behind, each part read once.

    `chat_thread` is the first thread a chat platform accepted a post of Argus's
    about the incident in, and when - `None` where none was.
    """
    incident: Incident
    account: list[IncidentEvent]
    candidates: list[Hypothesis]
    actions: list[TakenAction]
    leads: list[ThreadMessage]
    chat_thread: RecordedReference | None


def the_snapshot_of(conn: psycopg.Connection, incident_id: str) -> IncidentSnapshot | None:
    """The incident read whole on `conn`, which the caller holds - or `None`
    where there is no such incident.

    One moment only where `conn` is inside `postgres.at_one_moment`. On a
    connection alone each part sees what was committed when it was read.
    """
    reads = incident_reads_on(conn)
    incident = reads.incident(incident_id)
    if incident is None:
        return None

    return IncidentSnapshot(
        incident=incident,
        account=reads.account(incident_id),
        candidates=reads.candidates(incident_id),
        actions=reads.actions(incident_id),
        leads=reads.leads(incident_id),
        chat_thread=incident_names_on(conn).first_of_kind(incident_id, CHAT_THREAD)
    )
