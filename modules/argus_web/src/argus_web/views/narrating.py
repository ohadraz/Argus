"""An incident's recorded account, shaped into the lines a reader follows.

Every event becomes exactly one line. Nothing here decides what an event meant,
groups two of them into a conclusion, or drops one it finds uninteresting - the
moment this module had an opinion about the investigation, the page would be a
second investigator.

Two exceptions, and both are counting rather than judging: candidates formed in
one breath are gathered onto one line, because an investigation ranks them
against one another and split apart they read as separate findings; and
identical looks at a service that has not recovered are counted rather than
repeated, because a dozen rows saying one unchanged thing push everything else
off the screen.

Who did it is decided here because it is a fact about which component publishes
which event - a fact about this system rather than about the incident. Putting
an actor field on the events themselves would make every publisher restate its
own name on every line it wrote.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
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
from argus_core.models.actor import Actor
from argus_core.models.change_event import ChangeEvent
from argus_core.models.flag_change import FlagChange
from argus_core.models.incident_status import IncidentStatus
from pydantic import BaseModel

from argus_web.views.clock import a_minute, a_window
from argus_web.views.findings import Finding, a_finding
from argus_web.views.flags import on_or_off
from argus_web.views.logs import LogLine, a_log_line
from argus_web.views.metrics import BucketRow, a_bucket_row
from argus_web.views.prose import said_plainly

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

_HYPOTHESIS_FORMED = "hypothesis-formed"
_RECOVERY_CHECKED = "recovery-checked"


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

        line = a_narration_line(event)

        if _says_the_same_as_the_last_look(line, narration):
            narration[-1] = _looked_again(narration[-1])
            continue

        narration.append(line)

    return narration


def a_narration_line(event: IncidentEvent) -> NarrationLine:
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
                f"{a_window(event.window_start, event.window_end)}"
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
            text = f"Placed the start of the incident at {a_minute(event.onset)}"
        case HypothesisFormed():
            who = _INVESTIGATOR
            text = _how_many_candidates(1)
        case ActionTaken():
            who = _MITIGATION
            emphasis = event.subject or ""
            text = _an_action_taken(event)
            if event.enabled is not None:
                moved_from, moved_to = on_or_off(not event.enabled), on_or_off(event.enabled)
        case AwaitingRecovery():
            who = _MITIGATION
            text = (
                f"Waiting for the service to answer, from {a_minute(event.from_minute)} - "
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
            [a_bucket_row(bucket) for bucket in event.buckets]
            if isinstance(event, MetricsRetrieved)
            else []
        ),
        log_lines=(
            [a_log_line(line) for line in event.lines]
            if isinstance(event, LogsRetrieved)
            else []
        ),
        changes=event.changes if isinstance(event, ChangesRetrieved) else [],
        flag_changes=event.changes if isinstance(event, FlagChangesRetrieved) else [],
        candidates=(
            [a_candidate_line(event)] if isinstance(event, HypothesisFormed) else []
        ),
    )


def a_candidate_line(event: HypothesisFormed) -> CandidateLine:
    """One explanation the investigation formed, with what it cited for it."""
    return CandidateLine(
        rank=event.rank,
        summary=said_plainly(event.summary),
        subject=event.subject,
        confidence=_a_percentage(event.confidence) if event.confidence else None,
        evidence=[a_finding(cited) for cited in event.evidence],
    )


def _still_the_same_finding(narration: list[NarrationLine]) -> bool:
    """Whether the line just written is the candidates this one belongs with.

    Consecutive only. Two candidates with something in between were formed in
    two different rounds of the walk - the second after the first was tried and
    refuted - and folding those together would say the investigation had known
    both at once.
    """
    return bool(narration) and narration[-1].kind == _HYPOTHESIS_FORMED


def _says_the_same_as_the_last_look(line: NarrationLine,
                                    narration: list[NarrationLine]) -> bool:
    """Whether this look at the service found what the one before it found.

    The wait re-reads every few seconds and, until the moment it recovers, has
    the same thing to say each time. A dozen identical rows push everything
    else off the screen to report one unchanged fact.
    """
    return (
        line.kind == _RECOVERY_CHECKED
        and bool(narration)
        and narration[-1].kind == _RECOVERY_CHECKED
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
    candidates = [*line.candidates, a_candidate_line(event)]

    return line.model_copy(update={
        "candidates": candidates,
        "text": _how_many_candidates(len(candidates)),
    })


def _how_many_candidates(formed: int) -> str:
    return f"Formed {formed} candidate cause{'s' if formed != 1 else ''}, best first:"


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


def _a_percentage(confidence: float) -> str:
    return f"{confidence * 100:.0f}%"
