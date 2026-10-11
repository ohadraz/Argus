"""How a person's words about an incident reach its record - and nothing about
what they meant.

The resolution's sibling, and in this package for its reason: `argus_web` calls
this, and anything `argus_web` can import must reach nothing that walks a graph.
What the words meant is classified later, by the intent agent; the chat
platform waits three seconds for an answer, and a model takes longer than that.

A message is ingested once. The platform retries a delivery it believes went
unanswered, and a message ingested twice is classified twice and offered back
to its writer twice - so the message and the account of its arrival are one
write, recorded together or not at all. The event is recorded rather than
published, unlike every other account: an account that could fail to be
written here would be a message kept and never told of.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

import psycopg
from argus_core import Connections, utc_now
from argus_core.events import IncidentEvent, PersonWrote
from argus_core.models import Reference, ThreadMessage

from argus_incidents.repository import conversation, events

# Writes one event down on the connection it is handed, inside its transaction.
type RecordEvent = Callable[[psycopg.Connection, IncidentEvent], None]


def ingest_a_message(incident_id: str,
                     message: Reference,
                     person_id: str,
                     text: str,
                     connections: Connections,
                     now: Callable[[], datetime] = utc_now,
                     record_event: RecordEvent = events.record) -> bool:
    """Records that the person wrote this about the incident, and says whether
    it was ingested for the first time.

    `record_event` is the event log's write, a seam so the one failure this
    exists to survive - the account failing after the message was written -
    can be brought about on purpose.
    """
    written_at = now()

    with connections() as conn:
        if not conversation.write(conn, ThreadMessage(incident_id=incident_id,
                                                      message=message,
                                                      person_id=person_id,
                                                      text=text,
                                                      written_at=written_at)):
            return False

        record_event(conn, PersonWrote(incident_id=incident_id,
                                       message=message,
                                       person_id=person_id,
                                       text=text,
                                       at=written_at))
        conn.commit()

    return True
