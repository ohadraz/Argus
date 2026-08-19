from __future__ import annotations

import psycopg


def record(
    conn: psycopg.Connection, incident_id: str, action_type: str, outcome: str
) -> None:
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO action (incident_id, type, reversible, outcome) VALUES (%s, %s, %s, %s)",
            (incident_id, action_type, True, outcome),
        )
    conn.commit()
