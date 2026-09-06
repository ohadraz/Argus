from __future__ import annotations

from typing import Protocol

from argus_core.db import connect
from argus_core.events import Publisher, StatusChanged, publish
from argus_core.models.actor import Actor
from argus_core.models.incident_status import IncidentStatus

from orchestrator.publishing import record_event
from orchestrator.repository import incidents

"""How an incident is taken back - and nothing about how one is walked.

The Orchestrator's second entrypoint, beside `intake`, and in its own module for
that module's reason rather than for tidiness: `argus_web` calls this, and
anything `argus_web` can import must reach nothing that walks a graph.

Marking is all this does. The walk that is running the incident finds out by
reading the status back, and unwinds what it had done itself - which is what
keeps one writer on an incident. A withdrawal that undid actions from here would
be a second writer racing the first for the same rows.
"""


class IsStillWanted(Protocol):
    """Whether anybody still wants this incident walked.

    The one question the walk asks about itself rather than about the world it
    is investigating, and the only one whose answer its own state cannot hold:
    a withdrawal is recorded by whoever pressed the button, and the walk finds
    out by reading the incident back.

    Positional-only: the incident is all it is called with, and a stand-in has
    no use for anything else.
    """

    def __call__(self, incident_id: str, /) -> bool: ...


def is_still_wanted(incident_id: str) -> bool:
    """Reads back whether the incident is still one Argus should be working on.

    Beside the withdrawal rather than in the graph, because three things ask it
    and only one of them is a node: the wrapper around every node, the wait for
    a service to recover, and the worker deciding whether to walk a run at all.

    Withdrawn, and not merely terminal. The two are one question only while a
    walk is mid-flight, and the places that ask are not: the wrapper asks before
    every node, including the one that writes up an incident the walk has just
    resolved, and the worker asks again after the walk to decide whether to put
    everything back. Reading a resolve as a withdrawal there answers both wrong
    at once - the postmortem is never written, and the mitigation that worked is
    undone a second after it worked.

    An incident with no row is not wanted. Reading a missing row as "carry on"
    is how a walk goes on writing rows for an incident that no longer exists -
    which is exactly the state a suite leaves behind when it empties the
    database between cases.
    """
    with connect() as conn:
        incident = incidents.get(conn, incident_id)

    return incident is not None and incident.status is not IncidentStatus.WITHDRAWN


def withdraw_incident(incident_id: str,
                      actor: Actor = Actor.HUMAN,
                      publisher: Publisher = record_event) -> bool:
    """Stops Argus working on an incident, and says whether it took effect.

    `Actor.HUMAN` by default because that is who the door is for. A suite
    withdrawing what it started is standing in for that person and is still not
    Argus, so the default serves it too; the parameter is there for the day
    something of Argus's own withdraws an incident and must not be recorded as
    a person having done it.

    The publishing is what a page watching the incident finds out from. A
    withdrawal that only wrote the row would leave that page polling an
    incident that had already ended - and published only where the row actually
    moved, so a second press does not tell every watcher the incident ended
    twice.
    """
    with connect() as conn:
        withdrawn = incidents.withdraw(conn, incident_id, actor)

    if withdrawn:
        publish(
            StatusChanged(
                incident_id=incident_id,
                to_status=IncidentStatus.WITHDRAWN,
                detail="withdrawn - somebody has the incident in hand"
            ),
            publisher
        )

    return withdrawn
