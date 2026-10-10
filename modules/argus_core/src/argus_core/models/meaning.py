"""What a person meant by something they wrote about an incident.

Here rather than beside the agent that classifies a message for it, for the
reason `Report` is here: the intent agent decides it, the event that accounts for
the classification carries it, and the narration says it back. A vocabulary kept inside
one of those parties is one the others read by comparing spellings.
"""

from __future__ import annotations

from enum import StrEnum


class Meaning(StrEnum):
    """The one thing a person's message is taken to say.

    Closed, because each member is something Argus does or deliberately does
    not do, and a meaning nothing acts on is one a reader of the timeline would
    wait on for ever. Five rather than the two that ask for an ending: what a
    message was read as is recorded when it is read, and a reading that could
    only say "resolve", "withdraw" or "neither" would have to be done again for
    the question and the new fact the person may have written instead.
    """

    # The person says the incident is over - they ended it, or it ended and
    # they saw it. Offered back to them to confirm, never acted on as read.
    RESOLVE = "resolve"
    # The person asks something about the incident.
    QUESTION = "question"
    # The person tells Argus something about the incident it may not know.
    INFORMATION = "information"
    # The person tells Argus to stop and leave the incident to them - they are
    # taking it over. What a withdrawal from the page does, asked for in words,
    # and offered back to them to confirm as a resolution is.
    WITHDRAW = "withdraw"
    # Anything else: a thank-you, a conversation between people, a reaction.
    OTHER = "other"
