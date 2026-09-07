from __future__ import annotations

import psycopg
from agent_postmortem import PostmortemDocument
from argus_core.models.postmortem import Postmortem
from psycopg.rows import class_row
from psycopg.types.json import Jsonb


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
            "engineer_minutes, responders, responder_titles, "
            "responder_cost_estimate, responder_cost_minimum, "
            "responder_cost_maximum, responder_cost_currency, tokens_spent, "
            "assumptions, executive_summary, checklist_complete) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                incident_id,
                document.root_cause,
                document.customer_loss_estimate,
                document.estimate_currency,
                document.engineer_minutes,
                document.responders,
                Jsonb(document.responder_titles),
                document.responder_cost_estimate,
                document.responder_cost_minimum,
                document.responder_cost_maximum,
                document.responder_cost_currency,
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
            "engineer_minutes, responders, responder_titles, "
            "responder_cost_estimate, responder_cost_minimum, "
            "responder_cost_maximum, responder_cost_currency, tokens_spent, "
            "assumptions, "
            "executive_summary, checklist_complete, created_at "
            "  FROM postmortem "
            " WHERE incident_id = %s",
            (incident_id,),
        )
        return cursor.fetchone()
