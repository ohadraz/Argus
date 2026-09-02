from __future__ import annotations

from argus_core.db import connect
from argus_core.events import AlertAcknowledged, IncidentEvent, Publisher, publish
from argus_core.models.alert import Alert
from argus_core.replay import ReplayEntry

from orchestrator.repository import events, replay

"""The one subscriber the event stream has.

`argus_core` defines what an event is and how it is published; it cannot know
where an event goes, because knowing would make the shared library depend on
the module that owns the tables. So the wiring lives here, on the side that
already holds a database connection, and the graph hands this to every
component it invokes.

In-process and synchronous, which is what makes the recorded order the real
order: an event published before a decision is written before it, rather than
usually-before-it. A broker would implement the same `Publisher` and change
nothing about who publishes or who reads.
"""


def record_event(event: IncidentEvent) -> None:
    """Persists one event. Called only through `argus_core.events.publish`,
    which is where a failure here is caught and dropped - this function is free
    to raise, and the seam is what makes that harmless."""
    with connect() as conn:
        events.record(conn, event)


def record_call(entry: ReplayEntry) -> None:
    """Persists one call Argus made out of its own process.

    The replay log's subscriber, and the same arrangement as `record_event`
    beside it: `argus_core` says what an entry is and how it is handed over,
    and this side - which already holds a database connection - is the only
    thing that knows where it goes.

    Called only through `argus_core.replay.record`, which catches and drops a
    failure here. So this is free to raise: a receipt that could not be filed
    must not take down the investigation it was describing.
    """
    with connect() as conn:
        replay.record(conn, entry)


def acknowledge_alert(incident_id: str,
                      alert: Alert,
                      publisher: Publisher = record_event) -> None:
    """Says that Argus has the alert and has looked at nothing yet.

    The first line of every incident's story, and the only one the graph cannot
    write: by the time a node runs, the alert has already been received. It is
    published from the entrypoint instead, right after the incident row exists
    to hang it on.

    An event and not a status. The status machine (spec §10) says where an
    incident can go next, and acknowledging adds nowhere to go - so making it a
    status would rewrite the one assertion every lifecycle test makes, for the
    sake of a label.

    Its own function rather than three lines inside `create_incident_and_run`
    because that function opens a database connection and runs a whole graph:
    the seam that makes this checkable is a function whose entire job is the
    sentence it publishes.
    """
    publish(AlertAcknowledged(incident_id=incident_id, alert=alert), publisher)
