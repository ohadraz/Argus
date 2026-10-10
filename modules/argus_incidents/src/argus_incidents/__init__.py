"""The incident record: the tables, and what is done to an incident that is
not the walk.

Its operations behind one public name. `intake` takes an alert and makes an
incident of it, `withdrawal` stops one and answers whether anybody still wants
it walked, `ingesting` records a person's words about one, once, `publishing` is
the one subscriber the event stream has - where an event is written on the
connection its decision is written on - `following` is how a reader of the
event log finds what it has not yet read and keeps its place, `waiting` is how
a walk holds off its next step while a person is asked to confirm, and
`tracing` is how any later work on an incident continues the trace its alert
arrived in.

`repository` is deliberately not flattened into this namespace. Its modules are
named for the tables they own and are meant to be read that way -
`incidents.get`, `runs.claim`, `events.record` - and a flat door would have to
rename half of them to keep `record` from meaning four things. A caller reaches
one as `from argus_incidents.repository import incidents`, which is how the
layering contract already spells what this module may be reached by.

That leaves the reads coarser than they should be: a caller still asks for rows
by table rather than for the incident's story, and the repository is public to
everything that can name this package. Narrowing it is a design change - a
reads API returning domain values, with the tables behind it - and not one a
refactor gets to make on the way past.
"""

from __future__ import annotations

from argus_incidents.ending import (
    EndedByAPerson,
    IsStillWanted,
    ended_by_a_person_via,
    wanted_until_a_person_ends_it,
)
from argus_incidents.following import Backlog, Place, events_since, place_for
from argus_incidents.ingesting import ingest_a_message
from argus_incidents.intake import start_incident
from argus_incidents.publishing import (
    PublisherFor,
    acknowledge_alert,
    calls_into,
    events_into,
    events_into_connection,
    publish_beside,
)
from argus_incidents.resolution import resolve_incident
from argus_incidents.tracing import inside_the_incidents_trace
from argus_incidents.waiting import WaitForPeople, waiting_for_people_via
from argus_incidents.withdrawal import withdraw_incident

__all__ = [
    "Backlog",
    "EndedByAPerson",
    "IsStillWanted",
    "Place",
    "WaitForPeople",
    "PublisherFor",
    "acknowledge_alert",
    "calls_into",
    "ended_by_a_person_via",
    "events_into",
    "events_into_connection",
    "events_since",
    "ingest_a_message",
    "inside_the_incidents_trace",
    "place_for",
    "publish_beside",
    "resolve_incident",
    "start_incident",
    "waiting_for_people_via",
    "wanted_until_a_person_ends_it",
    "withdraw_incident"
]
