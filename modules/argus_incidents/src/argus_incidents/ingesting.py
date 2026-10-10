"""How a person's words about an incident reach its record - and nothing about
what they meant.

The resolution's sibling, and in this package for its reason: `argus_web` calls
this, and anything `argus_web` can import must reach nothing that walks a graph.
What the words meant is classified later, by the intent agent, from the event
written here; the chat platform waits three seconds for an answer, and a model
takes longer than that.

A message is ingested once. The platform retries a delivery it believes went
unanswered, and a message ingested twice is classified twice and offered back
to its writer twice - so the message's own name and the account of it are one
write, claimed and recorded together or not at all. The event is recorded
rather than published, unlike every other account: an account that could fail
to be written here would be a message claimed and never ingested.
"""

from __future__ import annotations

from argus_core import Connections
from argus_core.events import PersonWrote
from argus_core.models import Reference

from argus_incidents.repository import events, references


def ingest_a_message(incident_id: str,
                     message: Reference,
                     person_id: str,
                     text: str,
                     connections: Connections) -> bool:
    """Records that the person wrote this about the incident, and says whether
    it was ingested for the first time."""
    with connections() as conn:
        if not references.claim(conn, incident_id, message):
            return False

        events.record(conn, PersonWrote(incident_id=incident_id,
                                        message=message,
                                        person_id=person_id,
                                        text=text))
        conn.commit()

    return True
