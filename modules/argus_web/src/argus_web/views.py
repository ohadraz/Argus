from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from hashlib import sha256
from typing import assert_never

from argus_core.events import (
    ActionTaken,
    AgentInvoked,
    AlertAcknowledged,
    AwaitingRecovery,
    ChangesRetrieved,
    ChannelsUnread,
    FlagChangesRetrieved,
    HypothesisFormed,
    IncidentEvent,
    LogsRetrieved,
    MetricsRetrieved,
    OnsetDetected,
    RecoveryChecked,
    RetrievalChannel,
    RetrievalRequested,
    StatusChanged,
    VerdictReached,
)
from argus_core.ids import UuidStr
from argus_core.models.actor import Actor
from argus_core.models.alert import Alert
from argus_core.models.cause import CauseType
from argus_core.models.change_event import ChangeEvent
from argus_core.models.flag_change import FlagChange
from argus_core.models.hypothesis import Hypothesis
from argus_core.models.incident_status import IncidentStatus
from argus_core.models.metrics import MetricBucket
from argus_core.timestamps import parse_iso
from orchestrator.repository.actions import Action
from orchestrator.repository.incidents import Incident
from orchestrator.repository.postmortems import Postmortem
from orchestrator.repository.timeline import TimelineEvent
from pydantic import BaseModel

# The verdict a reversible action gets when the service did not recover. The
# walk undoes such an action before returning it - see `agent_mitigation` - so
# "refuted" is also the record that the change was put back. Named here because
# that is an inference from the walk's contract rather than something the row
# states, and if the contract ever changes the fix is to record the revert, not
# to re-derive it from a different string.
_REFUTED = "refuted"

# The error rate at which a minute is marked on the page. The same figure the
# Target Service's own console reddens a row at, and copied deliberately rather
# than shared: the two screens sit side by side during a demo, and one that
# marked a different set of minutes than the other would make a reader
# translate between them. Presentation only - nothing decides anything on it,
# and the judgement of which minutes departed from the baseline belongs to
# `argus_core.anomaly`, which made it while the investigation ran.
_ELEVATED_ERROR_RATE = 0.05

# What a log line's level token means, as the Target Service writes them. The
# page distinguishes warnings and errors from the rest; anything it cannot read
# a level from is the rest.
_LEVELS = {"ERROR": "error", "WARN": "warn", "WARNING": "warn", "INFO": "info"}

# How far into a line to look for that token. The service writes the minute
# first and the level second; a level word appearing later is prose - a line
# that mentions an error is not a line at error level.
_LEVEL_IS_WITHIN_THE_FIRST = 2

_PLAIN = "plain"

# Who a reader sees on each line. The orchestrator narrates as Argus itself,
# because from outside "the orchestrator called in the Investigator" is one
# system talking about its own internals - what happened is that Argus did.
_ARGUS = "Argus"
_INVESTIGATOR = "Investigator Agent"
_MITIGATION = "Mitigation Agent"
_CODEFIX = "Code-Fix Agent"
_COMMUNICATOR = "Communicator Agent"
_POSTMORTEM = "Postmortem Agent"

_AGENTS = {
    Actor.ORCHESTRATOR: _ARGUS,
    Actor.INVESTIGATOR: _INVESTIGATOR,
    Actor.MITIGATION: _MITIGATION,
    Actor.CODEFIX: _CODEFIX,
    Actor.COMMUNICATOR: _COMMUNICATOR,
    Actor.POSTMORTEM: _POSTMORTEM,
}

# What each retrieval channel is, said so that somebody who has never read the
# spec knows what was asked for. "changes" in particular: it means deploys and
# releases that landed on the service, not changes Argus made.
_CHANNELS = {
    RetrievalChannel.METRICS: "the service's per-minute metrics",
    RetrievalChannel.LOGS: "the service's log lines",
    RetrievalChannel.CHANGES: "production change events - deploys and releases on the service",
}

# Action types said as a sentence. Falls back to the identifier itself for an
# action nobody has written words for yet, which is wrong in the readable way:
# a reader sees a name they can search the code for rather than nothing.
_ACTIONS = {"revert-feature-flag": "Reverted the feature flag"}


class Attempt(BaseModel):
    """One action the walk took, as a reader sees it."""

    action_type: str | None
    outcome: str | None
    undone: bool
    taken_at: datetime


class Candidate(BaseModel):
    """One explanation the investigation formed, with what became of it.

    The evidence travels on the candidate rather than in a collection beside
    it: a reader who has to match claims to evidence by timestamp is doing the
    investigation over again.
    """

    rank: int
    summary: str
    cause_type: CauseType | None
    confidence: float | None
    subject: str | None
    evidence: list[str]
    tested: bool
    result: str | None
    attempts: list[Attempt]


class TimelineEntry(BaseModel):
    """One status transition, and who made it."""

    at: datetime
    to_status: IncidentStatus
    actor: Actor | None
    action: str | None
    result: str | None
    confidence: float | None


class IncidentSummary(BaseModel):
    """An incident as it appears in a list of them."""

    id: UuidStr
    alert: Alert
    status: IncidentStatus
    created_at: datetime


class IncidentDetail(BaseModel):
    """One incident's whole walk, in one response.

    `unattributed_attempts` exists because `action.hypothesis_id` is nullable:
    an action that names no candidate has nowhere to hang, and dropping it
    would erase a change Argus made to the service from the only account of
    what it did.
    """

    id: UuidStr
    alert: Alert
    status: IncidentStatus
    created_at: datetime
    candidates: list[Candidate]
    unattributed_attempts: list[Attempt]
    timeline: list[TimelineEntry]


