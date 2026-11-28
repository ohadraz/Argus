"""What Argus does with a delivery from the chat platform an incident is
talked about in.

Two things, for two deliveries. A person writing in an incident's thread is
ingested: recorded on that incident, once, and nothing more. What they meant is
classified later and elsewhere, by the intent reader, because the platform waits
three seconds for an answer and a model takes longer than that. And a person pressing
the button on an offer ends the incident the way the offer offered - resolved
(spec §16: a person saying it is over is fact) or withdrawn - credited to them,
through the platform, with the words the offer was made about, but only if the
offer was made to them.

Which deliveries are a person writing or pressing is the platform adapter's to
say, because only it can tell a person's reply from a bot's or an edit. Which
incident a thread is, and whether a press accepts the offer, are the incident
record's (`the_incident_of_thread`, `accept_offer`), because they are decisions
about incidents; this module carries the delivery to them and says what they
answered. Nothing here knows which platform answered. It holds the port.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Protocol, assert_never

from chat_platform import ChatPlatformReads, Handshake, Irrelevant, Pressed, Written
from core.models import IncidentStatus, Reference, Report, ReportChannel
from incident_record import Accepted, EndedAsSaid, NotAccepted, NotAcceptedBecause, PersonsEnding

logger = logging.getLogger(__name__)


class ChatRecord(Protocol):
    """The incident record, for what a chat platform's deliveries ask of it.

    A seam rather than the incident record's roles and decisions themselves,
    because those are asserted in its own suite. What belongs here is which
    deliveries reach them, and with what.
    """

    def incident_of_thread(self, thread: Reference) -> str | None:
        """The one incident whose thread this is, or `None`."""
        ...

    def ingest(self, incident_id: str, message: Reference, person_id: str, text: str) -> bool:
        """Records that the person wrote this on the incident, unless the
        message was ingested before; whether it was new."""
        ...

    def accept_offer(self,
                     thread: Reference,
                     message: Reference,
                     presser: str) -> Accepted | NotAccepted:
        """Whether the person pressing the button beside the message, in the
        thread, accepts the offer made there - and if so, what it accepts."""
        ...

    def resolve(self, incident_id: str, reported: Report) -> PersonsEnding:
        """Resolves the incident as a person reported it."""
        ...

    def withdraw(self, incident_id: str, reported: Report) -> PersonsEnding:
        """Withdraws the incident as a person asked."""
        ...


def receive_chat_delivery(body: bytes,
                          headers: Mapping[str, str],
                          *,
                          platform: ChatPlatformReads,
                          record: ChatRecord) -> str | None:
    """Acts on one delivery from the chat platform: ingests a person writing
    in an incident's thread, or ends the incident on a press of its offer.

    Returns the challenge where the platform is checking the address, and
    `None` for every other delivery. Raises `ChatDeliveryUnverified` for one the
    platform did not sign, and `ChatDeliveryUnreadable` for one it signed in
    none of its shapes; every other outcome returns, because a delivery
    about something Argus does not act on was still received.
    """
    delivery = platform.parse_delivery(body, headers)

    match delivery:
        case Handshake(challenge=challenge):
            return challenge
        case Written():
            _ingest(delivery, record)
        case Pressed():
            _confirm(delivery, platform, record)
        case Irrelevant(why=why):
            # Most of what the platform delivers is not for Argus - bots,
            # edits, other conversations - so it is said where it can be
            # looked for rather than read every day.
            logger.debug("chat delivery not acted on", extra={"why": why})

    return None


def _ingest(written: Written, record: ChatRecord) -> None:
    """Records a person's words on the incident whose thread they wrote in."""
    incident_id = record.incident_of_thread(written.thread)

    if incident_id is None:
        # Argus is in the channel for its war rooms, and people hold other
        # conversations there.
        logger.info("chat message in no incident's thread", extra={
            "chat_thread": written.thread.value
        })
        return

    if not record.ingest(incident_id, written.message, written.person_id, written.text):
        # The platform sent it again, believing the first went unanswered.
        logger.info("chat message ingested before", extra={
            "chat_message": written.message.value
        })


def _confirm(pressed: Pressed, platform: ChatPlatformReads, record: ChatRecord) -> None:
    """Ends the incident a press of its offer is about the way the offer
    offered - resolved or withdrawn - if the record accepts the press, and says
    why where it does not."""
    answered = record.accept_offer(pressed.thread, pressed.message, pressed.person_id)

    match answered:
        case Accepted():
            _end(answered, pressed, platform, record)
        case NotAccepted(because=because, incident_id=incident_id):
            _say_why_not(because, incident_id, pressed)
        case _:
            assert_never(answered)


def _say_why_not(because: NotAcceptedBecause, incident_id: str | None, pressed: Pressed) -> None:
    """Says why a press ended nothing - a warning only where Argus never posted
    the button, since every other refusal is an ordinary day."""
    match because:
        case NotAcceptedBecause.NO_OFFER:
            logger.warning("press on no offer", extra={"chat_message": pressed.message.value})
        case NotAcceptedBecause.EXPIRED:
            # The person who still means it writes again.
            logger.info("press on an expired offer",
                        extra={"chat_message": pressed.message.value})
        case NotAcceptedBecause.NOT_THEIRS:
            logger.info("offer pressed by someone else", extra={
                "incident_id": incident_id,
                "chat_message": pressed.message.value,
                "person_id": pressed.person_id
            })
        case _:
            assert_never(because)


def _end(accepted: Accepted, pressed: Pressed, platform: ChatPlatformReads,
         record: ChatRecord) -> None:
    """Ends the incident the way the accepted offer offered, credited as the
    record says, through the platform, with the words the offer was made
    about."""
    reported = Report(by=accepted.credited_to,
                      channel=ReportChannel.CHAT_PLATFORM,
                      platform=platform.name,
                      note=accepted.note)

    match accepted.ending:
        case IncidentStatus.RESOLVED:
            ended = record.resolve(accepted.incident_id, reported)
        case IncidentStatus.WITHDRAWN:
            ended = record.withdraw(accepted.incident_id, reported)
        case _:
            assert_never(accepted.ending)

    if not isinstance(ended, EndedAsSaid):
        # A button outlives the incident until the relay takes it away, so it
        # can be pressed after the incident ended some other way - or, for a
        # withdrawal, after the walk left it somewhere a withdrawal is refused.
        # That ending stands.
        logger.info("offer pressed on an ended incident", extra={
            "incident_id": accepted.incident_id,
            "chat_message": pressed.message.value
        })
