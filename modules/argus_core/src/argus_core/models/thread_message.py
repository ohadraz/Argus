"""One message a person wrote in an incident's thread, as the incident keeps it.

Here rather than beside the repository that stores it, for the reason
`Reference` is here: the web application ingests it, the intent agent reads and
classifies it, the walk waits on it, and the agents a lead reaches are handed
it. A shape kept inside one of those parties is one the others read by
comparing spellings.

A fact about the incident rather than an account of Argus's work, which is why
it is a row and not only an event: what a person wrote is the one input to an
incident Argus did not produce, and what decides on it reads it here.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime
from enum import StrEnum
from typing import Final, Literal

from pydantic import BaseModel

from argus_core.ids import UuidStr
from argus_core.models.incident_status import IncidentStatus
from argus_core.models.meaning import Meaning
from argus_core.models.reference import Reference

# What a lead is called before its number, wherever a model is shown one and
# names it back by it.
_LEAD_LABEL: Final = "L"

# The endings a person can ask for in words and confirm with a press. Closed,
# so that whatever acts on a press has a case for each and none left over.
type OfferedEnding = Literal[IncidentStatus.RESOLVED, IncidentStatus.WITHDRAWN]


class Offer(BaseModel):
    """An ending offered back to the person who asked for it, to confirm.

    What the press reads: which ending it brings about. Who it is credited to
    is the message's writer, by the name the message carries.
    """

    ending: OfferedEnding
    # Five minutes passed with the walk waiting on it and nobody pressing. A
    # press on it changes nothing, and the walk is no longer held for it.
    expired: bool = False


class Standing(StrEnum):
    """Where a lead stands against what the Investigator read.

    A lead is weighed, never obeyed: a person can be wrong, and a lead acted on
    against the evidence would be Argus doing what it was told instead of what
    it found.
    """

    # Something read agrees with it. Evidence like any other.
    SUPPORTED = "supported"
    # Something read contradicts it. Never acted on.
    REFUTED = "refuted"
    # Nothing read bears on it either way. It may still be tried, at the
    # confidence the evidence leaves it.
    UNVERIFIED = "unverified"


class Weighing(BaseModel):
    """What the Investigator made of a lead, and why."""

    standing: Standing
    reason: str


class ThreadMessage(BaseModel):
    """What a person wrote, who they are, and when.

    `message` is the chat platform's own name for it, and its identity: a
    message the platform delivers twice is one message.
    """

    incident_id: UuidStr
    message: Reference
    # The chat platform's id for the person - all a delivery carries.
    person_id: str
    # What the chat platform calls them, asked once the message is understood
    # to want something credited to them - an ending, or a lead the postmortem
    # reports. `None` until then, or where the platform could not say, when
    # their id stands in.
    person_name: str | None = None
    text: str
    # On the stack's clock, as every moment a wait is counted from is.
    written_at: datetime
    # What the intent agent understood it to mean, once it has. `None` until
    # then - which the wait reads as a message it must still hold a walk for.
    meaning: Meaning | None = None
    # The ending offered back to the person, where they asked for one the
    # incident still accepted.
    offer: Offer | None = None
    # What the Investigator last made of it, where it was a lead - a message
    # understood as information - and an investigation has weighed it since.
    weighing: Weighing | None = None


# What people have told an incident so far, as leads in the order they wrote
# them. Asked rather than handed over once, because a person can write while
# an agent is working, and an agent asks before each turn.
type Leads = Callable[[], list[ThreadMessage]]


def no_leads() -> list[ThreadMessage]:
    """Nobody has told the incident anything - the default wherever an agent
    is run without a thread to listen to."""
    return []


def not_yet_shown(leads: Sequence[ThreadMessage],
                  shown: Sequence[ThreadMessage]) -> list[ThreadMessage]:
    """The leads written since an agent was last shown any, in the order they
    were written - each shown once, however often the thread is asked.

    A lead is the message the chat platform names, not its current standing:
    one weighed since it was shown comes back from the thread changed, and is
    still a lead the agent has read. Here rather than in each agent, because
    two agents working this out apart would come to disagree about when a lead
    is the same lead.
    """
    seen = {_identity_of(lead) for lead in shown}

    return [lead for lead in leads if _identity_of(lead) not in seen]


def labelled(leads: Sequence[ThreadMessage],
             first: int = 1) -> list[tuple[str, ThreadMessage]]:
    """Each lead with the label a model is shown it as and names it back by,
    counting from `first` in the order they were written.

    `first` is for leads written since an agent was last shown any, which are
    numbered on from those it already holds. Here rather than in each agent
    for `not_yet_shown`'s reason: two agents numbering apart would come to
    disagree about which lead a label names.
    """
    return [(f"{_LEAD_LABEL}{number}", lead) for number, lead in enumerate(leads, start=first)]


def _identity_of(lead: ThreadMessage) -> tuple[str, str, str]:
    """A lead as something a set can hold: the chat platform's name for it."""
    return lead.message.source, lead.message.kind, lead.message.value