class PostmortemView(BaseModel):
    """The postmortem, served on its own because it is the largest body Argus
    writes and the incident detail beside it is polled every two seconds."""

    root_cause: str | None
    customer_loss_estimate: Decimal | None
    estimate_currency: str | None
    engineer_minutes: int | None
    responders: int | None
    responder_titles: list[str] | None
    tokens_spent: int | None
    assumptions: list[str] | None
    executive_summary: str | None
    checklist_complete: bool
    created_at: datetime


class BucketRow(BaseModel):
    """One minute of metrics as the page shows it.

    `elevated` is presentation and nothing else: it is the mark the reader's
    eye lands on, not a judgement about the incident. The judgement was made by
    `argus_core.anomaly` while the investigation ran, and is in the narration
    already as the onset.
    """

    bucket_id: str
    # The same minute a person reads off a clock. `bucket_id` stays as it is
    # because it is the minute's identity - what the row is keyed and linked by
    # - and `when` is that identity said out loud.
    when: str
    error_rate: float
    p50_ms: int
    p95_ms: int
    request_volume: int
    elevated: bool


class LogLine(BaseModel):
    """One log line as it was read, split into the columns a table shows.

    `text` is the line exactly as the service wrote it - stamp and level
    included - because the line is the evidence. `when` and `message` are that
    same line arranged for reading, never a substitute for it: the page shows
    the arrangement and carries the original with it.
    """

    level: str
    text: str
    stamp: str | None
    when: str
    message: str


class FlagToggleRow(BaseModel):
    """One recorded flag change, as the page shows it.

    `moved` is the whole transition where the history contains the flag's
    previous state, and only the new one where it does not - a prior state
    invented to fill the arrow would be a guess about production. No colour on
    it: which direction is the bad one depends entirely on the flag, and a page
    that reddened "on" would be asserting something about `legacy-checkout-
    fallback` that is exactly backwards.
    """

    flag: str
    when: str
    # The state the flag left and the state it arrived in. Two fields rather
    # than one sentence, so the page can strike the state that is no longer
    # true - which is the difference between showing a change and describing
    # one.
    was: str
    now: str
    actor: str | None
    # Whether this is the newest recorded change to this flag. It is the row an
    # action points at: the change Mitigation chose to undo is by definition
    # the latest one, and a link to an older move would show a reader the wrong
    # reason for what Argus did.
    latest_for_flag: bool = False


class Finding(BaseModel):
    """One thing a candidate rests on, as the Investigator cited it.

    `links_to_minute` is set only where the finding quotes a time that can be
    parsed into one of the minutes on the page. Prose is not matched to log
    lines: the model writes about the lines rather than quoting them, and a
    link built by guessing which line it meant would point confidently at the
    wrong evidence - worse than no link, because a reader would believe it.
    """

    text: str
    links_to_minute: str = ""
    # The lines of that same minute. Its own link because the two answer
    # different questions - what the numbers did, and what the service said -
    # and a reader checking a claim usually wants the second.
    links_to_lines: str = ""


class CandidateLine(BaseModel):
    """One explanation, with what it was formed from.

    The findings travel with the claim rather than in a paragraph before it: a
    reader asking "why does it think that" is looking at the claim when they
    ask, and the answer belongs where they are looking.
    """

    rank: int
    summary: str
    subject: str | None
    confidence: str | None
    evidence: list[Finding]


class NarrationLine(BaseModel):
    """One thing that happened, as a reader sees it.

    `who` is on every line because "what did Argus do" is really "which of
    Argus's agents did what": a story where every sentence has the same silent
    subject reads as one program doing everything, which is the opposite of
    what this system is.

    The evidence a line read travels on it - the retrieval knows what came back
    - while the page lays those out in tables of their own. `links_to_minute`
    is how the two are joined: the line naming a minute points at that minute's
    row rather than making a reader find it.

    `kind` is carried through from the event so the page can style a line by
    what it is without matching on its prose.
    """

    at: datetime
    kind: str
    who: str
    text: str
    # One word inside `text` that the page sets apart - the flag a line is
    # about, the status an incident moved to. Split here rather than marked up
    # here: a view that returned HTML would be a view that could inject it, and
    # the template can put a tag around three strings perfectly well.
    before_emphasis: str = ""
    emphasis: str = ""
    after_emphasis: str = ""
    # A state the line's subject left and the state it arrived in, said the way
    # the flag table says them: struck through and picked out, so a change
    # reads as a change wherever it appears on the page.
    moved_from: str = ""
    moved_to: str = ""
    # How the emphasised word is dressed - a status in the colour the header
    # gives it, a verdict in red or green. A class rather than a type, because
    # the page is styling a word rather than holding a domain value.
    emphasis_class: str = ""
    # Where the line points, when what it is about is in one of the tables
    # below it. An account that says "read 40 log lines" and leaves a reader to
    # find them is only half an account.
    link_target: str = ""
    link_label: str = ""
    # How many identical looks this line stands for. The wait polls every few
    # seconds and says the same thing each time; a dozen rows saying it is
    # noise, and none at all is a page that looks stuck.
    repeated: int = 1
    buckets: list[BucketRow] = []
    log_lines: list[LogLine] = []
    changes: list[ChangeEvent] = []
    flag_changes: list[FlagChange] = []
    # The explanations formed in one breath. A list rather than a line each,
    # because an investigation arrives at its candidates together and ranks
    # them against one another - split apart they read as three separate
    # findings, and the ranking loses the comparison it was made in.
    candidates: list[CandidateLine] = []


