from __future__ import annotations

import json

import psycopg
from argus_core.models.hypothesis import Hypothesis
from psycopg.rows import class_row


def record(conn: psycopg.Connection, hypothesis: Hypothesis) -> None:
    """Writes a hypothesis the Investigator formed.

    Takes the domain object whole rather than its fields one by one - the row
    *is* the hypothesis, so there is nothing to translate beyond the shape
    Postgres wants. The id comes from the object, not from the table's
    default: it was assigned when the hypothesis was formed.
    """
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO hypothesis "
            "       (id, incident_id, summary, cause_type, confidence, "
            "        supporting_evidence, subject, tested, result) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                hypothesis.id,
                hypothesis.incident_id,
                hypothesis.summary,
                hypothesis.cause_type,
                hypothesis.confidence,
                json.dumps(hypothesis.supporting_evidence),
                hypothesis.subject,
                hypothesis.tested,
                hypothesis.result,
            ),
        )
    conn.commit()


def get_latest_by_incident(conn: psycopg.Connection, incident_id: str) -> Hypothesis | None:
    """The most recent hypothesis formed for an incident.

    `created_at` orders the rows but is not selected: it is an audit fact the
    table records, and nothing in the domain reads it.
    """
    with conn.cursor(row_factory=class_row(Hypothesis)) as cursor:
        cursor.execute(
            "SELECT id, incident_id, summary, cause_type, confidence, "
            "       supporting_evidence, subject, tested, result "
            "  FROM hypothesis "
            " WHERE incident_id = %s "
            "ORDER BY created_at DESC "
            " LIMIT 1",
            (incident_id,),
        )
        return cursor.fetchone()
