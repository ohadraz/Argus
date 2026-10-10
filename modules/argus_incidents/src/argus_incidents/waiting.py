"""A walk waiting on a person who said the incident was over (spec D11).

Argus asked them to confirm it. Until they answer, or until they have had long
enough to, a step started is work they may be about to make pointless - so the
walk starts none. Asked between steps, never inside one: a step already running
finishes, and a press ends the walk wherever it is, as it always has.

Beside the ending rather than in the graph, for the ending's reason: what is
asked is a question about the incident record, and the walk only asks it.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Final, Protocol

from argus_core import Connections, sleep_on_the_clock, utc_now
from argus_core.events import (
    IncidentEvent,
    MessageUnderstood,
    OfferExpired,
    PersonWrote,
    Publisher,
    ResolutionOffered,
    publish,
)
from argus_core.models import Meaning, Reference

from argus_incidents.ending import EndedByAPerson, ended_by_a_person_via
from argus_incidents.repository import events

logger = logging.getLogger(__name__)

# How long a person has to confirm, counted from the latest message still
# unanswered. On the stack's clock, as every wait that stands for time passing
# in the world is.
HOW_LONG_A_PERSON_IS_WAITED_FOR: Final = timedelta(minutes=5)

# How often the incident is looked at again while waiting, in seconds of the
# stack's clock. A press shows up as the incident's ending, so this is how late
# a walk can be to notice one - short against a person's five minutes.
_A_LOOK: Final = 2.0


class WaitForPeople(Protocol):
    """Returns once nobody is left to wait on for this incident, saying whether
    anything happened that the walk has to ask about - somebody waited on, or
    the incident ended. A walk told so asks again how it ended.

    Positional-only: the incident is all it is called with, and a stand-in has
    no use for anything else.
    """

    def __call__(self, incident_id: str, /) -> bool: ...


def waiting_for_people(events_of: Callable[[str], list[IncidentEvent]],
                       ended_by_a_person: EndedByAPerson,
                       publisher: Publisher,
                       now: Callable[[], datetime] = utc_now,
                       sleep: Callable[[float], None] = sleep_on_the_clock) -> WaitForPeople:
    """The wait, over whatever reads an incident's events and its ending.

    A message is waited on until it is understood as anything but a
    resolution, until its offer has expired, or until a person ends the
    incident - the press, or anybody else's ending meanwhile. Waited on from
    the message rather than from the offer, so a walk cannot slip through
    between a message stored and its offer posted.

    The wait ends together for every message, at the latest one's deadline: a
    person saying it again is the question asked afresh. At that deadline each
    offer still standing is said to have expired, and the walk carries on. A
    message never understood in time has no offer to expire, and is carried on
    from all the same.
    """

    def wait(incident_id: str, /) -> bool:
        said_so = False

        while True:
            # Ended - by the press, or by anybody else meanwhile - is an
            # answer the walk has to hear, so it is told to ask.
            if ended_by_a_person(incident_id) is not None:
                return True

            unanswered = _unanswered(events_of(incident_id))

            if not unanswered:
                return said_so

            if not said_so:
                logger.info("waiting for a person", extra={"messages": len(unanswered)})
                said_so = True

            if now() >= max(written.at for written in unanswered) + HOW_LONG_A_PERSON_IS_WAITED_FOR:
                _expire_the_offers(incident_id, unanswered, events_of(incident_id), publisher)
                return True

            sleep(_A_LOOK)

    return wait


def waiting_for_people_via(connections: Connections,
                           publisher: Publisher,
                           now: Callable[[], datetime] = utc_now,
                           sleep: Callable[[float], None] = sleep_on_the_clock) -> WaitForPeople:
    """The real wait, bound to the connections that can answer it."""

    def events_of(incident_id: str) -> list[IncidentEvent]:
        with connections() as conn:
            return events.get_by_incident(conn, incident_id)

    return waiting_for_people(events_of, ended_by_a_person_via(connections), publisher,
                              now=now, sleep=sleep)


def _unanswered(account: list[IncidentEvent]) -> list[PersonWrote]:
    """Every message a person wrote that nothing has answered yet."""
    answered = {_key(event.message) for event in account
                if (isinstance(event, MessageUnderstood) and event.meaning is not Meaning.RESOLVE)
                or isinstance(event, OfferExpired)}

    return [event for event in account
            if isinstance(event, PersonWrote) and _key(event.message) not in answered]


def _expire_the_offers(incident_id: str,
                       unanswered: list[PersonWrote],
                       account: list[IncidentEvent],
                       publisher: Publisher) -> None:
    """Says each offer still standing has expired - one for each unanswered
    message that was offered. A message never offered has nothing to expire."""
    offered = {_key(event.message) for event in account if isinstance(event, ResolutionOffered)}
    expiring = [written.message for written in unanswered if _key(written.message) in offered]

    logger.info("offers not confirmed in time", extra={"offers": len(expiring)})

    for message in expiring:
        publish(OfferExpired(incident_id=incident_id, message=message), publisher)


def _key(message: Reference) -> tuple[str, str, str]:
    """A message as something a set can hold."""
    return message.source, message.kind, message.value
