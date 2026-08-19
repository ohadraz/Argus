from __future__ import annotations

from datetime import datetime

import psycopg
from argus_core.models.actor import Actor
from argus_core.models.incident_status import IncidentStatus
from psycopg.rows import class_row
from pydantic import BaseModel

from orchestrator.repository._types import UuidStr


class TimelineEvent(BaseModel):
    id: UuidStr
    incident_id: UuidStr
    to_status: IncidentStatus
    actor: Actor | None
    action: str | None
    result: str | None
    confidence: float | None
    created_at: datetime


def get_timeline_events(conn: psycopg.Connection, incident_id: str) -> list[TimelineEvent]:
    with conn.cursor(row_factory=class_row(TimelineEvent)) as cursor:
        cursor.execute(
            "SELECT id, incident_id, to_status, actor, action, result, confidence, created_at "
            "  FROM timeline_event "
            " WHERE incident_id = %s "
            "ORDER BY created_at",
            (incident_id,),
        )
        return cursor.fetchall()
