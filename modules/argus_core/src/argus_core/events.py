from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Any, Literal, Protocol

from pydantic import BaseModel, Field, TypeAdapter

from argus_core.ids import UuidStr, new_id
from argus_core.models.actor import Actor
from argus_core.models.alert import Alert
from argus_core.models.cause import CauseType
from argus_core.models.change_event import ChangeEvent
from argus_core.models.flag_change import FlagChange
from argus_core.models.incident_status import IncidentStatus
from argus_core.models.metrics import MetricBucket

"""What Argus says about its own work as it does it (spec §4 principle 6).

The incident tables record conclusions - which candidate was blamed, what was
done, where the incident ended. These record the work: which window was asked
for, what came back, which minute was called the onset, what was formed from
it. Nothing here is read by anything that decides: an event is an account, and
an account that could change the outcome would be a participant.

Each event is its own type rather than a `kind` with a bag of fields, because a
reader has to be able to hold one and know what it is holding. `kind` is on
each of them all the same - it is what a stored row is read back by.
"""

_logger = logging.getLogger(__name__)


class RetrievalChannel(StrEnum):
    """The three ways Argus learns anything about the service (spec §16).

    Named on the request so a reader can see what was asked for even where the
    answer never arrived - a channel that failed is a fact about the
    investigation, and one that is silent in the account looks like a channel
    nobody thought to try.
    """

    METRICS = "metrics"
    LOGS = "logs"
    CHANGES = "changes"


class _Event(BaseModel):
    """What every event carries, whatever it is about.

    `at` is taken here rather than accepted from a caller: the moment belongs
    to the thing that happened, and a narration ordered by when rows reached
    the database is a narration of the database's day rather than the
    incident's.
    """

    id: UuidStr = Field(default_factory=new_id)
    incident_id: UuidStr
    at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class AlertAcknowledged(_Event):
    """Argus has the alert and has looked at nothing yet - the first line of
    every incident's story.

    An event and not a status: the status machine (spec §10) says where an
    incident can go next, and acknowledging adds nowhere to go.
    """

    kind: Literal["alert-acknowledged"] = "alert-acknowledged"
    alert: Alert


class AgentInvoked(_Event):
    """The Orchestrator handed the incident to one of its sub-agents."""

    kind: Literal["agent-invoked"] = "agent-invoked"
    agent: Actor


class StatusChanged(_Event):
    """The incident moved, and what moved it said why."""

    kind: Literal["status-changed"] = "status-changed"
    to_status: IncidentStatus
    detail: str | None = None


class RetrievalRequested(_Event):
    """A channel was asked about a span of time.

    Both bounds where the request has them, because a bounded window with one
    of them is a window nobody can check an answer against. A metrics read is
    anchored on the alert rather than bounded (spec §16), so it names where it
    was anchored and leaves the end open - which is the truth about that call,
    and better than a second bound invented here to fill the field.
    """

    kind: Literal["retrieval-requested"] = "retrieval-requested"
    channel: RetrievalChannel
    window_start: str | None = None
    window_end: str | None = None


class MetricsRetrieved(_Event):
    """The buckets a metrics read returned, stored whole.

    The span is the one the buckets actually cover rather than one asked for -
    the read is anchored, not bounded - so it is absent exactly when nothing
    came back, which is a span no answer has.
    """

    kind: Literal["metrics-retrieved"] = "metrics-retrieved"
    window_start: str | None = None
    window_end: str | None = None
    buckets: list[MetricBucket]


class LogsRetrieved(_Event):
    """The lines a log window returned, stored whole.

    Whole rather than as a reference to fetch again: the log store moves on,
    and a page that re-asked would show what the service says now instead of
    what Argus read - which is the difference between an account and a guess.
    """

    kind: Literal["logs-retrieved"] = "logs-retrieved"
    window_start: str
    window_end: str
    lines: list[str]


class ChangesRetrieved(_Event):
    """What changed on the service over the window that was asked about."""

    kind: Literal["changes-retrieved"] = "changes-retrieved"
    window_start: str
    window_end: str
    changes: list[ChangeEvent]


class ChannelsUnread(_Event):
    """The channels an investigation never asked about.

    Absence is the one thing an append-only account cannot state by itself. A
    channel nobody asked for and a channel that was read and came back empty
    leave the same silence behind, and they mean opposite things: the first is
    a gap in the investigation, the second is a finding about the service. A
    reader inferring that from what is *missing* would have to know what could
    have been there, and be right about it.

    Published once, when the investigation ends, because that is the first
    moment "never asked" is true of anything - mid-run, every unread channel is
    only unread so far.
    """

    kind: Literal["channels-unread"] = "channels-unread"
    channels: list[RetrievalChannel]


class OnsetDetected(_Event):
    """The minute the incident is judged to have started, named as the bucket
    it was found in."""

    kind: Literal["onset-detected"] = "onset-detected"
    onset: str


class HypothesisFormed(_Event):
    """One explanation the Investigator arrived at, as it arrived at it.

    Carries the candidate's own id, so the narration and the walk are the same
    hypothesis seen twice rather than two accounts that have to be reconciled.
    """

    kind: Literal["hypothesis-formed"] = "hypothesis-formed"
    hypothesis_id: UuidStr
    summary: str
    cause_type: CauseType | None
    confidence: float | None
    subject: str | None
    rank: int
    # What the candidate rests on, as the Investigator cited it. A claim
    # published without its evidence is an assertion, and an account of an
    # investigation that shows only conclusions asks its reader to take them on
    # trust - which is the one thing an autonomous agent cannot be given.
    evidence: list[str] = []


