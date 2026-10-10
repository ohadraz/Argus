"""What Argus does with a delivery from the chat platform an incident is
talked about in.

Two things, for two deliveries. A person writing in an incident's thread is
ingested: recorded on that incident, once, and nothing more. What they meant is
classified later and elsewhere, by the intent agent, because the platform waits
three seconds for an answer and a model takes longer than that. And a person pressing
the button on an offer to resolve resolves the incident - credited to them,
through the platform, with the words the offer was made about (spec §16: a
person saying it is over is fact) - but only if the offer was made to them.

Which deliveries are a person writing or pressing is the platform adapter's to
say, because only it can tell a person's reply from a bot's or an edit; this
module is about finding the incident and the offer. Nothing here knows which
platform answered. It holds the port.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import Protocol

from argus_core.events import ResolutionOffered
from argus_core.models import CHAT_THREAD, Reference, Report
from chat_platform import ChatPlatformReads, Handshake, Irrelevant, Pressed, Written

logger = logging.getLogger(__name__)


class ChatRecord(Protocol):
    """The incident record, for what a chat platform's deliveries ask of it.

    A seam rather than the repositories and `resolve_incident` themselves,
    because their rows are asserted against a real database in their own
    suites. What belongs here is which deliveries reach them, and with what.
    """

    def incident_known_as(self, kind: str, values: Sequence[str]) -> str | None:
        """The incident holding any of these names of this kind, or `None`."""
        ...

    def ingest(self, incident_id: str, message: Reference, person_id: str, text: str) -> bool:
        """Records that the person wrote this on the incident, unless the
        message was ingested before; whether it was new."""
        ...

    def offer_about(self, incident_id: str, message: Reference) -> ResolutionOffered | None:
        """The offer to resolve made about this message, or `None`."""
        ...

    def offer_expired(self, incident_id: str, message: Reference) -> bool:
        """Whether the walk stopped waiting on the offer about this message."""
        ...

    def resolve(self, incident_id: str, reported: Report) -> bool:
        """Resolves the incident as a person reported it; whether it moved."""
        ...


def receive_chat_delivery(body: bytes,
                          headers: Mapping[str, str],
                          *,
                          platform: ChatPlatformReads,
                          record: ChatRecord) -> str | None:
    """Acts on one delivery from the chat platform: ingests a person writing
    in an incident's thread, or resolves the incident on a press of its offer.

    Returns the challenge where the platform is checking the address, and
    `None` for every other delivery. Raises `ChatDeliveryUnverified` for one the
    platform did not sign; every other outcome returns, because a delivery
    about something Argus does not act on was still received.
    """
    delivery = platform.parse_delivery(body, headers)

    match delivery:
        case Handshake(challenge=challenge):
            return challenge
        case Written():
            _ingest(delivery, record)
        case Pressed():
            _resolve(delivery, platform, record)
        case Irrelevant(why=why):
            # Most of what the platform delivers is not for Argus - bots,
            # edits, other conversations - so it is said where it can be
            # looked for rather than read every day.
            logger.debug("chat delivery not acted on", extra={"why": why})

    return None


def _ingest(written: Written, record: ChatRecord) -> None:
    """Records a person's words on the incident whose thread they wrote in."""
    incident_id = record.incident_known_as(CHAT_THREAD, [written.thread.value])

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


def _resolve(pressed: Pressed, platform: ChatPlatformReads, record: ChatRecord) -> None:
    """Resolves the incident a press of its offer is about, if the offer was
    made to whoever pressed it."""
    incident_id = record.incident_known_as(CHAT_THREAD, [pressed.thread.value])
    offer = (record.offer_about(incident_id, pressed.message)
             if incident_id is not None else None)

    if incident_id is None or offer is None:
        # Argus posts the button only beside an offer it recorded first, so a
        # press on none is a button it did not post, or a record it lost.
        logger.warning("press on no offer", extra={"chat_message": pressed.message.value})
        return

    if record.offer_expired(incident_id, pressed.message):
        # The walk stopped waiting for this answer and carried on. The button
        # may still be on screen until the relay takes it away; a press on it
        # answers a question nobody is asking now, and the person who still
        # means it writes again.
        logger.info("press on an expired offer", extra={"chat_message": pressed.message.value})
        return

    if offer.person_id != pressed.person_id:
        # The offer is to the person who said it was over. Anybody else
        # pressing it would be resolving the incident in their name.
        logger.info("offer pressed by someone else", extra={
            "incident_id": incident_id,
            "chat_message": pressed.message.value,
            "person_id": pressed.person_id
        })
        return

    # Credited by the name the offer was made with, or - where the platform
    # could not name them - by its id for them: the one name Argus holds, and
    # one a reader can look up.
    resolved = record.resolve(incident_id, Report(
        by=offer.person_name or offer.person_id, channel=platform.channel, note=offer.said
    ))

    if not resolved:
        # A button outlives the incident until the relay takes it away, so it
        # can be pressed after the incident ended some other way. That ending
        # stands.
        logger.info("offer pressed on an ended incident", extra={
            "incident_id": incident_id,
            "chat_message": pressed.message.value
        })
