from __future__ import annotations

from typing import Any

import psycopg
from psycopg.types.json import Jsonb


def record(
    conn: psycopg.Connection,
    incident_id: str,
    action_type: str,
    outcome: str,
    undo_descriptor: dict[str, Any],
) -> None:
    """Writes what an action did and what would undo it (spec §11.1, §13).

    An empty descriptor is stored as NULL rather than as `{}`: an action that
    never reached the provider changed nothing, and a row offering a way back
    from a change that was never made would send a human to undo it.
    """
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO action (incident_id, type, reversible, outcome, undo_descriptor) "
            "VALUES (%s, %s, %s, %s, %s)",
            (
                incident_id,
                action_type,
                True,
                outcome,
                Jsonb(undo_descriptor) if undo_descriptor else None,
            ),
        )
    conn.commit()