class FlagChangesRetrieved(_Event):
    """What the flag provider says has changed lately, as Mitigation read it.

    Its own event rather than a `ChangesRetrieved` with a different kind: this
    is read to *act* on, not to reason with. It carries which flag moved and
    which way, which is what an action is chosen from, where a change event
    carries prose for a model.

    Published only where a history was actually read. A provider that could not
    be reached reports nothing, and nothing is not an empty history - "nobody
    could say what changed" and "nothing changed" lead to the same place and
    are not the same fact.
    """

    kind: Literal["flag-changes-retrieved"] = "flag-changes-retrieved"
    changes: list[FlagChange]


class ActionTaken(_Event):
    """A reversible change Argus made to the service, for a candidate."""

    kind: Literal["action-taken"] = "action-taken"
    hypothesis_id: UuidStr | None
    action_type: str
    subject: str | None
    # Which way the subject was moved. Carried because "a flag was changed" is
    # the half of the sentence a reader cannot act on: whether the shop is now
    # serving with the fallback on or off is the whole point of the change, and
    # an account that leaves it out describes a button being pressed. `None`
    # where the action is not a two-state one.
    enabled: bool | None = None


class AwaitingRecovery(_Event):
    """An action has been taken and the service is being given time to answer.

    Published at the moment production has already changed, because that is
    where the account would otherwise go quiet: the flag has moved and nothing
    further is decided until a whole minute has passed and been judged. A
    reader with no line here cannot tell a slow verification from a stuck one.

    `from_minute` is the first minute that began after the action - not the
    one it fell inside, which is aggregated over seconds either side of the
    change and can only blur the two states together.
    """

    kind: Literal["awaiting-recovery"] = "awaiting-recovery"
    from_minute: str
    # A float, because the configured timeout is one - the wait is a duration
    # the operator set, not a count of anything.
    seconds_allowed: float


class RecoveryChecked(_Event):
    """One look at the service while waiting, and what it saw.

    Carries the judgement rather than the buckets it was made from. A wait
    polls every few seconds over a couple of minutes, and storing the whole
    metrics window each time would record the same numbers a dozen times to
    say one thing that fits in a boolean.
    """

    kind: Literal["recovery-checked"] = "recovery-checked"
    minute: str
    recovered: bool


class VerdictReached(_Event):
    """What the service said about an action once it had been measured."""

    kind: Literal["verdict-reached"] = "verdict-reached"
    hypothesis_id: UuidStr | None
    outcome: str


type IncidentEvent = Annotated[
    (
        AlertAcknowledged
        | AgentInvoked
        | AwaitingRecovery
        | RecoveryChecked
        | StatusChanged
        | RetrievalRequested
        | MetricsRetrieved
        | LogsRetrieved
        | ChangesRetrieved
        | ChannelsUnread
        | FlagChangesRetrieved
        | OnsetDetected
        | HypothesisFormed
        | ActionTaken
        | VerdictReached
    ),
    Field(discriminator="kind"),
]

_events = TypeAdapter[IncidentEvent](IncidentEvent)


def parse_event(row: dict[str, Any]) -> IncidentEvent:
    """Reads a stored event back as the type it was published as.

    Discriminated on `kind`, so a reader holds a `LogsRetrieved` rather than a
    dictionary it has to match on strings to interpret.
    """
    return _events.validate_python(row)


class Publisher(Protocol):
    """Where an event goes. Says nothing about how it travels.

    In-process dispatch today, a broker later: the point of the Protocol is
    that neither the components publishing nor the readers of what was
    recorded can tell the difference.
    """

    # Positional-only: a publisher is called with the event and nothing else,
    # so any single-argument function is one, whatever it happens to have
    # named its parameter.
    def __call__(self, event: IncidentEvent, /) -> None: ...


def nobody(event: IncidentEvent) -> None:
    """The default: publishing that reaches no one.

    A component publishes whether or not anything is listening, and behaves
    identically either way - which is easiest to guarantee when the ordinary
    default is nobody listening at all.
    """


def publish(event: IncidentEvent, publisher: Publisher = nobody) -> None:
    """Hands one event to a publisher, and cannot fail.

    The single place in this codebase where an exception is caught and
    discarded, and it is correct here for one reason: the account of the work
    is never part of the work. An incident that would have resolved must
    resolve even when nobody could write down that it was resolving, so a
    subscriber having a bad day costs the story a line and costs the
    investigation nothing.

    Logged at warning rather than silently, so a stream that has stopped
    recording is discoverable without reading the page and noticing a gap.
    """
    try:
        publisher(event)
    except Exception:
        _logger.warning("could not publish %s for incident %s",
                        type(event).__name__, event.incident_id, exc_info=True)


class Narrator:
    """Everything one incident says about itself, in one place.

    A component that narrates does two things at every step: name the incident
    the event belongs to, and hand it to whoever is listening. Both are the
    same for every event it will ever publish, so both are said once here
    rather than at each call - which is what keeps an incident id from being
    threaded through every function that has something to report.

    Nothing here can fail: `publish` swallows a subscriber's exception, and a
    narrator with no publisher reaches nobody by design. A component holding
    one behaves identically whether or not anybody is listening (spec §4
    principle 6), and that is easiest to guarantee when the ordinary default is
    that nobody is.
    """

    def __init__(self, incident_id: str, publisher: Publisher = nobody) -> None:
        self._incident_id = incident_id
        self._publisher = publisher

    def say(self, event: Callable[..., IncidentEvent], **about: Any) -> None:
        """Publishes one event about this incident.

        The event type is passed rather than an instance, so that the incident
        it belongs to is supplied here and cannot be omitted or got wrong at a
        call site. `about` is the rest of that event's own fields, and it is
        the event's model that validates them - this is a seam, not a schema.
        """
        publish(event(incident_id=self._incident_id, **about), self._publisher)
