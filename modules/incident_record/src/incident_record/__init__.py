"""The incident record: the tables, and what is done to an incident that is
not the walk.

Its operations behind one public name. `intake` takes an alert and makes an
incident of it, `withdrawal` stops one and answers whether anybody still wants
it walked, `ingesting` records a person's words about one, once, `publishing` is
the one subscriber the event stream has - where an event is written on the
connection its decision is written on - `following` is how a reader of the
event log finds what it has not yet read and keeps its place, `waiting` is how
a walk holds off its next step while a person is asked to confirm,
`tracing` is how any later work on an incident continues the trace its alert
arrived in, and `dating` is when an action was taken, as every reader says it.

What the record holds is reached by role, never by table. A reader of one
incident at one moment holds `IncidentReads`, the pages choosing which incidents
to show hold `IncidentsOnShow`, whatever hears from another tool holds
`IncidentNames`, the reader of people's messages holds `IncidentConversation`,
the walk holds `TheWalksWrites`, the processes that walk runs and change the
world for them hold `RunQueue`, and the source of exchange rates holds
`RatesCache`. Each answers in domain values, and each is built on a connection
its caller holds (`<role>_on`), so a reader's several questions describe one
moment and a writer's rows commit with the line it publishes beside them - and,
where a caller holds only where connections come from, over those
(`<role>_over`), each call on a connection of its own.

`repository` is this package's own: the tables, one module each, which the
roles read and write. Nothing that ships outside the package imports it - a
layering contract holds that - so what a table looks like is a question only
this package has to answer. A suite arranging rows still reaches it, as a
fixture reaches what it sets up.
"""

from __future__ import annotations

from incident_record.dating import when_it_was_taken
from incident_record.ending import (
    EndedByAPerson,
    IsStillWanted,
    StillHeld,
    ended_by_a_person_via,
    still_held_via,
    wanted_until_a_person_ends_it,
)
from incident_record.following import Backlog, Place, events_since, place_for
from incident_record.incident_conversation import (
    IncidentConversation,
    incident_conversation_on,
    incident_conversation_over,
)
from incident_record.incident_names import (
    IncidentNames,
    incident_names_on,
    incident_names_over,
)
from incident_record.incident_reads import (
    IncidentReads,
    incident_reads_on,
    incident_reads_over,
)
from incident_record.incidents_on_show import IncidentsOnShow, incidents_on_show_on
from incident_record.ingesting import ingest_a_message
from incident_record.intake import start_incident
from incident_record.publishing import (
    PublisherFor,
    acknowledge_alert,
    calls_into,
    events_into,
    events_into_connection,
    publish_beside,
)
from incident_record.rates_cache import RatesCache, rates_cache_on
from incident_record.repository.incidents import NO_TRACE_CONTEXT
from incident_record.repository.runs import ChangeInFlight, Run
from incident_record.repository.taken_actions import NoLongerOpen
from incident_record.resolution import resolve_incident
from incident_record.run_queue import RunQueue, run_queue_on
from incident_record.tracing import inside_the_incidents_trace
from incident_record.waiting import WaitForPeople, waiting_for_people_via
from incident_record.walk_step import the_current_step, within_step
from incident_record.walks_writes import TheWalksWrites, the_walks_writes_on
from incident_record.withdrawal import withdraw_incident

__all__ = [
    "Backlog",
    "ChangeInFlight",
    "EndedByAPerson",
    "IncidentConversation",
    "IncidentNames",
    "IncidentReads",
    "IncidentsOnShow",
    "IsStillWanted",
    "NoLongerOpen",
    "Place",
    "PublisherFor",
    "RatesCache",
    "Run",
    "RunQueue",
    "StillHeld",
    "TheWalksWrites",
    "WaitForPeople",
    "acknowledge_alert",
    "calls_into",
    "ended_by_a_person_via",
    "events_into",
    "events_into_connection",
    "events_since",
    "incident_conversation_on",
    "incident_conversation_over",
    "incident_names_on",
    "incident_names_over",
    "incident_reads_on",
    "incident_reads_over",
    "incidents_on_show_on",
    "ingest_a_message",
    "inside_the_incidents_trace",
    "NO_TRACE_CONTEXT",
    "place_for",
    "publish_beside",
    "rates_cache_on",
    "resolve_incident",
    "run_queue_on",
    "start_incident",
    "still_held_via",
    "the_current_step",
    "the_walks_writes_on",
    "waiting_for_people_via",
    "wanted_until_a_person_ends_it",
    "when_it_was_taken",
    "withdraw_incident",
    "within_step"
]
