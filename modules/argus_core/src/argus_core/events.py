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

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Literal, Protocol

from pydantic import BaseModel, Field, TypeAdapter

from argus_core.ids import UuidStr, new_id
from argus_core.models.action import (
    ActionIdentity,
    ActionType,
    Platform,
    Verdict,
)
from argus_core.models.actor import Actor
from argus_core.models.alert import Alert
from argus_core.models.change_event import ChangeEvent
from argus_core.models.evidence import Evidence
from argus_core.models.failure_mode import FailureMode
from argus_core.models.fix import FixOutcome
from argus_core.models.flag_change import FlagChange
from argus_core.models.incident_status import IncidentStatus
from argus_core.models.metrics import MetricBucket
from argus_core.models.placement import RecordedPlacement
from argus_core.models.pull_request import OpenedPullRequest
from argus_core.models.reading import RetrievalChannel
from argus_core.models.refusal import Refusal
from argus_core.models.undone import Undone
from argus_core.telemetry import ARGUS_INCIDENT_ID
from argus_core.timestamps import utc_now

_logger = logging.getLogger(__name__)


class _Event(BaseModel):
    """What every event carries, whatever it is about.

    `at` is taken here rather than accepted from a caller: the moment belongs
    to the thing that happened, and a narration ordered by when rows reached
    the database is a narration of the database's day rather than the
    incident's.
    """

    id: UuidStr = Field(default_factory=new_id)
    incident_id: UuidStr
    at: datetime = Field(default_factory=utc_now)


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

    `stopped_before_the_alert` is the other thing a reader needs and the span
    cannot say. A window ending well before the alert fired is a service that
    stopped reporting, and a count of the minutes it did report is a true figure
    about the time before the incident - so the count alone reads as a short
    window in the three places this event is narrated to. Carried beside the span
    rather than inferred from it, because the alert's own firing time is not in
    this event and a reader comparing one to the other would need both.
    """

    kind: Literal["metrics-retrieved"] = "metrics-retrieved"
    window_start: str | None = None
    window_end: str | None = None
    buckets: list[MetricBucket]
    stopped_before_the_alert: bool = False


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


class RetrievalUnanswered(_Event):
    """Something Argus asked for and could not be told.

    The third silence, and the one `ChannelsUnread` above sets up without
    covering. A channel nobody asked about and a channel that answered with
    nothing already mean opposite things; a channel that was asked and would not
    answer means a third, and without a line of its own it reads as the second -
    as a finding about the service rather than a gap in what Argus knows.

    Published from wherever the asking happens, which is three places that know
    different amounts. So `what_was_asked` is a plain string rather than a tag:
    its publishers speak three vocabularies - a tool the model named, a channel
    the walk read, the shop's own metrics - and a single enumeration over them
    would be a fourth vocabulary that none of them uses.

    `minute` is the one a verdict is being judged on, where there is one. A read
    that failed inside a verification window is not merely a read that failed:
    it is the reason a confirmation took longer than the window it was measured
    over, and a person reading the incident cannot work that out from a line
    that names no minute. `None` everywhere else, for the reason
    `RecoveryChecked` carries its own - the minute belongs to the judgement, not
    to the asking.

    It says nothing about what happens next, and must not: the same fact is a
    pass of a poll that will be tried again, an investigation continuing without
    one channel, and a model recovering on its next turn. Whoever asked decides,
    and this is only the record that they were not answered.

    `because` is what the asking failed with, kept apart from what was asked for
    the reason `RememberingFailed` keeps its refusal apart: a read that timed out
    and one that was refused are fixed by different people, and a subject with
    the reason folded into it reads as neither ("the service's metrics: timed out
    for 10:14" says the timing out lasted a minute).
    """

    kind: Literal["retrieval-unanswered"] = "retrieval-unanswered"
    what_was_asked: str
    because: str | None = None
    minute: str | None = None


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
    failure_mode: FailureMode | None
    confidence: float | None
    subject: str | None
    # The two ends of the change the candidate blamed, as the Investigator was
    # told them. Values rather than words in `summary`: the narration draws a
    # transition struck-through and picked out, the way the flag table does,
    # and a renderer picking the states out of a sentence cannot tell one from
    # a sentence that merely uses the word.
    from_state: str | None = None
    to_state: str | None = None
    rank: int
    # What the candidate rests on, as the Investigator cited it. A claim
    # published without its evidence is an assertion, and an account of an
    # investigation that shows only conclusions asks its reader to take them on
    # trust - which is the one thing an autonomous agent cannot be given.
    evidence: list[Evidence] = []


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


class PlacementRecorded(_Event):
    """Where the alerting service's pods were running, recorded against the
    onset before anything was done.

    Published because it is the basis of an action and the one reading nothing
    else in the record holds: a deployment history says what was deployed, and a
    replica moved to another card with nothing deployed is visible only here. The
    onset travels with it because which pods started at the onset is what the
    placement is read for, and a reader has the event and not the walk.
    """

    kind: Literal["placement-recorded"] = "placement-recorded"
    placement: RecordedPlacement


class ActionTaken(_Event):
    """A change Argus made to the service, for a candidate."""

    kind: Literal["action-taken"] = "action-taken"
    hypothesis_id: UuidStr | None
    # The tag, not a free string: every renderer of this event matches on it
    # exhaustively, so a second kind of action is a type error where the words
    # for it are written rather than a row that renders as its own identifier.
    action_type: ActionType
    subject: str | None
    # Which way the subject was moved. Carried because "a flag was changed" is
    # the half of the sentence a reader cannot act on: whether the shop is now
    # serving with the fallback on or off is the whole point of the change, and
    # an account that leaves it out describes a button being pressed. `None`
    # where the action is not a two-state one.
    enabled: bool | None = None
    # The service this action's subject is a dependency of, where it is one -
    # which is to say, where Argus acted on something it was never paged about.
    # `None` is the ordinary incident, in which the subject is the service that
    # alerted and there is nothing to explain.
    #
    # Carried rather than worked out by whoever renders the line. The comparison
    # needs the incident's own alerting service, which an account rendered from
    # events alone does not have, and putting it on every action line so that
    # one kind of line could compare against it would have every publisher
    # restate a fact about the incident on every row it wrote.
    a_dependency_of: str | None = None
    # The card a pin held the deployment to, and `None` for every other kind.
    # Carried beside the subject rather than in it, because the subject of a pin
    # is the application: which card is the half a reader checks against the
    # placement recorded at the onset, and nothing else on the line says it.
    accelerator: str | None = None


class AwaitingRecovery(_Event):
    """An action has been taken and the service is being given time to answer.

    Published at the moment production has already changed, because that is
    where the account would otherwise go quiet: the flag has moved and nothing
    further is decided until a whole minute has passed and been judged. A
    reader with no line here cannot tell a slow verification from a stuck one.

    `from_minute` is the first minute that began after the change was in force -
    not the one the action fell inside, which is aggregated over seconds either
    side of the change and can only blur the two states together, and not the
    minute after the action where a change takes time to reach the service.

    Published once the service has been read, because `seconds_allowed` is
    measured off its window (§16) rather than configured: said before the first
    reading it would be a guess, and this line is the one a reader takes the
    length of the wait from.
    """

    kind: Literal["awaiting-recovery"] = "awaiting-recovery"
    from_minute: str
    # A float, because it is a span between two instants - how long the clear
    # minutes a recovery must hold run for, from the moment the change arrived.
    seconds_allowed: float


class RecoveryChecked(_Event):
    """One look at the service while waiting, and what it saw.

    Carries the judgement rather than the buckets it was made from. A wait
    polls every few seconds over a couple of minutes, and storing the whole
    metrics window each time would record the same numbers a dozen times to
    say one thing that fits in a boolean.

    Two minutes travel here and they are different facts. `minute` is the one
    the verdict is read from - the first whole minute the change was in force
    for, which is about Argus - and `recovered_minute` is the one the metrics
    date the recovery at, which is about the service. Keeping both is what lets
    a reader see that a shop came back at 11:08 and Argus acted at 11:10, and
    the write-up is the only place that difference can currently be seen at all.

    `recovered_minute` is recorded rather than re-derived because it is the one
    measurement nothing downstream can repeat. The postmortem reads a window
    bounded by the incident's close, not the window this wait polled, so a
    second answer computed there would be computed over different minutes - and
    two windows are how one incident comes to carry two recovery times. Read
    from the account, as the onset already is (spec §16).

    Absent on every look that found the service still failing, since those have
    nothing to date, and absent too on a confirmation nothing can date: the
    verdict is reached on a window whose departure need not have persisted.
    """

    kind: Literal["recovery-checked"] = "recovery-checked"
    minute: str
    recovered: bool
    recovered_minute: str | None = None


class VerdictReached(_Event):
    """What the service said about an action once it had been measured.

    The verdict is carried as the value rather than as its spelling: the four
    answers already have a name in this system, and an event typed `str` is
    one every reader downstream has to recognise a word in - which is how a
    page and a policy end up matching on different sets of four.
    """

    kind: Literal["verdict-reached"] = "verdict-reached"
    hypothesis_id: UuidStr | None
    outcome: Verdict


class CandidateSelected(_Event):
    """The walk moved on to the next explanation worth testing.

    Which candidate is under test now is not derivable from the ranked list the
    investigation published: the walk skips any it cannot act on, so a reader
    following along has no way to work out which explanation an attempt belongs
    to. The summary and the confidence travel because they are what the reader
    would otherwise go back to the list for, and a list read later is a list
    that may have been added to since.
    """

    kind: Literal["candidate-selected"] = "candidate-selected"
    hypothesis_id: UuidStr
    summary: str
    # Nullable because a hypothesis's is: a candidate that named no cause has
    # no confidence to state, and `HypothesisFormed` carries it the same way.
    confidence: float | None


class ActionRefused(_Event):
    """An action was proposed and the gate would not let it through.

    The autonomy boundary holding is the most important thing Argus publishes
    about itself (spec §13): every other event says what it did, and this says
    what it declined to do and why. The reason is carried as the value for the
    reason a verdict is - two refusals mean different things to whoever reads
    them, and a page comparing sentences would eventually match neither.
    """

    kind: Literal["action-refused"] = "action-refused"
    # Absent where the walk reached the gate with no candidate at all: the
    # proposal answers a hypothesis it does not have with no action, and the
    # gate then refuses an action nobody proposed. Nullable for the reason
    # `ActionTaken` and `VerdictReached` are - a refusal with nothing to pin it
    # to is still a refusal, and skipping it would leave the gap this event
    # exists to close.
    hypothesis_id: UuidStr | None
    refusal: Refusal


class ActionRecommended(_Event):
    """An action Argus worked out, declined to take, and is handing on.

    The other half of the refusal beside it. That one says something did not
    happen and why; this is the only thing that says what should. An incident
    that published the refusal alone would report a cause, a reason for
    inaction, and no next step - which is worse than escalating, because
    escalation at least announces that a person is needed.

    Its own event rather than a field on `ActionRefused`, because five of the
    six refusals have nothing to recommend: they reject the action itself, and
    a reader told to go and do the thing Argus was stopped from doing would be
    told to cross the boundary Argus just held.

    `action_type` and `subject` mirror `ActionTaken` for the reason that one
    carries them - the tag is what a renderer matches on, and the subject is
    the half a person can act on. "Revert a feature flag" is not something
    anybody can go and do; the flag's name is.
    """

    kind: Literal["action-recommended"] = "action-recommended"
    hypothesis_id: UuidStr | None
    action_type: ActionType
    subject: str | None


class AlarmDisproven(_Event):
    """The window held none of what the alarm claimed, and what it was judged on.

    The one event here that reports the absence of an incident. Everything else
    on a timeline says what Argus found or did about something that was
    happening; this says the rule fired about a series the service never moved,
    and that the rule rather than the service is what to look at.

    Its own event rather than a kind of `StatusChanged`, for the reason
    `ActionRecommended` is not a field on `ActionRefused`: a reader given the
    status alone learns that Argus stopped and not why it was entitled to.

    `signals_judged`, the two minutes and `minutes_judged` are the whole of why
    the event exists. A disproof is the only claim in a walk that nothing later
    can check - no recovery confirms it and no next poll contradicts it - so the
    grounds travel with it or they are not recorded anywhere. The count is not
    the span: a window whose readings stop part way through holds fewer minutes
    than its ends suggest, and a reader has to be able to see which they were
    handed.
    """

    kind: Literal["alarm-disproven"] = "alarm-disproven"
    condition: str
    signals_judged: tuple[str, ...]
    earliest_minute: str
    latest_minute: str
    minutes_judged: int


class PlatformUnavailable(_Event):
    """A platform Argus acts through did not answer, and what went with it.

    The account of a thing that is never about one action. Five of the seven
    generic mitigations reach the estate through the deployment platform, so a
    platform that is not answering has taken five away at once - and an incident
    that was then mitigated by the one action on a live platform reads, without
    this, as though Argus simply preferred that action. Which is the record
    misstating the reasoning it exists to hold.

    One per incident and not one per candidate passed over. The fact is about the
    platform, and repeated against each candidate it teaches a reader to skim
    exactly the sentence that explains the outcome.

    Named for the platform rather than for the exception a tool raised.
    `PlatformUnreachable` is that exception and lives in `mcp_transport`; this is
    what the incident's record says happened, and one name for both is one a
    reader will eventually take for the other.

    `actions_unavailable` is carried rather than looked up from the mapping that
    holds it, though the two agree today. An event is read months later without
    the code that published it, and a further mitigation added in between changes
    what the platform carries *now* - it must not change what an incident from
    before it says went away then.
    """

    kind: Literal["platform-unavailable"] = "platform-unavailable"
    platform: Platform
    actions_unavailable: list[ActionType]


class MitigationResumed(_Event):
    """A restarted walk found this candidate's verdict already recorded.

    The account of a gap rather than of a decision. The verdict was reached and
    published by the walk that took the action; this says that a second walk
    picked the incident up and read that answer back rather than acting again -
    which is how a reader tells "Argus tried once" from "Argus tried twice".
    """

    kind: Literal["mitigation-resumed"] = "mitigation-resumed"
    hypothesis_id: UuidStr
    outcome: Verdict


class ChangeUndone(_Event):
    """One change an incident made, put back - or found not to be Argus's to
    put back.

    Published per change rather than per withdrawal, because an incident that
    changed three flags and restored two of them is not a withdrawal that
    worked. The outcome is carried as the value: "nothing was written" has two
    meanings here, and they are the difference between somebody else owning the
    flag now and nobody being able to read it.
    """

    kind: Literal["change-undone"] = "change-undone"
    # What was put back, whatever kind of thing it is. `subject` rather than
    # `flag` because it is the word the rest of the model already uses for
    # this - `ActionIdentity.subject`, `the_subject_of` - and a flag was only
    # ever one of the things an action acts on. A rolled-back deployment is
    # put back by application.
    subject: str
    outcome: Undone
    detail: str


class FixAttempted(_Event):
    """Argus looked at the code, and this is what came of it (spec §7.4).

    The one step whose outcome the status cannot carry. A mitigated incident is
    mitigated whether a fix was proposed, was not warranted, or could not be
    proposed at all (§10) - so without this, the only step that ends with
    somebody else's turn leaves no account of itself, and "Argus read the code
    and found nothing to change" arrives looking exactly like "Argus could not
    reach the repository".

    The pull request travels whole rather than as a link, because what a reader
    does next is open it, and the number alone identifies it to the API that
    issued it and to nobody else. It is absent for both of the outcomes that
    proposed nothing, which is why the outcome is a value of its own rather
    than something derived from whether this field is set.

    `detail` is what happened said once, in the words of whichever branch
    produced it - the address for a proposal, the refusal for a failure. It is
    not the sentence a destination shows: that is the renderer's, and three
    destinations rendering the same event differently is the point of keeping
    them apart.
    """

    kind: Literal["fix-attempted"] = "fix-attempted"
    outcome: FixOutcome
    pull_request: OpenedPullRequest | None = None
    detail: str


class PostmortemWritten(_Event):
    """The incident written up, in the few lines somebody would read first.

    The summary rather than the document. The whole postmortem is a row of its
    own and a page of its own; what an account needs is the sentence a reader
    stops at - what caused it, what it cost, and how long people spent on it -
    and a destination that wanted more has somewhere to send them.

    Every field is optional because the document's are: a postmortem written
    from an incident nobody recorded hours against is still a postmortem, and
    a zero here would claim a figure that was never measured.
    """

    kind: Literal["postmortem-written"] = "postmortem-written"
    root_cause: str | None = None
    executive_summary: str | None = None
    customer_loss_estimate: Decimal | None = None
    # What that figure is in, carried rather than looked up, for the reason the
    # document carries it: the reporting currency is configured, and an account
    # that read it back from settings would relabel figures already published
    # the day somebody changed it.
    estimate_currency: str | None = None
    engineer_minutes: int | None = None


class SimilarIncidentsRecalled(_Event):
    """Memory was searched for incidents like this one, and these were found.

    The search rather than what came of it, and the two are different facts. A
    reordering is visible only where a round offered a candidate to move something
    behind, and how many candidates a round offers is the model's to decide - so a
    timeline whose only account of memory is `CandidatesReordered` says nothing at
    all about the walks where memory was read, found something, and had nowhere to
    move it. This is the line that says it was read.

    Nearest first, as the search returned them, because the order is the only
    thing here a reader could act on: the incident at the front is the one whose
    record most resembles this one, and a set would throw that away.

    Every match rather than one, which is the opposite of the choice
    `CandidatesReordered` makes, and for a reason that survives both: that line
    names the record a walk *acted on*, where this one accounts for what was
    available to act on. A reader asking why a candidate was spared wants one
    incident; a reader asking whether memory had anything to say wants all of
    them.

    Silent on an empty search, for the reason a reordering that moved nothing is
    silent: a line on every walk saying memory held nothing is a timeline nobody
    reads.
    """

    kind: Literal["similar-incidents-recalled"] = "similar-incidents-recalled"
    # The ids alone. What each of those incidents tried is in the record this was
    # read from, and a copy of it here would be a second version of the same
    # fact - one that goes stale the moment the record is written to again.
    #
    # At least one, in the type rather than in the caller that publishes this. The
    # silence on an empty search is a decision one publisher makes, and a row is
    # read back by everything that renders a timeline - which reads the nearest
    # incident off the front of this list, and would raise on a page and in a
    # postmortem a long way from whoever wrote the row.
    incident_ids: list[str] = Field(min_length=1)


class CandidatesReordered(_Event):
    """Long-term memory moved this incident's candidates, and what moved them.

    Written only where the order actually changed. A walk that tried its
    second-best candidate first, with nothing saying why, is a walk a human
    reading the incident back cannot account for - and a walk that said so on
    every incident would be a timeline nobody reads.

    One past incident rather than all of them that matched. This line is read
    during an incident, and "because of these four" is a list nobody scanning a
    timeline follows.
    """

    kind: Literal["candidates-reordered"] = "candidates-reordered"
    # The action that was tried before, not the candidate that would take it
    # again. Both halves, because the subject alone does not say what was done
    # to it: "moved checkout down the list" is true of a service somebody
    # restarted and of a flag somebody put back, and a reader cannot tell from
    # the line which experiment this incident is being spared.
    action_type: ActionType
    subject: str
    on_the_strength_of: str


class IncidentRemembered(_Event):
    """What was filed about this incident for the next one to read.

    The actions rather than the record. What a later walk gets from this is
    which things were done and how each turned out, and the description the
    record is found by is a fact about searching rather than about the incident.

    Each as its identity rather than as the subject it acted on, because the
    subject alone is half of what was filed: "filed what was tried: io-shop"
    says nothing about whether io-shop was a service somebody restarted or a
    flag somebody put back, and a reader cannot tell one incident's record
    from the other's. It is the same halving `CandidatesReordered` carries the
    kind to avoid.

    Its own event rather than a clause on the postmortem's, because the two are
    written by different steps for different readers: one is a document a person
    opens, and this is a row nobody reads until an incident like this one
    happens again.
    """

    kind: Literal["incident-remembered"] = "incident-remembered"
    tried: list[ActionIdentity]


class RememberingFailed(_Event):
    """The incident ended and nothing was filed about what was tried.

    Costs this incident nothing - it is over - and costs the next one an
    advantage, which is exactly why it is said out loud. Silence here is
    indistinguishable from an incident that had nothing worth filing, and the
    two call for different things from whoever reads it.
    """

    kind: Literal["remembering-failed"] = "remembering-failed"
    refusal: str


class CommunicationFailed(_Event):
    """A line of the account that a destination would not carry, and why.

    The account's own record of its gaps. Everything else here is something
    Argus did to the incident; this is something that failed to reach a person
    about it - and the timeline is the only place left to say so, the place it
    was going to be said being the one that refused.

    Written only where trying again would meet the same answer. A throttle
    waits and is said a moment later, and an event for every one of those
    would be a timeline about the messaging rather than about the incident.

    `about_kind` is the kind of the line that was lost rather than the line
    itself: the sentence is still on the timeline, a few rows up, and copying
    it here would leave two versions of it to disagree.
    """

    kind: Literal["communication-failed"] = "communication-failed"
    channel: str
    refusal: str
    about_kind: str


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
        | PlacementRecorded
        | OnsetDetected
        | HypothesisFormed
        | CandidateSelected
        | ActionRefused
        | ActionRecommended
        | AlarmDisproven
        | PlatformUnavailable
        | RetrievalUnanswered
        | ActionTaken
        | VerdictReached
        | MitigationResumed
        | ChangeUndone
        | FixAttempted
        | PostmortemWritten
        | SimilarIncidentsRecalled
        | CandidatesReordered
        | IncidentRemembered
        | RememberingFailed
        | CommunicationFailed
    ),
    Field(discriminator="kind")
]

_events = TypeAdapter[IncidentEvent](IncidentEvent)


def parse_event(row: dict[str, Any]) -> IncidentEvent:
    """Reads a stored event back as the type it was published as.

    Discriminated on `kind`, so a reader holds a `LogsRetrieved` rather than a
    dictionary it has to match on strings to interpret.
    """
    return _events.validate_python(row)


class RecordedEvent(BaseModel):
    """One event as the log holds it: what was published, and where it sits.

    The place travels with the event because a reader following the log has to
    keep it. Where `get_by_incident` answers a question about an incident -
    whose answer is complete the moment it is given - a relay's question is
    "what has happened since", and the only thing that can be asked again is
    the place it got to.

    Here rather than with the table it is read from, because the relay that
    follows the log names it as well, and a type kept inside the repository is
    one a reader has to install the repository to name. It sits in `events`
    rather than in `models` for the plainest of reasons: it holds an
    `IncidentEvent`, and `events` already reaches `models` - the other way
    round would be a circle.
    """

    seq: int
    event: IncidentEvent


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
        # The incident named here as well as stamped: a publish before any work
        # on the incident has begun - its alert acknowledged - has no baggage to
        # stamp it from.
        _logger.warning("event could not be published", exc_info=True, extra={
            "event": type(event).__name__, ARGUS_INCIDENT_ID: event.incident_id
        })


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
