from __future__ import annotations

from datetime import datetime

import psycopg
from argus_core.models.actor import Actor
from argus_core.models.alert import Alert
from argus_core.models.incident_status import IncidentStatus
from psycopg.rows import class_row
from psycopg.types.json import Jsonb
from pydantic import BaseModel

from orchestrator.repository._types import UuidStr


class Incident(BaseModel):
    id: UuidStr
    alert_payload: dict[str, object]
    status: IncidentStatus
    slack_channel_id: str | None
    pr_url: str | None
    created_at: datetime
    # Absent while the incident is still being worked, which is a state it
    # spends most of its life in and `fixing` keeps it in despite reading like
    # an ending.
    ended_at: datetime | None


def create(conn: psycopg.Connection, alert: Alert) -> str:
    """Creates the Incident row and its initial TimelineEvent in the same
    transaction (spec §7.1's single-writer rule, §11.1; spec §10's
    `[*] --> acknowledged` edge counts as a transition).

    `acknowledged`, not `investigating`: this runs where the alert is received,
    and the walk it queues belongs to a worker that has not taken it yet.
    Writing `investigating` here would date an investigation from the moment
    Argus heard about the incident rather than from the moment one began."""
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO incident (alert_payload, status) VALUES (%s, %s) RETURNING id",
            (Jsonb(alert.model_dump(mode="json")), IncidentStatus.ACKNOWLEDGED),
        )
        row = cursor.fetchone()
        assert row is not None
        incident_id = str(row[0])
        cursor.execute(
            "INSERT INTO timeline_event (incident_id, to_status, actor, action) "
            "VALUES (%s, %s, %s, %s)",
            (incident_id, IncidentStatus.ACKNOWLEDGED, Actor.ORCHESTRATOR, "incident created"),
        )
    conn.commit()
    return incident_id


def transition(
    conn: psycopg.Connection,
    incident_id: str,
    to_status: IncidentStatus,
    actor: Actor,
    action: str,
    result: str | None = None,
    confidence: float | None = None,
) -> None:
    """Updates `Incident.status` and writes the paired `TimelineEvent` row in
    the same transaction (spec §7.1, §11.1's single-writer rule).

    For a status the incident is actually entering. Work that is worth recording
    and moved nothing goes to `record_note` instead - see there for why the two
    are separate.

    A transition into a terminal status also stamps `ended_at`, in the same
    statement rather than in a second one: the two facts are one event, and a
    status written without its time would leave an incident that has ended
    looking like one still running.

    `now()` rather than a time the caller supplies - the database already
    stamps `created_at`, and a duration measured between two clocks is a
    duration measuring the difference between them.

    Committing is the caller's. The event that narrates this transition is
    written on the same connection, and a commit here would put the transition
    beyond reach of the account before the account existed.
    """
    ends_the_incident = to_status.is_terminal()

    with conn.cursor() as cursor:
        cursor.execute(
            "UPDATE incident "
            "   SET status = %s, ended_at = CASE WHEN %s THEN now() ELSE ended_at END "
            " WHERE id = %s",
            (to_status, ends_the_incident, incident_id),
        )
        cursor.execute(
            "INSERT INTO timeline_event "
            "(incident_id, to_status, actor, action, result, confidence) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (incident_id, to_status, actor, action, result, confidence),
        )


