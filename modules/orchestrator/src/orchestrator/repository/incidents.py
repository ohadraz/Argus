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


def create(conn: psycopg.Connection, alert: Alert) -> str:
    """Creates the Incident row and its initial TimelineEvent in the same
    transaction (spec §7.1's single-writer rule, §11.1; spec §10's
    `[*] --> investigating` edge counts as a transition)."""
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO incident (alert_payload, status) VALUES (%s, %s) RETURNING id",
            (Jsonb(alert.model_dump(mode="json")), IncidentStatus.INVESTIGATING),
        )
        row = cursor.fetchone()
        assert row is not None
        incident_id = str(row[0])
        cursor.execute(
            "INSERT INTO timeline_event (incident_id, to_status, actor, action) "
            "VALUES (%s, %s, %s, %s)",
            (incident_id, IncidentStatus.INVESTIGATING, Actor.ORCHESTRATOR, "incident created"),
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
    the same transaction (spec §7.1, §11.1's single-writer rule)."""
    with conn.cursor() as cursor:
        cursor.execute("UPDATE incident SET status = %s WHERE id = %s", (to_status, incident_id))
        cursor.execute(
            "INSERT INTO timeline_event "
            "(incident_id, to_status, actor, action, result, confidence) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (incident_id, to_status, actor, action, result, confidence),
        )
    conn.commit()


def get(conn: psycopg.Connection, incident_id: str) -> Incident | None:
    with conn.cursor(row_factory=class_row(Incident)) as cursor:
        cursor.execute(
            "SELECT id, alert_payload, status, slack_channel_id, pr_url, created_at "
            "  FROM incident "
            " WHERE id = %s",
            (incident_id,),
        )
        return cursor.fetchone()
