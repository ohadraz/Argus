from __future__ import annotations

from datetime import datetime
from typing import Any

import psycopg
from psycopg.rows import class_row
from psycopg.types.json import Jsonb
from pydantic import BaseModel

from orchestrator.repository._types import UuidStr


class Action(BaseModel):
    id: UuidStr
    incident_id: UuidStr
    hypothesis_id: UuidStr | None
    type: str | None
    target: str | None
    reversible: bool
    tier: str | None
    undo_descriptor: dict[str, Any] | None
    outcome: str | None
    taken_at: datetime
    approved_by: str | None


def record(
    conn: psycopg.Connection,
    incident_id: str,
    hypothesis_id: str,
    action_type: str,
    outcome: str,
    undo_descriptor: dict[str, Any],
) -> None:
    """Writes what an action did, what it was done for, and what would undo it
    (spec §11.1, §13).

    An empty descriptor is stored as NULL rather than as `{}`: an action that
    never reached the provider changed nothing, and a row offering a way back
    from a change that was never made would send a human to undo it.

    `hypothesis_id` is required rather than defaulted, because every caller has
    it: an action is taken *for* a candidate, and the node taking it is holding
    that candidate when it writes the row. A default would let a call site that
    does not know which candidate it is acting for compile, and the row it wrote
    would be indistinguishable from one where the association genuinely does not
    apply. Recovering it afterwards means matching the flag the action and the
    hypothesis happen to share, which is right only for as long as the walk
    refuses to act on one subject twice.
    """
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO action "
            "(incident_id, hypothesis_id, type, reversible, outcome, undo_descriptor) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (
                incident_id,
                hypothesis_id,
                action_type,
                True,
                outcome,
                Jsonb(undo_descriptor) if undo_descriptor else None,
            ),
        )
    conn.commit()


def get_by_incident(conn: psycopg.Connection, incident_id: str) -> list[Action]:
    """Everything the walk did during an incident, in the order it did it.

    A walk's actions are a sequence - tried, undone, tried again - and read back
    in any other order they describe a different incident. `taken_at` carries
    that order; `id` does not, because a random uuid says nothing about when its
    row was written.
    """
    with conn.cursor(row_factory=class_row(Action)) as cursor:
        cursor.execute(
            "SELECT id, incident_id, hypothesis_id, type, target, reversible, "
            "       tier, undo_descriptor, outcome, taken_at, approved_by "
            "  FROM action "
            " WHERE incident_id = %s "
            "ORDER BY taken_at",
            (incident_id,),
        )
        return cursor.fetchall()