class Story(BaseModel):
    """One incident's account of itself, arranged for one screen.

    The narration is what happened; the metrics and the logs are what it read,
    gathered into a table each rather than repeated under every retrieval that
    returned them. A widening investigation reads overlapping windows, so the
    same minute comes back several times - and three tables that each say a
    thing once are readable where a dozen inline fragments saying it again are
    not.
    """

    narration: list[NarrationLine]
    metrics: list[BucketRow]
    logs: list[LogLine]
    changes: list[ChangeEvent]
    flag_changes: list[FlagToggleRow]
    # Whether the change channel was read at all. An empty answer from it is a
    # finding - it is what rules a deploy out - and a table that simply did not
    # appear would leave that finding unsaid.
    read_changes: bool


class LiveIncident(BaseModel):
    """The incident somebody watching Argus is looking at.

    Header and story together, because they are one screen and answering "what
    is happening" in two calls invites the two halves to disagree about which
    incident they are describing.
    """

    id: UuidStr
    alert: Alert
    status: IncidentStatus
    created_at: datetime
    # When it stopped, or `None` while it runs. The page counts the elapsed
    # time itself from these two, so that the seconds advance smoothly between
    # polls rather than in the two-second steps the server can supply.
    finished_at: datetime | None
    elapsed_seconds: int
    story: Story
    # What this incident's page currently says, as one value. The page polls
    # every two seconds and almost every poll returns exactly what is already
    # on screen; re-rendering it anyway destroys everything the reader is doing
    # inside it - a scrolled table jumps to its first row, a minute they
    # followed a link to scrolls away, and the status badge's pulse restarts
    # mid-breath. Comparing this says whether there is anything to swap.
    version: str


def build_incident_summary(incident: Incident) -> IncidentSummary:
    """Shapes one incident row for a list of them.

    The alert comes back as an `Alert` rather than as the JSON column it was
    stored in: the payload shape is how the row remembers it, not what a reader
    asked for.
    """
    return IncidentSummary(
        id=incident.id,
        alert=Alert.model_validate(incident.alert_payload),
        status=incident.status,
        created_at=incident.created_at,
    )


def build_incident_detail(
    incident: Incident,
    candidates: list[Hypothesis],
    attempts: list[Action],
    timeline: list[TimelineEvent],
) -> IncidentDetail:
    """Arranges an incident's rows into the walk a reader follows.

    Every argument is already ordered by the repository that returned it, and
    that order is kept rather than re-imposed: ranking candidates and sequencing
    actions are decisions the investigation made, and a view that sorted them
    again would be a second opinion about them.

    Attempts are attached to the candidate they name, because "what did we try
    for this explanation?" is the question a reader has while looking at one.
    """
    attached: dict[str, list[Attempt]] = {}
    unattributed: list[Attempt] = []

    for action in attempts:
        shown = _an_attempt(action)
        if action.hypothesis_id is None:
            unattributed.append(shown)
        else:
            attached.setdefault(action.hypothesis_id, []).append(shown)

    return IncidentDetail(
        id=incident.id,
        alert=Alert.model_validate(incident.alert_payload),
        status=incident.status,
        created_at=incident.created_at,
        candidates=[
            _a_candidate(candidate, attached.get(candidate.id, []))
            for candidate in candidates
        ],
        unattributed_attempts=unattributed,
        timeline=[_a_timeline_entry(event) for event in timeline],
    )


def build_postmortem_view(postmortem: Postmortem) -> PostmortemView:
    """Shapes the postmortem row for transport."""
    return PostmortemView(
        root_cause=postmortem.root_cause,
        customer_loss_estimate=postmortem.customer_loss_estimate,
        estimate_currency=postmortem.estimate_currency,
        engineer_minutes=postmortem.engineer_minutes,
        responders=postmortem.responders,
        responder_titles=postmortem.responder_titles,
        tokens_spent=postmortem.tokens_spent,
        assumptions=postmortem.assumptions,
        executive_summary=postmortem.executive_summary,
        checklist_complete=postmortem.checklist_complete,
        created_at=postmortem.created_at,
    )


def build_narration(events: Sequence[IncidentEvent]) -> list[NarrationLine]:
    """Shapes an incident's recorded account into the lines a reader follows.

    The order is the one the events were published in, kept rather than
    re-imposed: the account is a sequence, and a view that sorted it again
    would be telling a different story from the one that happened.

    Every event becomes exactly one line. Nothing here decides what an event
    meant, groups two of them into a conclusion, or drops one it finds
    uninteresting - the moment this function had an opinion about the
    investigation, the page would be a second investigator.
    """
    narration: list[NarrationLine] = []

    for event in events:
        if isinstance(event, HypothesisFormed) and _still_the_same_finding(narration):
            narration[-1] = _also_carrying(narration[-1], event)
            continue

        line = _a_narration_line(event)

        if _says_the_same_as_the_last_look(line, narration):
            narration[-1] = _looked_again(narration[-1])
            continue

        narration.append(line)

    return narration


def _still_the_same_finding(narration: list[NarrationLine]) -> bool:
    """Whether the line just written is the candidates this one belongs with.

    Consecutive only. Two candidates with something in between were formed in
    two different rounds of the walk - the second after the first was tried and
    refuted - and folding those together would say the investigation had known
    both at once.
    """
    return bool(narration) and narration[-1].kind == "hypothesis-formed"


def _says_the_same_as_the_last_look(line: NarrationLine,
                                    narration: list[NarrationLine]) -> bool:
    """Whether this look at the service found what the one before it found.

    The wait re-reads every few seconds and, until the moment it recovers, has
    the same thing to say each time. A dozen identical rows push everything
    else off the screen to report one unchanged fact.
    """
    return (
        line.kind == "recovery-checked"
        and bool(narration)
        and narration[-1].kind == "recovery-checked"
        and narration[-1].text == line.text
    )


def _looked_again(line: NarrationLine) -> NarrationLine:
    """One more identical look, counted rather than repeated.

    The count is kept because it is the sign of life: "looked six times" says
    Argus is waiting and working, where a single unrepeated line at the bottom
    of a still page reads as one that has stopped.
    """
    return line.model_copy(update={"repeated": line.repeated + 1})


