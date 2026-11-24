"""The rows a filed record hangs off, written as plainly as the schema allows.

A record is filed against an incident, and a walk files it for the run it holds.
This module knows neither the incident record nor the run queue - those are
`incident_record`' - so the rows are written here in SQL, naming only the columns
the schema requires. Spelled once, because a case that wrote its own would be a
case about the spelling.
"""

from __future__ import annotations

import psycopg
from core import Fence, new_id
from core.stored import ALERT, REMEMBERED_INCIDENT, SHIPPED
from psycopg.types.json import Jsonb

from incident_memory_test.framework.builders import DONT_CARE_MOMENT, DONT_CARE_SERVICE

# The state a run is in while somebody walks it, as the fence reads it.
RUNNING = "running"


def an_incident_on_record(conn: psycopg.Connection, incident_id: str) -> str:
    """An incident row for a record to be filed against, and its id."""
    conn.execute(
        "INSERT INTO incident (id, alert_payload, shape, alert_service, status, created_at) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (incident_id, Jsonb({}), SHIPPED.current(ALERT), DONT_CARE_SERVICE, "investigating",
         DONT_CARE_MOMENT)
    )
    conn.commit()

    return incident_id


def a_claim_since_taken_back(conn: psycopg.Connection, incident_id: str) -> Fence:
    """The claim a paused walk still believes it holds, on a run a newer claim
    has since taken.

    The run is at its second epoch and running, so the fence refuses a write
    for the first and would pass one for the second.
    """
    run_id = new_id()
    conn.execute(
        "INSERT INTO incident_run (id, incident_id, state, epoch) VALUES (%s, %s, %s, %s)",
        (run_id, incident_id, RUNNING, 2)
    )
    conn.commit()

    return Fence(run_id=run_id, epoch=1)


def filed_by_a_newer_release(conn: psycopg.Connection, incident_id: str) -> None:
    """The incident's filed record marked as written in a shape one on from
    any this release knows, as a newer release would have filed it."""
    conn.execute("UPDATE incident_memory SET shape = %s WHERE incident_id = %s",
                 (SHIPPED.current(REMEMBERED_INCIDENT) + 1, incident_id))
    conn.commit()


def filed_unreadable(conn: psycopg.Connection, incident_id: str) -> None:
    """The incident's filed record replaced by one no reader can bring up - an
    empty object, missing everything a record has - at a shape the reader
    knows, so it is unreadable rather than newer."""
    conn.execute("UPDATE incident_memory SET record = '{}' WHERE incident_id = %s",
                 (incident_id,))
    conn.commit()
