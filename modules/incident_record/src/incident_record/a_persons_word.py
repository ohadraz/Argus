"""A person ending an incident, whichever door they said it through.

The page's controls, a press in the chat thread and a resolution in the
on-call platform all end an incident the same way, so they reach it through
this one role rather than each its own: the incident is looked up, the ending is
made inside the trace the incident kept - a person ending it is part of its
story, wherever they said it - and a refusal is said there too, so the line
carries the incident it is about.

What each door answers is its own - a page answers a status code, a thread
answers nothing - so the outcome is a value the door reads, not an answer
already chosen for it.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final, Protocol

from core.models import Report
from opentelemetry.trace import SpanKind, Tracer
from postgres import Connections

from incident_record.incident_reads import incident_reads_over
from incident_record.publishing import PublisherFor, events_into_connection
from incident_record.resolution import resolve_incident
from incident_record.tracing import inside_the_incidents_trace
from incident_record.withdrawal import withdraw_incident

logger = logging.getLogger(__name__)

# The spans a person's ending is made inside, one per ending.
RESOLVE_SPAN: Final = "resolve incident"
WITHDRAW_SPAN: Final = "withdraw incident"


@dataclass(frozen=True)
class NoSuchIncident:
    """There is no incident by that id, so nothing was ended."""

    incident_id: str


@dataclass(frozen=True)
class Refused:
    """The incident had ended in a way this ending would contradict, and that
    ending stands."""

    incident_id: str


@dataclass(frozen=True)
class EndedAsSaid:
    """The incident ended as the person said."""

    incident_id: str


type PersonsEnding = NoSuchIncident | Refused | EndedAsSaid

# One of the two endings, as `resolve_incident` and `withdraw_incident` are
# both called: whether the incident moved.
type _Ending = Callable[[str, Report, Connections, PublisherFor], bool]


class AtAPersonsWord(Protocol):
    """Ending an incident because a person said so."""

    def resolve(self, incident_id: str, reported: Report, /) -> PersonsEnding:
        """Resolves the incident as `reported` says a person reported it."""
        ...

    def withdraw(self, incident_id: str, reported: Report, /) -> PersonsEnding:
        """Withdraws the incident as `reported` says a person asked."""
        ...


class _OverConnections:
    """A person's endings, each read and written on connections of its own."""

    def __init__(self, connections: Connections, tracer: Tracer | None) -> None:
        self._connections = connections
        self._tracer = tracer

    def resolve(self, incident_id: str, reported: Report, /) -> PersonsEnding:
        return self._end(incident_id, reported, resolve_incident, RESOLVE_SPAN,
                         refused="resolution refused")

    def withdraw(self, incident_id: str, reported: Report, /) -> PersonsEnding:
        return self._end(incident_id, reported, withdraw_incident, WITHDRAW_SPAN,
                         refused="withdrawal refused")

    def _end(self,
             incident_id: str,
             reported: Report,
             ending: _Ending,
             span: str,
             *,
             refused: str) -> PersonsEnding:
        """Ends the incident with `ending`, inside a span named `span` in the
        trace the incident kept, and says `refused` there where it would not
        move."""
        incident = incident_reads_over(self._connections).incident(incident_id)

        if incident is None:
            return NoSuchIncident(incident_id)

        with inside_the_incidents_trace(incident_id, incident.trace_context, span,
                                        kind=SpanKind.SERVER, tracer=self._tracer):
            if ending(incident_id, reported, self._connections, events_into_connection):
                return EndedAsSaid(incident_id)

            logger.info(refused)

            return Refused(incident_id)


def at_a_persons_word_over(connections: Connections,
                           tracer: Tracer | None = None) -> AtAPersonsWord:
    """A person's endings for a caller holding only where connections come
    from - nothing opened until asked.

    `tracer` is what the ending's span is made with; the process's own, looked
    up when the ending is made, where none is handed in.
    """
    return _OverConnections(connections, tracer)
