from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import psycopg
from agent_postmortem import PostmortemDocument
from psycopg.rows import class_row
from psycopg.types.json import Jsonb
from pydantic import BaseModel

from orchestrator.repository._types import UuidStr


class Postmortem(BaseModel):
    id: UuidStr
    incident_id: UuidStr
    root_cause: str | None
    # What the incident cost, in three units. Only the first is an estimate;
    # the other two are measured, and none of them is convertible into the
    # others - a rate to do that belongs to the reader, not to this row.
    customer_loss_estimate: Decimal | None
    estimate_currency: str | None
    engineer_minutes: int | None
    responders: int | None
    responder_titles: list[str] | None
    tokens_spent: int | None
    assumptions: list[str] | None
    executive_summary: str | None
    checklist_complete: bool
    created_at: datetime


def record(
    conn: psycopg.Connection, incident_id: str, document: PostmortemDocument
) -> None:
    """Writes the document the agent produced.

    Takes the document rather than a mapping of its fields: a dict makes every
    column a string looked up at runtime, so a field added to the document and
    forgotten here fails as a `KeyError` in production instead of as a type
    error on the way in - and a field misspelled in a caller's dict fails
    nowhere at all.
    """
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO postmortem "
            "(incident_id, root_cause, customer_loss_estimate, estimate_currency, "
            "engineer_minutes, responders, responder_titles, tokens_spent, "
            "assumptions, executive_summary, checklist_complete) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                incident_id,
                document.root_cause,
                document.customer_loss_estimate,
                document.estimate_currency,
                document.engineer_minutes,
                document.responders,
                Jsonb(document.responder_titles),
                document.tokens_spent,
                Jsonb(document.assumptions),
                document.executive_summary,
                document.checklist_complete,
            ),
        )
    conn.commit()


def get_by_incident(conn: psycopg.Connection, incident_id: str) -> Postmortem | None:
    with conn.cursor(row_factory=class_row(Postmortem)) as cursor:
        cursor.execute(
            "SELECT id, incident_id, root_cause, customer_loss_estimate, "
            "estimate_currency, "
            "engineer_minutes, responders, responder_titles, tokens_spent, "
            "assumptions, "
            "executive_summary, checklist_complete, created_at "
            "  FROM postmortem "
            " WHERE incident_id = %s",
            (incident_id,),
        )
        return cursor.fetchone()
