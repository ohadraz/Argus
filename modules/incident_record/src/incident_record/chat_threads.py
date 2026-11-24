"""What a chat thread's deliveries ask of the incident record: which incident
a thread is, and whether a press of an offer's button is accepted.

Decisions about incidents rather than about a delivery, so they are the
record's and not the web application's: any process that hears from the chat
platform asks them the same way. They take values - the thread, the message
and the person - and never the platform's own delivery, so nothing here knows
which platform answered.

Accepting a press ends nothing. It says which ending the offer offered and
whom it is credited to; ending the incident is `AtAPersonsWord`'s, as every
other person's ending is.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from core.models import CHAT_THREAD, OfferedEnding, Reference

from incident_record.incident_conversation import IncidentConversation
from incident_record.incident_names import IncidentNames


class NotAcceptedBecause(StrEnum):
    """Why a press of an offer's button ends nothing."""

    # Argus posts the button only beside an offer it recorded first, so a
    # press on none is a button it did not post, or a record it lost.
    NO_OFFER = "no_offer"
    # The walk stopped waiting for this answer and carried on. The button may
    # still be on screen until the relay takes it away; a press on it answers
    # a question nobody is asking now.
    EXPIRED = "expired"
    # The offer is to the person who asked. Anybody else pressing it would be
    # ending the incident in their name.
    NOT_THEIRS = "not_theirs"


@dataclass(frozen=True)
class Accepted:
    """The press is accepted: the incident it ends, the way the offer offered,
    whom the ending is credited to, and the words the offer was made about."""

    incident_id: str
    ending: OfferedEnding
    credited_to: str
    note: str


@dataclass(frozen=True)
class NotAccepted:
    """The press ends nothing, and why - with the incident it was pressed on,
    where there is one."""

    because: NotAcceptedBecause
    incident_id: str | None = None


def the_incident_of_thread(names: IncidentNames, thread: Reference) -> str | None:
    """The one incident whose thread `thread` is, or `None`.

    One holder or none: a thread several incidents hold names none of them, and
    acting on one of them would be guessing.
    """
    found = names.incidents_known_as(CHAT_THREAD, [thread.value])

    return found[0].id if len(found) == 1 else None


def accept_offer(conversation: IncidentConversation,
                 names: IncidentNames,
                 thread: Reference,
                 message: Reference,
                 presser: str) -> Accepted | NotAccepted:
    """Whether `presser` pressing the button beside `message`, in `thread`,
    accepts the offer made there - and if so, what it accepts.

    The message is found by its own name and belongs to one incident, so a
    press in one incident's thread on another's message accepts nothing.
    Accepted only where the message carries an offer, the offer has not
    expired, and the person pressing is the person who wrote.

    Credited by the name the writer was given when the offer was made, or -
    where the platform could not name them - by its id for them: the one name
    Argus holds, and one a reader can look up.
    """
    incident_id = the_incident_of_thread(names, thread)
    written = conversation.message(message) if incident_id is not None else None

    if (incident_id is None or written is None or written.incident_id != incident_id
            or written.offer is None):
        return NotAccepted(NotAcceptedBecause.NO_OFFER)

    if written.offer.expired:
        return NotAccepted(NotAcceptedBecause.EXPIRED, incident_id)

    if written.person_id != presser:
        return NotAccepted(NotAcceptedBecause.NOT_THEIRS, incident_id)

    return Accepted(incident_id=incident_id,
                    ending=written.offer.ending,
                    credited_to=written.person_name or written.person_id,
                    note=written.text)