def _also_carrying(line: NarrationLine, event: HypothesisFormed) -> NarrationLine:
    """The candidates line, with one more candidate on it."""
    candidates = [*line.candidates, _a_candidate_line(event)]

    return line.model_copy(update={
        "candidates": candidates,
        "text": _how_many_candidates(len(candidates)),
    })


def _a_candidate_line(event: HypothesisFormed) -> CandidateLine:
    return CandidateLine(
        rank=event.rank,
        summary=_said_plainly(event.summary),
        subject=event.subject,
        confidence=_a_percentage(event.confidence) if event.confidence else None,
        evidence=[_a_finding(cited) for cited in event.evidence],
    )


# A time inside a sentence, in either of the two shapes this system writes:
# the wire format the tools speak to each other, and the clock time the model
# uses when it writes for a person.
_A_TIME_IN_PROSE = re.compile(
    r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?Z?)"
    r"|(?<!\d)(\d{2}:\d{2}(?::\d{2})?Z)"
    r"|(?<!\d)(\d{2}:\d{2})(?!:?\d)"
)


def _a_finding(cited: str,
              minutes: Sequence[str] = (),
              logged: Sequence[str] = ()) -> Finding:
    """One cited fact, pointed at the minute it names where it names one.

    Pointed at rows that exist and nothing else: the minute has to be one the
    metrics window covers, and the lines have to be lines the page holds. A
    finding about a minute nobody retrieved gets no link rather than a link
    into an empty table.
    """
    named = _the_minute_named_in(cited, minutes)

    return Finding(
        text=_said_plainly(cited),
        links_to_minute=named,
        links_to_lines=_the_minute_named_in(cited, logged),
    )


def _the_minute_named_in(cited: str, minutes: Sequence[str]) -> str:
    """The row a finding refers to, or nothing.

    Compared minute against minute, never as text inside text. `21:00` is a
    substring of `2026-08-30T20:21:00Z` - it lands in that minute's *seconds* -
    so a link built by searching for one inside the other points confidently at
    a minute half an hour away from the one the finding named.

    Matched against the minutes actually on the page: a link has to land on a
    row that exists, and a time nothing retrieved names no row here however
    well it parses.
    """
    found = _A_TIME_IN_PROSE.search(cited)

    if found is None:
        return ""

    said = found.group(0)

    for minute in minutes:
        if _the_same_minute(said, minute):
            return minute

    return ""


def _the_same_minute(said: str, minute: str) -> bool:
    """Whether a time quoted in prose is this minute.

    Prose writes a time either as the wire format the tools speak or as the
    clock time a person reads, so both are compared as what they are: an
    instant truncated to its minute, or the minute's own rendering.
    """
    try:
        return parse_iso(said).replace(second=0, microsecond=0) == parse_iso(
            minute
        ).replace(second=0, microsecond=0)
    except ValueError:
        return _a_minute(minute) == said.rstrip("Z")[:5]


def _how_many_candidates(formed: int) -> str:
    return f"Formed {formed} candidate cause{'s' if formed != 1 else ''}, best first:"


def build_story(events: Sequence[IncidentEvent]) -> Story:
    """One incident's whole account: what happened, and what it read.

    The evidence is gathered here rather than left under the retrievals that
    returned it, because an investigation that widens reads the same minutes
    several times - and a reader scanning for the minute the errors started
    should find one table with that minute in it, not the fourth of six
    fragments that each contain a copy.

    Deduplicated by the identity the evidence already has: a bucket is its
    minute and a log line is its text. Where a minute comes back twice the
    later read wins, because it is the later read that Argus acted on.
    """
    narration = build_narration(events)

    minutes: dict[str, BucketRow] = {}
    lines: dict[str, LogLine] = {}
    changed: dict[str, ChangeEvent] = {}
    toggled: dict[tuple[str, str], FlagChange] = {}

    for line in narration:
        minutes.update({bucket.bucket_id: bucket for bucket in line.buckets})
        lines.update({log.text: log for log in line.log_lines})
        changed.update({change.reference: change for change in line.changes})
        # Keyed by flag and moment together: one flag moving twice is two
        # changes, and it is exactly the flag that moved twice - tried, then
        # put back - whose second move a reader must not lose.
        toggled.update({(toggle.flag, toggle.occurred_at): toggle
                        for toggle in line.flag_changes})

    return Story(
        narration=[
            _pointed_at(line, list(minutes), _the_minutes_logged(lines.values()))
            for line in narration
        ],
        metrics=sorted(minutes.values(), key=lambda bucket: bucket.bucket_id),
        logs=sorted(lines.values(), key=lambda log: log.stamp or ""),
        changes=sorted(changed.values(), key=lambda change: change.occurred_at),
        flag_changes=_a_flag_history(
            sorted(toggled.values(), key=lambda toggle: toggle.occurred_at)
        ),
        read_changes=any(isinstance(event, ChangesRetrieved) for event in events),
    )


def _the_minutes_logged(logs: Iterable[LogLine]) -> list[str]:
    """Every minute the page holds log lines for, so a link lands on a row.

    A log line's stamp is to the second; the anchor is the minute, because that
    is the granularity a finding cites and the granularity a reader reads at.
    """
    return sorted({log.stamp[:16] for log in logs if log.stamp})


def _pointed_at(line: NarrationLine,
                minutes: Sequence[str],
                logged: Sequence[str]) -> NarrationLine:
    """One line, with its findings pointed at the minutes the page holds.

    Done here rather than while the line is built, because a finding cited at
    10:14 can only link to 10:14 once it is known that 10:14 is on the page -
    and that is not known until every metrics retrieval has been read.
    """
    if not line.candidates:
        return line

    return line.model_copy(update={"candidates": [
        candidate.model_copy(update={"evidence": [
            _a_finding(cited.text, minutes, logged) for cited in candidate.evidence
        ]})
        for candidate in line.candidates
    ]})


