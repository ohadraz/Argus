"""What the intent agent does with one thing a person wrote.

It keeps what the message was classified as, whatever that was, on the
incident's record, and says so, so the timeline says Argus understood it -
including that it found nothing to act on. And where the person asked for an
ending - the incident is over, or Argus is to stand down - and the incident can
still end that way, it offers that person the chance to confirm: named, so the
offer says who it is to, and carrying their own words, which become the
ending's note. A lead's writer is named too, because the postmortem owes them
the line it reports their lead in. A question is answered from the incident's
record, whatever the incident's status.

The record is the work and the event the account of it, so the record is
written first. What decides on a message - the wait, the press - reads the
record, and an account that went missing costs the timeline a line. An answer
is the one thing worked out before the record is written, so a question is
never kept as understood and left unanswered.

It never ends anything. Towards an ending, the offer is the whole of what a
classification can do, because a model's classification of a sentence is not a
person's decision - the press that answers the offer is (spec §16). That holds
for a withdrawal more than for anything: it puts back what Argus changed.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Final, Protocol

from argus_core.events import (
    MessageUnderstood,
    Offered,
    Publisher,
    QuestionAnswered,
    ResolutionOffered,
    WithdrawalOffered,
    publish,
)
from argus_core.models import IncidentStatus, Meaning, OfferedEnding, Reference, ThreadMessage

logger = logging.getLogger(__name__)

# What a message meant, as the model classifies it, or `None` where it could not.
type MeaningOf = Callable[[str], Meaning | None]
# The answer to a question, from the record of the incident it was asked in, or
# `None` where the model gave none it could use.
type AnswerOf = Callable[[str], str | None]

# What a person whose question could not be answered is told, so they learn it
# was read.
COULD_NOT_ANSWER: Final = (
    "I could not answer that from what Argus has recorded. The incident's page "
    "has the whole timeline."
)
# Where an incident, by id, stands now, or `None` where it cannot be found.
type StatusOf = Callable[[str], IncidentStatus | None]
# What the chat platform calls a person, by its id for them, or `None`.
type PersonNamed = Callable[[str], str | None]


class ConversationRecord(Protocol):
    """The incident's record of what people wrote, as far as understanding a
    message writes to it."""

    def understood(self, message: Reference, meaning: Meaning) -> None:
        """Keeps what the message was understood to mean."""
        ...

    def named(self, message: Reference, person_name: str | None) -> None:
        """Keeps what the chat platform calls the message's writer, or that it
        could not say."""
        ...

    def offered(self, message: Reference, ending: OfferedEnding) -> None:
        """Keeps that the message's writer was offered this ending."""
        ...


def understand(written: ThreadMessage,
               *,
               meaning_of: MeaningOf,
               answer_of: AnswerOf,
               status_of: StatusOf,
               person_named: PersonNamed,
               record: ConversationRecord,
               publisher: Publisher) -> None:
    """Records what a person's message meant, offers them the chance to
    confirm the ending they asked for where the incident can still take it,
    and answers what they asked."""
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

    # Answered before the meaning is kept: a process that dies mid-answer then
    # leaves the question to be asked again, where answering after would leave
    # it understood and never answered.
    answered = (_the_answer_to(written, answer_of, status_of)
                if meaning is Meaning.QUESTION else None)

    record.understood(written.message, meaning)
    publish(MessageUnderstood(incident_id=written.incident_id,
                              message=written.message,
                              meaning=meaning),
            publisher)

    if meaning is Meaning.QUESTION:
        if answered is not None:
            publish(QuestionAnswered(incident_id=written.incident_id,
                                     message=written.message,
                                     answer=answered),
                    publisher)

        return

    if meaning is Meaning.INFORMATION:
        # A lead is reported in the postmortem, which owes its writer the line.
        record.named(written.message, person_named(written.person_id))

        return

    offer = _the_offer_for(meaning, status_of(written.incident_id))

    if offer is None:
        return

    offered, ending = offer
    # Named here, once, because the name is what the ending will be credited
    # by - and asked only for an offer or a lead, so a thread full of chatter
    # costs the chat platform nothing.
    person_name = person_named(written.person_id)

    record.named(written.message, person_name)
    record.offered(written.message, ending)
    publish(offered(incident_id=written.incident_id,
                    message=written.message,
                    person_id=written.person_id,
                    person_name=person_name,
                    said=written.text),
            publisher)


def _the_answer_to(written: ThreadMessage,
                   answer_of: AnswerOf,
                   status_of: StatusOf) -> str | None:
    """What the person is told in answer to their question, or `None` where
    the incident cannot be found - there is no record to answer from.

    Answered whatever the incident's status: a question about an incident that
    has ended is still about something Argus recorded. Where the model gave no
    usable answer, the person is told so rather than left with nothing, and
    the warning is how anybody learns which question it was.
    """
    if status_of(written.incident_id) is None:
        return None

    answered = answer_of(written.text)

    if answered is None:
        logger.warning("question not answered", extra={
            "incident_id": written.incident_id,
            "chat_message": written.message.value
        })

        return COULD_NOT_ANSWER

    return answered


def _the_offer_for(meaning: Meaning,
                   status: IncidentStatus | None) -> tuple[type[Offered], OfferedEnding] | None:
    """The offer a message calls for, and the ending it offers, or `None` where
    it asks for no ending, or for one the incident - if it can be found at all -
    no longer accepts."""
    if status is None or not status.accepts_what_was_asked(meaning):
        return None

    match meaning:
        case Meaning.RESOLVE:
            return ResolutionOffered, IncidentStatus.RESOLVED
        case Meaning.WITHDRAW:
            return WithdrawalOffered, IncidentStatus.WITHDRAWN
        case _:
            return None
