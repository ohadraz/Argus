"""What the intent agent does with one thing a person wrote.

It records what the message was classified as, whatever that was, so the
timeline says Argus understood it - including that it found nothing to act on.
And where the person asked for an ending - the incident is over, or Argus is to
stand down - and the incident can still end that way, it offers that person the
chance to confirm: named, so the offer says who it is to, and carrying their
own words, which become the ending's note.

It never ends anything. The offer is the whole of what a classification can do,
because a model's classification of a sentence is not a person's decision - the
press that answers the offer is (spec §16). That holds for a withdrawal more
than for anything: it puts back what Argus changed.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from argus_core.events import (
    MessageUnderstood,
    Offered,
    PersonWrote,
    Publisher,
    ResolutionOffered,
    WithdrawalOffered,
    publish,
)
from argus_core.models import IncidentStatus, Meaning

logger = logging.getLogger(__name__)

# What a message meant, as the model classifies it, or `None` where it could not.
type MeaningOf = Callable[[str], Meaning | None]
# Where an incident, by id, stands now, or `None` where it cannot be found.
type StatusOf = Callable[[str], IncidentStatus | None]
# What the chat platform calls a person, by its id for them, or `None`.
type PersonNamed = Callable[[str], str | None]


def understand(written: PersonWrote,
               *,
               meaning_of: MeaningOf,
               status_of: StatusOf,
               person_named: PersonNamed,
               publisher: Publisher) -> None:
    """Records what a person's message meant, and offers them the chance to
    confirm the ending they asked for where the incident can still take it."""
    meaning = meaning_of(written.text)

    if meaning is None:
        # Nothing to act on is the one meaning that does nothing, so the
        # message costs the person an offer and nothing else - which they can
        # still make for themselves, from the page. This is how anybody learns
        # which message it cost them.
        logger.warning("message not classified", extra={
            "incident_id": written.incident_id,
            "chat_message": written.message.value
        })
        meaning = Meaning.OTHER

    publish(MessageUnderstood(incident_id=written.incident_id,
                              message=written.message,
                              meaning=meaning),
            publisher)

    offered = _the_offer_for(meaning, status_of(written.incident_id))

    if offered is None:
        return

    # Named here, once, because the name is what the ending will be credited
    # by - and asked only for an offer, so a thread full of chatter costs the
    # chat platform nothing.
    publish(offered(incident_id=written.incident_id,
                    message=written.message,
                    person_id=written.person_id,
                    person_name=person_named(written.person_id),
                    said=written.text),
            publisher)


def _the_offer_for(meaning: Meaning, status: IncidentStatus | None) -> type[Offered] | None:
    """The offer a message calls for, or `None` where it asks for no ending, or
    for one the incident - if it can be found at all - no longer accepts."""
    if status is None or not status.accepts_what_was_asked(meaning):
        return None

    match meaning:
        case Meaning.RESOLVE:
            return ResolutionOffered
        case Meaning.WITHDRAW:
            return WithdrawalOffered
        case _:
            return None
