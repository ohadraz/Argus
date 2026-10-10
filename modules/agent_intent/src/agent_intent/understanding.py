"""What the intent agent does with one thing a person wrote.

It records what the message was classified as, whatever that was, so the
timeline says Argus understood it - including that it found nothing to act on.
And where the person said the incident is over, and the incident can still be
resolved, it offers that person the chance to confirm: named, so the offer says
who it is to, and carrying their own words, which become the resolution's note.

It never resolves anything. The offer is the whole of what a classification can
do, because a model's classification of a sentence is not a person's decision -
the press that answers the offer is (spec §16).
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from argus_core.events import (
    MessageUnderstood,
    PersonWrote,
    Publisher,
    ResolutionOffered,
    publish,
)
from argus_core.models import Meaning

logger = logging.getLogger(__name__)

# What a message meant, as the model classifies it, or `None` where it could not.
type MeaningOf = Callable[[str], Meaning | None]
# Whether an incident, by id, may still be reported resolved.
type AcceptsResolution = Callable[[str], bool]
# What the chat platform calls a person, by its id for them, or `None`.
type PersonNamed = Callable[[str], str | None]


def understand(written: PersonWrote,
               *,
               meaning_of: MeaningOf,
               accepts_resolution: AcceptsResolution,
               person_named: PersonNamed,
               publisher: Publisher) -> None:
    """Records what a person's message meant, and offers them the chance to
    confirm a resolution where that is what they said."""
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

    if meaning is not Meaning.RESOLVE or not accepts_resolution(written.incident_id):
        return

    # Named here, once, because the name is what the resolution will be
    # credited by - and asked only for an offer, so a thread full of chatter
    # costs the chat platform nothing.
    publish(ResolutionOffered(incident_id=written.incident_id,
                              message=written.message,
                              person_id=written.person_id,
                              person_name=person_named(written.person_id),
                              said=written.text),
            publisher)
