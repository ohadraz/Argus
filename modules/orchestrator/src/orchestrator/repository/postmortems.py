from __future__ import annotations

from datetime import datetime

import psycopg
from psycopg.rows import class_row
from psycopg.types.json import Jsonb
from pydantic import BaseModel

from orchestrator.repository._types import UuidStr


class Postmortem(BaseModel):
    id: UuidStr
    incident_id: UuidStr
    root_cause: str | None
    cost_estimate: dict[str, object] | None
    assumptions: list[str] | None
    executive_summary: str | None
    checklist_complete: bool
    created_at: datetime


def record(
    conn: psycopg.Connection, incident_id: str, content: dict[str, object]
) -> None:
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO postmortem "
            "(incident_id, root_cause, cost_estimate, assumptions, executive_summary, "
            "checklist_complete) VALUES (%s, %s, %s, %s, %s, %s)",
            (
                incident_id,
                content["root_cause"],
                Jsonb(content["cost_estimate"]),
                Jsonb(content["assumptions"]),
                content["executive_summary"],
                content["checklist_complete"],
            ),
        )
    conn.commit()


def get_by_incident(conn: psycopg.Connection, incident_id: str) -> Postmortem | None:
    with conn.cursor(row_factory=class_row(Postmortem)) as cursor:
        cursor.execute(
            "SELECT id, incident_id, root_cause, cost_estimate, assumptions, "
            "executive_summary, checklist_complete, created_at "
            "  FROM postmortem "
            " WHERE incident_id = %s",
            (incident_id,),
        )
        return cursor.fetchone()
