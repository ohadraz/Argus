"""The fix Code-Fix claimed, as a row: one per incident, written before any of
it reaches the code host and read back by a Code-Fix step run again.

Stored with the shape it was written in and read back brought up to the shape
it is at now, as every stored dump is (`core.stored`).
"""

from __future__ import annotations

from datetime import datetime

import psycopg
from core.models import ClaimedFix
from core.stored import FIX_CLAIM, SHIPPED, Shapes, up_to_date
from psycopg.types.json import Jsonb


def claim(conn: psycopg.Connection,
          incident_id: str,
          fix: ClaimedFix,
          *,
          at: datetime,
          shapes: Shapes = SHIPPED) -> ClaimedFix:
    """Writes `fix` as the incident's fix, where none is claimed yet, and
    answers the claim that stands: this one, or the one written first.

    The one written first stands because it may already be on a branch. A
    second claim is a walk that asked the model again while the first was in
    flight, and pushing its patch would be refused by the branch the first
    wrote."""
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO fix_claim (incident_id, shape, claim, claimed_at) "
            "VALUES (%s, %s, %s, %s) ON CONFLICT (incident_id) DO NOTHING",
            (incident_id, shapes.current(FIX_CLAIM),
             Jsonb(fix.model_dump(mode="json")), at)
        )

    standing = get(conn, incident_id, shapes)
    assert standing is not None, "a claim just written, or already standing, reads back"

    return standing


def get(conn: psycopg.Connection,
        incident_id: str,
        shapes: Shapes = SHIPPED) -> ClaimedFix | None:
    """The incident's claimed fix, or `None` where none was claimed - brought
    up to the shape it is at now, and raising where it cannot be: a claim
    this release cannot read is the incident's own account, and pushing
    anything else in its place would be refused by the branch it wrote."""
    with conn.cursor() as cursor:
        cursor.execute("SELECT shape, claim FROM fix_claim WHERE incident_id = %s",
                       (incident_id,))
        row = cursor.fetchone()

    if row is None:
        return None

    shape, stored = row

    return ClaimedFix.model_validate(up_to_date(FIX_CLAIM, shape, stored, shapes))