def withdraw(conn: psycopg.Connection, incident_id: str, actor: Actor) -> bool:
    """Takes an incident back from Argus, and says whether it took effect.

    The one status written from outside the walk. Every other status an
    incident reaches is derived from work the walk did and written by the walk
    itself; this one records something the walk cannot observe - that somebody
    has the failure in hand - so it is written here and the walk finds out by
    reading it back.

    The refusal is the point of the `WHERE`. An incident that resolved was
    resolved by a mitigation still holding the service up, and withdrawing it
    would put the failure back; an incident already withdrawn has had its
    actions undone once, and undoing them again would fight whoever has changed
    them since. Both are refused by the same clause, and refused in the same
    statement that would have made the change - a read followed by a write
    would let two callers both find the incident live and both withdraw it.

    The answer is what tells them apart, and callers act on it: the endpoint
    reports it, and the walk's unwind runs only for the withdrawal that took
    effect, so a second press is not a second undo.

    The timeline row is written only where the status moved, for the reason
    `record_note` exists at all - a row claiming the incident entered
    `withdrawn` when it was already there is a claim about the incident that is
    not true.
    """
    still_going = [status for status in IncidentStatus if not status.is_terminal()]

    with conn.cursor() as cursor:
        cursor.execute(
            "UPDATE incident SET status = %s, ended_at = now() "
            " WHERE id = %s AND status = ANY(%s)",
            (IncidentStatus.WITHDRAWN, incident_id, still_going),
        )
        withdrawn = cursor.rowcount == 1

        if withdrawn:
            cursor.execute(
                "INSERT INTO timeline_event (incident_id, to_status, actor, action) "
                "VALUES (%s, %s, %s, %s)",
                (incident_id, IncidentStatus.WITHDRAWN, actor, "incident withdrawn"),
            )
    conn.commit()

    return withdrawn


def record_note(
    conn: psycopg.Connection,
    incident_id: str,
    actor: Actor,
    action: str,
    result: str | None = None,
    confidence: float | None = None,
) -> None:
    """Writes a `TimelineEvent` row for work that did not move the incident.

    Narration and transition are two operations that were one function only by
    accident. An action refused at the tier gate is the case that separates
    them: it is worth recording, and the incident was already `mitigating` and
    still is. Written through `transition` it would claim the incident entered a
    status it had never left, which is exactly the false record the timeline is
    read to avoid.

    The row carries the status the incident is already in, taken from the row
    itself rather than from the caller - a caller that had to supply it could
    supply the wrong one, and then this function would be a transition after
    all.
    """
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO timeline_event "
            "(incident_id, to_status, actor, action, result, confidence) "
            "SELECT %s, status, %s, %s, %s, %s FROM incident WHERE id = %s",
            (incident_id, actor, action, result, confidence, incident_id),
        )
    conn.commit()


def get_recent(conn: psycopg.Connection) -> list[Incident]:
    """Every incident, newest first.

    A history view opens on what just happened, so the ordering is the whole
    point of the name: oldest-first would put the incident somebody came looking
    for at the bottom of the page.
    """
    with conn.cursor(row_factory=class_row(Incident)) as cursor:
        cursor.execute(
            "SELECT id, alert_payload, status, slack_channel_id, pr_url, created_at, ended_at "
            "  FROM incident "
            "ORDER BY created_at DESC"
        )
        return cursor.fetchall()


def get_current(conn: psycopg.Connection) -> Incident | None:
    """The incident a live view opens on: the newest one that has not finished,
    and where none is running, the newest there has ever been.

    No stored pointer to a "current" incident, because a pointer is a second
    thing that can be wrong about which incident is running. The rule is a
    question the rows already answer, and it is right whenever one incident
    runs at a time - which is what the demo does, and what it degrades from
    sensibly rather than by showing nothing.

    The fallback matters as much as the rule. An incident that vanished from
    the front page the moment it resolved would leave the screen exactly when
    everybody in the room is looking at it.

    Ordering on the terminal statuses rather than filtering by them, so the
    whole rule is one query: `false` sorts before `true`, which puts every
    unfinished incident above every finished one, newest first within each.
    """
    terminal = [status for status in IncidentStatus if status.is_terminal()]

    with conn.cursor(row_factory=class_row(Incident)) as cursor:
        cursor.execute(
            "SELECT id, alert_payload, status, slack_channel_id, pr_url, created_at, ended_at "
            "  FROM incident "
            "ORDER BY status = ANY(%s), created_at DESC "
            " LIMIT 1",
            (terminal,),
        )
        return cursor.fetchone()


def get(conn: psycopg.Connection, incident_id: str) -> Incident | None:
    with conn.cursor(row_factory=class_row(Incident)) as cursor:
        cursor.execute(
            "SELECT id, alert_payload, status, slack_channel_id, pr_url, created_at, ended_at "
            "  FROM incident "
            " WHERE id = %s",
            (incident_id,),
        )
        return cursor.fetchone()
