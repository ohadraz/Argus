from __future__ import annotations

from enum import StrEnum
from typing import Final, Protocol

from argus_incidents.repository.events import RecordedEvent
from argus_narration import NarrationLine, a_narration_line

from agent_communicator.policy import Register, how_it_is_said

"""Slack as a projection of the event log, fed by a relay.

Nothing in the walk calls this, and that is the whole point. A step of an
incident reaches a human because it was published, not because whoever wrote
that step remembered to report it - so an agent added tomorrow is heard from on
the day it publishes its first event, and no investigation has to know that
Slack exists.

The log is already a transactional outbox: every event is written on the
connection its decision is written on, inside a savepoint, so an event exists
if and only if the thing it describes does. This is the publisher over it -
polling, at-least-once, with a durable place of its own.

What that place is kept in, and where the log is read from, are seams. This
module decides what gets said and in what order and knows about no database at
all; `following` is where those seams meet postgres.

At-least-once rather than exactly-once, deliberately. A line said twice is a
nuisance a reader forgives; a line nobody ever says is the failure this exists
to prevent, so the place only ever moves past a line that landed.
"""

# Which reader this is, in `event_cursor`. Named for the destination rather
# than for the process, so a second relay to a second destination is a second
# row keeping its own pace - not a second deployment fighting over one place.
SLACK_RELAY: Final = "slack"

# How much one look at the log reads. Big enough that catching up after a
# restart takes a few passes rather than hundreds, small enough that a relay an
# hour behind does not read an hour of events into memory at once.
_A_BATCH: Final = 100


class Backlog(Protocol):
    """What has been published since a place, oldest first and capped.

    The relay's whole view of the log: no incident to ask about, because a
    relay follows everything rather than watching one thing.
    """

    def __call__(self, since: int, batch: int, /) -> list[RecordedEvent]: ...


class Place(Protocol):
    """Where this reader got to, kept somewhere that outlives the process.

    Two methods rather than a value passed in and out, because the keeping is
    the point: a relay that returned its new place and trusted its caller to
    store it would lose everything the moment a caller forgot.
    """

    def where(self) -> int: ...

    def move_to(self, seq: int, /) -> None: ...


class Outcome(StrEnum):
    """What became of one line at its destination.

    Three rather than two, because "it did not land" is two different facts
    with opposite consequences. A throttle or a workspace that did not answer
    says nothing about the line, so it keeps its place and is tried again; a
    refusal about the line itself - a renamed channel, a revoked token - will
    say the same thing on every pass for as long as the workspace stays the
    way it is, and a relay waiting for it to change would go silent about
    every line behind it too.

    The destination decides which it was and writes a lost line down where a
    reader will find it. All the relay does with that is move, or wait.
    """

    SAID = "said"
    NOT_NOW = "not-now"
    NEVER = "never"


class Delivery(Protocol):
    """Where a line goes, how loudly it is said, and what became of it.

    Answers rather than raises, because "Slack refused" is an ordinary outcome
    of talking to Slack and not an error in the relay: the adapter already
    turns a refusal, a throttle and an unreachable workspace into an answer.

    The register travels with the line rather than being worked out at the far
    end: how loudly something is said is the policy's decision, and what that
    looks like - a thread reply, a channel message, a digest - is the
    destination's.

    A Protocol rather than a `Callable` alias so a test can build one against
    the contract itself.
    """

    def __call__(self,
                 incident_id: str,
                 line: NarrationLine,
                 register: Register, /) -> Outcome: ...


def relay_once(backlog: Backlog,
               place: Place,
               deliver: Delivery,
               batch: int = _A_BATCH) -> int:
    """One look at the log: says what is new, and moves on behind itself.

    One look rather than a loop, so that what schedules it - a process, a test,
    a single call in a walkthrough - is somebody else's decision. Returns how
    many lines it delivered, which is what a caller logs and what a test asks.

    Each line is delivered before the place moves past it. A relay killed
    between the two says one line twice, which is the direction this is meant
    to fail in.

    A line that could not be said *now* stops the batch where it is. The ones
    behind it wait rather than going out in front of it, because an account
    delivered with its middle missing reads as a different incident - and the
    gap would never be filled, the place having moved past it.

    A line that will never be said is passed over instead. The destination has
    already written it down where a reader will find it, and waiting for a
    renamed channel to come back is how a relay stays silent about an incident
    that is still running.

    A line nobody needs to hear is passed over and the place moves past it all
    the same: a relay that stopped at the first retrieval would sit there for
    ever, re-reading something it is never going to say.
    """
    delivered = 0

    for recorded in backlog(place.where(), batch):
        register = how_it_is_said(recorded.event)

        if register is not Register.UNSAID:
            outcome = deliver(recorded.event.incident_id,
                              a_narration_line(recorded.event),
                              register)

            if outcome is Outcome.NOT_NOW:
                break

            if outcome is Outcome.SAID:
                delivered += 1

        place.move_to(recorded.seq)

    return delivered
