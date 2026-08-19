from __future__ import annotations

from datetime import datetime

import psycopg
from argus_core.models.cause import CauseType
from psycopg.rows import class_row
from pydantic import BaseModel

from orchestrator.repository._types import UuidStr


class Hypothesis(BaseModel):
    id: UuidStr
    incident_id: UuidStr
    cause_type: CauseType | None
    description: str | None
    tested: bool
    result: str | None
    confidence: float | None
    created_at: datetime


def record(
    conn: psycopg.Connection,
    incident_id: str,
    description: str,
    confidence: float,
    cause_type: CauseType | None,
) -> None:
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO hypothesis (incident_id, description, cause_type, tested, confidence) "
            "VALUES (%s, %s, %s, %s, %s)",
            (incident_id, description, cause_type, True, confidence),
        )
    conn.commit()


def get_latest_by_incident(conn: psycopg.Connection, incident_id: str) -> Hypothesis | None:
    with conn.cursor(row_factory=class_row(Hypothesis)) as cursor:
        cursor.execute(
            "SELECT id, incident_id, cause_type, description, tested, result, confidence, "
            "created_at "
            "  FROM hypothesis "
            " WHERE incident_id = %s "
            "ORDER BY created_at DESC "
            " LIMIT 1",
            (incident_id,),
        )
        return cursor.fetchone()