def _a_flag_history(toggles: list[FlagChange]) -> list[FlagToggleRow]:
    """The recorded toggles, each said as the move it was."""
    return _with_the_latest_marked([
        FlagToggleRow(
            flag=toggle.flag,
            when=_a_moment(toggle.occurred_at),
            # The state before a change is the other one. Not an assumption
            # about production but the meaning of the record: the provider
            # writes one of these when a flag's state changes, so a flag that
            # arrived ON is a flag that was OFF.
            was=_on_or_off(not toggle.enabled),
            now=_on_or_off(toggle.enabled),
            actor=toggle.actor,
        )
        for toggle in toggles
    ])


def _with_the_latest_marked(history: list[FlagToggleRow]) -> list[FlagToggleRow]:
    """The same history, with each flag's newest change marked as its own."""
    newest = {row.flag: index for index, row in enumerate(history)}

    return [
        row.model_copy(update={"latest_for_flag": newest[row.flag] == index})
        for index, row in enumerate(history)
    ]


def _on_or_off(enabled: bool | None) -> str:
    return "ON" if enabled else "OFF"


def _utc_now() -> datetime:
    """The clock `build_live_incident` reads when an incident is still running.

    Its own function so that it is an argument with a default rather than a
    call buried in the builder - which is the difference between a test that
    can hold the elapsed time still and one that cannot.
    """
    return datetime.now(UTC)


def build_live_incident(incident: Incident,
                        events: Sequence[IncidentEvent],
                        now: Callable[[], datetime] = _utc_now) -> LiveIncident:
    """Arranges one incident into the screen somebody watches it on.

    `now` is injected because the elapsed time is the one value here that does
    not come out of the rows, and a clock reached for internally is a clock no
    test can hold still.
    """
    finished_at = _when_it_finished(incident, events)
    story = build_story(events)

    return LiveIncident(
        id=incident.id,
        alert=Alert.model_validate(incident.alert_payload),
        status=incident.status,
        created_at=incident.created_at,
        finished_at=finished_at,
        elapsed_seconds=int(((finished_at or now()) - incident.created_at).total_seconds()),
        story=story,
        version=_a_version_of(incident, finished_at, story),
    )


def _a_version_of(incident: Incident,
                  finished_at: datetime | None,
                  story: Story) -> str:
    """A short value that changes exactly when the page's content does.

    Everything the page renders goes in except the elapsed time, which is a
    clock rather than a fact about the incident and is counted by the browser
    for that reason. Including it would make every poll a change, which is the
    same as having no version at all.

    A hash rather than a counter: there is no writer to keep a counter, and the
    question being asked - "is this the same page I am already showing?" - is
    answered by the content itself.
    """
    said = f"{incident.id}|{incident.status}|{finished_at}|{story.model_dump_json()}"

    return sha256(said.encode()).hexdigest()[:16]


def _when_it_finished(incident: Incident,
                      events: Sequence[IncidentEvent]) -> datetime | None:
    """The moment a finished incident stopped, or `None` while it is running.

    An elapsed time that kept climbing after the incident ended would report
    the age of the record rather than the length of the incident.

    Taken from the status change that ended it, falling back to the last thing
    recorded at all: an incident can reach a terminal status without that
    change appearing in its stream - it was resolved before the stream existed,
    or by a path that publishes nothing - and a header that answered "still
    going" for one of those would be wrong in the one way this field exists to
    prevent.
    """
    if not incident.status.is_terminal():
        return None

    ended = [
        event.at
        for event in events
        if isinstance(event, StatusChanged) and event.to_status.is_terminal()
    ]

    if ended:
        return ended[-1]

    return events[-1].at if events else incident.created_at


