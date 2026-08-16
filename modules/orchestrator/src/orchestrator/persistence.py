from __future__ import annotations

import psycopg
from argus_core.models import Alert, IncidentStatus
from psycopg.types.json import Jsonb


def create_incident(conn: psycopg.Connection, alert: Alert) -> str:
    """Creates the Incident row and its initial TimelineEvent in the same
    transaction (spec §7.1's single-writer rule, §11.1; spec §10's
    `[*] --> investigating` edge counts as a transition)."""
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO incident (alert_payload, status) VALUES (%s, %s) RETURNING id",
            (Jsonb(alert.model_dump(mode="json")), "investigating"),
        )
        row = cursor.fetchone()
        assert row is not None
        incident_id = str(row[0])
        cursor.execute(
            "INSERT INTO timeline_event (incident_id, to_status, actor, action) "
            "VALUES (%s, %s, %s, %s)",
            (incident_id, "investigating", "orchestrator", "incident created"),
        )
    conn.commit()
    return incident_id


def transition(
    conn: psycopg.Connection,
    incident_id: str,
    to_status: IncidentStatus,
    actor: str,
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


def record_hypothesis(
    conn: psycopg.Connection, incident_id: str, description: str, confidence: float
) -> None:
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO hypothesis (incident_id, description, tested, confidence) "
            "VALUES (%s, %s, %s, %s)",
            (incident_id, description, True, confidence),
        )
    conn.commit()


def record_action(
    conn: psycopg.Connection, incident_id: str, action_type: str, outcome: str
) -> None:
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO action (incident_id, type, reversible, outcome) VALUES (%s, %s, %s, %s)",
            (incident_id, action_type, True, outcome),
        )
    conn.commit()


def record_postmortem(
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
