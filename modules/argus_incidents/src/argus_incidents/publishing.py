from __future__ import annotations

from collections.abc import Callable

import psycopg
from argus_core.db import Connections
from argus_core.events import AlertAcknowledged, IncidentEvent, Publisher, publish
from argus_core.models.alert import Alert
from argus_core.replay import Recorder, ReplayEntry

from argus_incidents.repository import events, replay

"""The one subscriber the event stream has.

`argus_core` defines what an event is and how it is published; it cannot know
where an event goes, because knowing would make the shared library depend on
the module that owns the tables - which is this one. So the wiring lives here,
and the process that holds the connections builds it and hands it to every
component it invokes.

In-process and synchronous, which is what makes the recorded order the real
order: an event published before a decision is written before it, rather than
usually-before-it. A broker would implement the same `Publisher` and change
nothing about who publishes or who reads.
"""

# How a caller that already holds a connection gets a subscriber that writes on
# it. A seam rather than a call, so what files an event stays injectable in the
# one place it matters - the paired write, where a failing subscriber must be
# provable not to take the decision down with it.
type PublisherFor = Callable[[psycopg.Connection], Publisher]


def events_into_connection(conn: psycopg.Connection) -> Publisher:
    """The subscriber that files events onto a connection somebody else holds.

    What makes a decision and its account one write: the event goes onto the
    connection the decision was written on, so both commit together or neither
    does. `events_into` below is the same subscriber for a caller that has
    nothing to join - an alert being acknowledged, a withdrawal arriving from
    outside a walk.
    """

    def record_event(event: IncidentEvent) -> None:
        events.record(conn, event)

    return record_event


def publish_beside(conn: psycopg.Connection,
                   event: IncidentEvent,
                   publisher: Publisher) -> None:
    """Writes the account of what was just done, and cannot fail the doing.

    Both halves at once, which is the whole point. The event is written on the
    caller's connection, so it commits with the fact it narrates and a crash
    between the two cannot leave one without the other. And it is written
    inside a savepoint, so a subscriber having a bad day rolls back its own row
    and nothing else - without one, a failed insert leaves the transaction
    aborted, and the mitigation it was describing would go down with the
    sentence about it (spec §4 principle 8).

    The savepoint is inside the try, the swallowing outside it: the roll back
    has to happen before anybody decides to carry on, or carrying on is the
    thing that fails.
    """
    def within_a_savepoint(narration: IncidentEvent) -> None:
        with conn.transaction():
            publisher(narration)

    publish(event, within_a_savepoint)


def events_into(connections: Connections) -> Publisher:
    """The subscriber that files events, against the connections it is given.

    A function returning one rather than a function taking both, because what
    publishes is a `Publisher` - one argument, one event - and the database has
    no business appearing in the signature every component in this system is
    handed. Where the connections come from is settled once, by the process that
    has them.

    The subscriber it returns is free to raise. `argus_core.events.publish` is
    where a failure here is caught and dropped, and that seam is what makes
    raising harmless.
    """

    def record_event(event: IncidentEvent) -> None:
        with connections() as conn:
            events.record(conn, event)

    return record_event


def calls_into(connections: Connections) -> Recorder:
    """The replay log's subscriber, and the same arrangement as `events_into`.

    `argus_core` says what an entry is and how it is handed over; this side is
    the only thing that knows where it goes.

    Called only through `argus_core.replay.record`, which catches and drops a
    failure here. So this is free to raise: a receipt that could not be filed
    must not take down the investigation it was describing.
    """

    def record_call(entry: ReplayEntry) -> None:
        with connections() as conn:
            replay.record(conn, entry)

    return record_call


def acknowledge_alert(incident_id: str, alert: Alert, publisher: Publisher) -> None:
    """Says that Argus has the alert and has looked at nothing yet.

    The first line of every incident's story, and the only one the graph cannot
    write: by the time a node runs, the alert has already been received. It is
    published from the entrypoint instead, right after the incident row exists
    to hang it on.

    An event and not a status. The status machine (spec §10) says where an
    incident can go next, and acknowledging adds nowhere to go - so making it a
    status would rewrite the one assertion every lifecycle test makes, for the
    sake of a label.

    Its own function rather than three lines inside `start_incident` because
    that function creates a row and queues a walk: the seam that makes this
    checkable is a function whose entire job is the sentence it publishes.
    """
    publish(AlertAcknowledged(incident_id=incident_id, alert=alert), publisher)