def _a_narration_line(event: IncidentEvent) -> NarrationLine:
    """One event, said in words, by somebody.

    A `match` over the event types rather than a lookup keyed on `kind`, so a
    new event type that nobody wrote a line for is a type error rather than a
    line that silently reads "unknown".

    Who did it is decided here because it is a fact about which component
    publishes which event, and that is a fact about this system rather than
    about the incident - putting an actor field on the events themselves would
    make every publisher restate its own name on every line it wrote.
    """
    emphasis = ""
    dressed_as = ""
    moved_from = moved_to = ""
    target, label = _where_to_look(event)

    match event:
        case AlertAcknowledged():
            who = _ARGUS
            text = f"Received the alert {event.alert.alert_name} on {event.alert.service}"
        case AgentInvoked():
            who = _ARGUS
            text = f"Called in the {_an_agent(event.agent)}"
        case StatusChanged():
            who = _ARGUS
            emphasis = str(event.to_status).upper()
            dressed_as = f"moved-to {event.to_status}"
            text = f"Moved the incident to {emphasis}{_why_it_moved(event)}"
        case RetrievalRequested():
            who = _INVESTIGATOR
            text = (
                f"Asked for {_CHANNELS[event.channel]}, "
                f"{_a_window(event.window_start, event.window_end)}"
            )
        case MetricsRetrieved():
            who = _INVESTIGATOR
            text = f"Read back {len(event.buckets)} minutes of metrics"
        case LogsRetrieved():
            who = _INVESTIGATOR
            text = f"Read back {len(event.lines)} log lines"
        case ChangesRetrieved():
            who = _INVESTIGATOR
            text = f"Read back {len(event.changes)} production changes"
        case FlagChangesRetrieved():
            who = _MITIGATION
            recent = len(event.changes)
            text = (
                f"Read the flag provider's history - "
                f"{recent} recent flag change{'s' if recent != 1 else ''}"
            )
        case ChannelsUnread():
            who = _INVESTIGATOR
            # Said out loud because the page cannot show it any other way: a
            # channel nobody asked for leaves exactly the same gap as one that
            # was read and had nothing in it, and a reader who cannot tell
            # them apart cannot tell an incomplete investigation from an
            # inconclusive one.
            unread = ", ".join(channel.value for channel in event.channels)
            text = (
                f"Did not read {unread}" if event.channels
                else "Read every channel available"
            )
        case OnsetDetected():
            who = _INVESTIGATOR
            text = f"Placed the start of the incident at {_a_minute(event.onset)}"
        case HypothesisFormed():
            who = _INVESTIGATOR
            text = _how_many_candidates(1)
        case ActionTaken():
            who = _MITIGATION
            emphasis = event.subject or ""
            text = _an_action_taken(event)
            if event.enabled is not None:
                moved_from, moved_to = _on_or_off(not event.enabled), _on_or_off(event.enabled)
        case AwaitingRecovery():
            who = _MITIGATION
            text = (
                f"Waiting for the service to answer, from {_a_minute(event.from_minute)} - "
                f"up to {int(event.seconds_allowed)}s"
            )
        case RecoveryChecked():
            who = _MITIGATION
            # Without the minute it is looking at. That minute is in the
            # future when the look happens - it is the one being waited for -
            # and a line stamped 19:21 that talks about 19:22 reads as a page
            # that cannot tell the time. The line above it already says what
            # is being waited for and for how long.
            settled = "back at its baseline" if event.recovered else "not back at baseline yet"
            text = f"Looked at the service - {settled}"
        case VerdictReached():
            who = _MITIGATION
            # Red or green, and in capitals: this is the sentence the whole
            # mitigation was for, and a reader scanning a screen from across a
            # room should be able to find it without reading the line.
            emphasis = event.outcome.upper()
            dressed_as = f"verdict {event.outcome}"
            text = f"Judged the action {emphasis}"
        case _:
            assert_never(event)

    before, marked, after = _set_apart(text, emphasis)

    return NarrationLine(
        at=event.at,
        kind=event.kind,
        who=who,
        text=text,
        before_emphasis=before,
        emphasis=marked,
        after_emphasis=after,
        moved_from=moved_from,
        moved_to=moved_to,
        emphasis_class=dressed_as if marked else "",
        link_target=target,
        link_label=label,
        buckets=(
            [_a_bucket_row(bucket) for bucket in event.buckets]
            if isinstance(event, MetricsRetrieved)
            else []
        ),
        log_lines=(
            [_a_log_line(line) for line in event.lines]
            if isinstance(event, LogsRetrieved)
            else []
        ),
        changes=event.changes if isinstance(event, ChangesRetrieved) else [],
        flag_changes=event.changes if isinstance(event, FlagChangesRetrieved) else [],
        candidates=(
            [_a_candidate_line(event)] if isinstance(event, HypothesisFormed) else []
        ),
    )


def _a_bucket_row(bucket: MetricBucket) -> BucketRow:
    """One minute of metrics, with the mark the reader's eye lands on."""
    return BucketRow(
        bucket_id=bucket.bucket_id,
        when=_a_minute(bucket.bucket_id),
        error_rate=bucket.error_rate,
        p50_ms=bucket.p50_ms,
        p95_ms=bucket.p95_ms,
        request_volume=bucket.request_volume,
        elevated=bucket.error_rate >= _ELEVATED_ERROR_RATE,
    )


def _where_to_look(event: IncidentEvent) -> tuple[str, str]:
    """The row a line points at, and what the link says.

    A link points at a row or it does not exist. "Show the metrics" beside a
    line that just said it read the metrics takes a reader to a table they were
    going to scroll to anyway - it looks like help and is furniture. The onset
    is different: it names one minute out of ninety, and finding that minute by
    hand is the work the link saves.
    """
    if isinstance(event, OnsetDetected):
        return f"#minute-{event.onset}", "show the minute"

    # The action names one flag, so it can point at that flag's own row. The
    # history line names all of them and points at none: a link that cannot say
    # which of four rows it means is furniture.
    if isinstance(event, ActionTaken) and event.subject:
        return f"#flag-{event.subject}", "the change it reverted"

    return "", ""


def _set_apart(text: str, emphasis: str) -> tuple[str, str, str]:
    """`text` split around the one word the page marks, as three plain strings.

    Three strings rather than a marked-up one, because a view that returned
    HTML would be a view that could inject it - and the template can put a tag
    around the middle of three perfectly well.

    A word that is not in the sentence is not marked: the whole line comes back
    as the first part, which renders exactly as it reads now.
    """
    if not emphasis or emphasis not in text:
        return text, "", ""

    before, _, after = text.partition(emphasis)

    return before, emphasis, after


def _why_it_moved(event: StatusChanged) -> str:
    """The reason a status change carries, said as a clause.

    Mitigation is the one move worth explaining in the view's own words: the
    detail on that transition is the candidate's summary, and "moved to
    mitigating - <a paragraph about a flag>" reads as though the paragraph were
    the reason for moving rather than the thing being acted on.
    """
    if event.to_status is IncidentStatus.MITIGATING:
        return " to act on the leading candidate"

    return f" - {event.detail}" if event.detail else ""


