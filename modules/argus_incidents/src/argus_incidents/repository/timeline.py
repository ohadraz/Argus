from __future__ import annotations

import psycopg
from argus_core.models.timeline_event import TimelineEvent
from psycopg.rows import class_row


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