def _said_plainly(prose: str) -> str:
    """A model's sentence, said the way the rest of the page says things.

    Three repairs, all of them presentation, none of them changing what was
    claimed. The escape sequences are a model artefact: it writes `\u2192`
    where it means an arrow, and the text is stored as it arrived because the
    stream records what was said rather than a tidied version of it - so the
    tidying happens here, at the last possible moment.

    Then the flag states, which the model quotes as `'on'` and the rest of the
    page calls `ON`; and then the times, which it writes in the wire format the
    tools speak. Three spellings of one fact on one screen is a reader
    wondering whether they are three facts.

    The states are repaired before the line breaks are, because the arrow the
    model draws between two of them is exactly what it sometimes breaks the
    line around.
    """
    return _with_readable_times(
        _on_one_line(_with_plain_states(_with_escapes_resolved(prose)))
    )


def _with_escapes_resolved(prose: str) -> str:
    r"""`\u2192` and its like, turned back into the characters they name.

    Left as written where the sequence is not one Python can read: the point is
    to show what the model meant, and guessing at a malformed escape would be
    inventing it.
    """
    if "\\u" not in prose:
        return prose

    try:
        return prose.encode("latin-1", "backslashreplace").decode("unicode_escape")
    except (UnicodeDecodeError, UnicodeEncodeError):
        return prose


# A flag's name as this system writes them: lower-case words joined by
# hyphens. Spelled out because it is what tells a state from an English word -
# "off" after a flag's name is a position, and "off" in a sentence is prose.
_A_FLAG_NAME = r"[a-z][a-z0-9]*(?:-[a-z0-9]+)+"

# A flag's state as the model writes it: quoted, bare on either side of the
# arrow it draws between two of them, said as a move in words, or written
# straight after the flag it belongs to.
_A_QUOTED_STATE = re.compile(r"""['"](on|off)['"]""", re.IGNORECASE)
_A_TRANSITION = re.compile(r"\b(on|off)\s*(?:→|->)\s*(on|off)\b", re.IGNORECASE)
_A_MOVE_IN_WORDS = re.compile(r"\bfrom (on|off) to (on|off)\b", re.IGNORECASE)
_A_STATE_OF_A_FLAG = re.compile(
    rf"\b({_A_FLAG_NAME})(\s*=\s*|\s+(?:to\s+)?)(on|off)\b", re.IGNORECASE
)

# The arrow between two states, as it sometimes arrives: the line broken around
# it and a fragment of nothing where the arrow should be. Repaired rather than
# shown, because a sentence broken across three lines around a word that is not
# a word is not what was meant - and matched only in this shape, which prose
# written on one line cannot take.
_A_BROKEN_ARROW = re.compile(r"\b(on|off)\s*\n\s*\S+\s*\n\s*(on|off)\b", re.IGNORECASE)


def _with_plain_states(prose: str) -> str:
    """`ON` and `OFF`, however the model happened to write them.

    Every shape the model actually writes a flag's position in: quoted, either
    side of an arrow, "from off to on", and straight after the flag it belongs
    to. A page that shouted one of them and whispered the rest would look like
    it was describing several different kinds of thing.

    Only these shapes. Uppercasing every "off" in a sentence would shout at
    prose that merely uses the word, which is the mistake in the other
    direction and the more embarrassing one.
    """
    prose = _A_BROKEN_ARROW.sub(
        lambda found: f"{found.group(1)} → {found.group(2)}", prose
    )
    prose = _A_QUOTED_STATE.sub(lambda found: found.group(1).upper(), prose)
    prose = _A_MOVE_IN_WORDS.sub(
        lambda found: f"from {found.group(1).upper()} to {found.group(2).upper()}", prose
    )
    prose = _A_STATE_OF_A_FLAG.sub(
        lambda found: f"{found.group(1)}{found.group(2)}{found.group(3).upper()}", prose
    )

    return _A_TRANSITION.sub(
        lambda found: f"{found.group(1).upper()} → {found.group(2).upper()}", prose
    )


# Any run of whitespace that contains a line break.
_A_LINE_BREAK = re.compile(r"[ \t]*\n\s*")


def _on_one_line(prose: str) -> str:
    """A sentence, said as a sentence.

    The model writes a paragraph and occasionally breaks it mid-clause; the
    page lays its own text out. A line break arriving inside a claim is
    typesetting the model did not mean and the page did not ask for, so it
    becomes the space it stands for.
    """
    return _A_LINE_BREAK.sub(" ", prose).strip()


def _with_readable_times(prose: str) -> str:
    """Wire-format instants inside a sentence, said as a clock says them.

    `21:48Z` is what the tools speak to each other; a person reading a page
    beside a wall clock wants `21:48`. Only the format changes - the moment is
    the one the model named, and every other time on the page is rendered the
    same way.
    """
    return _A_TIME_IN_PROSE.sub(lambda found: _on_the_clock(found.group(0)), prose)


def _on_the_clock(said: str) -> str:
    """One quoted time as a clock reads it, whatever shape it arrived in.

    A bare `21:48Z` is a wire-format time with its date left off, which nothing
    can parse into an instant - so it is trimmed rather than parsed. A full
    timestamp is parsed, because only parsing it can put it in UTC.
    """
    if _A_BARE_CLOCK.fullmatch(said):
        return said[:5]

    return _a_minute(said)


# A clock time on its own, with or without the wire format's seconds and zone.
_A_BARE_CLOCK = re.compile(r"\d{2}:\d{2}(?::\d{2})?Z?")


def _an_agent(agent: Actor) -> str:
    """One of Argus's sub-agents, named as a reader would name it."""
    return _AGENTS[agent]


def _an_action_taken(event: ActionTaken) -> str:
    """What was done to the service.

    The direction is not in the sentence: it is rendered as the same struck-out
    transition the flag table shows, because a change said the same way
    wherever it appears is one fact rather than two descriptions of one.
    """
    said = _ACTIONS.get(event.action_type, event.action_type)
    subject = f" {event.subject}" if event.subject else ""

    return f"{said}{subject}{', moved ' if event.enabled is not None else ''}"


def _a_log_line(text: str) -> LogLine:
    """One log line, read off into the columns a table shows.

    A line announcing no level it recognises is still shown, at no level, and
    with its whole text as the message: the log store belongs to the service
    rather than to Argus, and a line it never labelled is still a line Argus
    read. The original travels alongside whatever is made of it, so what the
    page shows can always be checked against what came back.
    """
    tokens = text.split()
    stamp = tokens[0] if tokens and _is_a_moment(tokens[0]) else None
    level = _PLAIN
    rest = tokens[1:] if stamp else tokens

    for index, token in enumerate(rest[:_LEVEL_IS_WITHIN_THE_FIRST]):
        found = _LEVELS.get(token.strip(":").upper())

        if found is not None:
            level = found
            rest = rest[:index] + rest[index + 1:]
            break

    return LogLine(
        level=level,
        text=text,
        stamp=stamp,
        when=_a_moment(stamp) if stamp else "",
        message=" ".join(rest),
    )


def _is_a_moment(value: str) -> bool:
    """Whether a token is a timestamp rather than the start of the message."""
    try:
        parse_iso(value)
    except ValueError:
        return False

    return True


def _a_minute(value: str, beside: str | None = None) -> str:
    """A wire-format minute, said the way a clock says it.

    `2026-08-30T10:14:00Z` is what the tools speak to each other; a person
    reading a page next to a wall clock wants `10:14`. The raw value stays
    reachable in the markup that carries it - it is what the metrics table's
    rows are keyed by - so nothing is lost by not printing it.

    `beside` is the other end of the same window, and the date comes back the
    moment the two fall on different days. The change channel is asked about
    the twenty-four hours before the onset, and a clock time alone renders that
    as "18:13 to 18:13" - a window a reader can only read as a bug.
    """
    if beside is not None and not _the_same_day(value, beside):
        return _reformatted(value, "%d %b %H:%M")

    return _reformatted(value, "%H:%M")


def _the_same_day(value: str, other: str) -> bool:
    """Whether two wire-format moments fall on the same date.

    Unparseable counts as the same day: the fallback prints the string as it
    arrived, and a date bolted onto something that is not a time would be a
    guess dressed up as precision.
    """
    try:
        return parse_iso(value).astimezone(UTC).date() == parse_iso(other).astimezone(UTC).date()
    except ValueError:
        return True


def _a_moment(value: str) -> str:
    """A wire-format instant to the second, for a log line's own stamp."""
    return _reformatted(value, "%H:%M:%S")


def _reformatted(value: str, pattern: str) -> str:
    """`value` in UTC under `pattern`, or `value` itself where it is not a time.

    Unparseable is shown as it arrived rather than dropped or guessed at: the
    string came out of a recorded event, and a page that silently blanked it
    would be hiding the one clue to why it looks wrong.
    """
    try:
        return parse_iso(value).astimezone(UTC).strftime(pattern)
    except ValueError:
        return value


def _a_window(start: str | None, end: str | None) -> str:
    """A retrieval's window, said the way the request actually made it.

    A metrics read is anchored rather than bounded (spec §16), so it has one
    end, and saying "to now" for the other would put a bound in the account
    that the call never had.
    """
    if start and end:
        return f"the {_how_long(start, end)} before {_a_minute(end, beside=start)}"

    if start:
        return f"anchored on {_a_minute(start)}"

    return f"up to {_a_minute(end)}" if end else "over no particular window"


def _how_long(start: str, end: str) -> str:
    """How much time a window covers, in the largest unit that says it whole.

    A span read as "29 Aug 19:16 to 30 Aug 19:16" is arithmetic the reader has
    to do to find out it is a day; "the 24 hours before 30 Aug 19:16" is the
    same window already understood. The end is kept and the start is not,
    because the end is what the window is anchored on.
    """
    try:
        minutes = round((parse_iso(end) - parse_iso(start)).total_seconds() / 60)
    except ValueError:
        return f"window {start} to {end}"

    if minutes >= 60 and minutes % 60 == 0:
        hours = minutes // 60

        return f"{hours} hour{'s' if hours != 1 else ''}"

    return f"{minutes} minute{'s' if minutes != 1 else ''}"


def _a_percentage(confidence: float) -> str:
    return f"{confidence * 100:.0f}%"


def _an_attempt(action: Action) -> Attempt:
    """One action row, as a reader sees it.

    An action with no outcome yet is undecided rather than undone: it was taken
    a moment ago and the service has not answered. That is a state to show, not
    an absence to hide - the same way the shop's console shows a minute still
    in progress.
    """
    return Attempt(
        action_type=action.type,
        outcome=action.outcome,
        undone=action.outcome == _REFUTED,
        taken_at=action.taken_at,
    )


def _a_candidate(hypothesis: Hypothesis, attempts: list[Attempt]) -> Candidate:
    """One hypothesis row, with the attempts made for it.

    A candidate the walk never reached comes back with no attempts and
    `tested` false, which is the difference between an investigation that ran
    out of options and one that stopped because it was right.
    """
    return Candidate(
        rank=hypothesis.rank,
        summary=hypothesis.summary,
        cause_type=hypothesis.cause_type,
        confidence=hypothesis.confidence,
        subject=hypothesis.subject,
        evidence=hypothesis.supporting_evidence,
        tested=hypothesis.tested,
        result=hypothesis.result,
        attempts=attempts,
    )


def _a_timeline_entry(event: TimelineEvent) -> TimelineEntry:
    """One transition row. `created_at` is when it happened, and is named `at`
    here because a reader is looking at an event, not at a record of one."""
    return TimelineEntry(
        at=event.created_at,
        to_status=event.to_status,
        actor=event.actor,
        action=event.action,
        result=event.result,
        confidence=event.confidence,
    )
