"""Turning an incident's rows back into one incident (spec §7.6).

The Postmortem agent holds no connection and reads no rows; what it needs is
scattered across the tables `argus_incidents` owns, and assembling it is the
Orchestrator's work. Keeping the gathering here is also what stops two readers
of the same incident disagreeing: the page and the postmortem read the same
account, through the same repositories.

Nothing here decides anything. Every line comes from something recorded while
it was happening, rendered for a reader - which is the point, because what
happened was settled then, and a postmortem re-deriving it from conclusions
would be describing a different incident.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from datetime import datetime
from typing import get_args

import psycopg
from agent_postmortem import (
    ActionRecord,
    CandidateRecord,
    DeploymentChangesRecord,
    IncidentEvidence,
    Sources,
    write_postmortem,
)
from argus_core import Connections, parse_iso
from argus_core.events import (
    ActionRecommended,
    ActionTaken,
    ChangesRetrieved,
    DeploymentChangesRead,
    FixAttempted,
    FlagChangesRetrieved,
    IncidentRemembered,
    LogsRetrieved,
    OnsetDetected,
    RecoveryChecked,
    RememberingFailed,
    StatusChanged,
)
from argus_core.llm import ClientFor
from argus_core.models import (
    AcceleratorPinUndo,
    ActionType,
    Alert,
    AutoscalerUndo,
    ChangeEvent,
    DeploymentRollbackUndo,
    Hypothesis,
    IncidentStatus,
    OpenedPullRequest,
    PostmortemDocument,
    ReplicaUndo,
    TakenAction,
    TimelineEntry,
    Verdict,
    as_a_change,
)
from argus_core.replay import Recorder, Replay
from argus_core.replay import nobody as records_nothing
from argus_incidents.repository import (
    conversation,
    events,
    hypotheses,
    incidents,
    replay,
    taken_actions,
)
from argus_narration import (
    build_narration,
    each_wait_told_once,
    said_in_full,
    what_the_action_does,
    what_was_done,
)


def write_postmortem_for(incident_id: str,
                         connections: Connections,
                         sources: Sources,
                         client_for: ClientFor,
                         recorder: Recorder = records_nothing) -> PostmortemDocument:
    """The real postmortem for one incident: gather, then write.

    `sources` and `client_for` arrive as arguments rather than being built
    here. What this function does is read an incident's rows and hand them to
    the agent; which payment provider answers the revenue question, and which
    model writes the prose, are decisions belonging to whoever started the
    process - and building them here is what made this the one production path
    in the repo that could not be tested without a vendor SDK installed.

    Every port is answered by a source that says so when it cannot answer,
    rather than reporting a zero: "this incident cost nothing" in front of a
    reader looks measured, and the document is built to tell the two apart.

    `client_for` is a factory rather than a client, because the receipt is per
    incident: the wrapper holds the incident it records for, and one client
    shared across a process would file every incident's calls under whichever
    was written up first.
    """
    with connections() as conn:
        evidence = gather_evidence(conn, incident_id)

    return write_postmortem(
        evidence, sources, client_for(Replay(incident_id, recorder))
    )


def gather_evidence(conn: psycopg.Connection, incident_id: str) -> IncidentEvidence:
    """Everything one incident left behind, in the order it left it.

    Refuses an incident that has not ended. A postmortem is written once, when
    the incident is over, and a duration measured to "now" instead would be a
    different number every time anyone asked for one.
    """
    incident = incidents.get(conn, incident_id)
    if incident is None:
        raise ValueError(f"no incident [{incident_id}] to write a postmortem for")

    if incident.ended_at is None:
        raise ValueError(
            f"incident [{incident_id}] has not ended, and an incident still being "
            f"worked has no duration to report"
        )

    # Read once, because two things are made of it - the candidates, and the
    # lines saying which of them each formed - and two reads could disagree.
    considered = hypotheses.get_all_by_incident(conn, incident_id)

    return IncidentEvidence(
        incident_id=incident_id,
        started_at=incident.created_at,
        ended_at=incident.ended_at,
        alerted_at=_when_it_was_alerted(incident.alert_payload) or incident.created_at,
        onset_at=_when_it_actually_began(conn, incident_id),
        recorded_recovery_at=_when_it_came_back(conn, incident_id),
        watched_and_never_recovered=_it_was_watched_and_never_came_back(conn, incident_id),
        rule=_the_rule_that_paged(incident.alert_payload),
        alert_title=_what_was_alerted(incident.alert_payload),
        alert_finding=_what_the_alert_found(incident.alert_payload),
        timeline=_what_happened(conn, incident_id, [hypothesis.id for hypothesis in considered]),
        candidates=_what_was_considered(considered),
        actions=_what_was_done(conn, incident_id),
        log_lines=_what_was_read(conn, incident_id),
        changes=_what_changed(conn, incident_id),
        deployment_changes=_what_each_deployment_changed(conn, incident_id),
        tokens_spent=replay.get_tokens_spent(conn, incident_id),
        pull_request=_what_was_proposed(conn, incident_id),
        fix_explanation=_what_code_fix_said(conn, incident_id),
        recommended_action=_what_is_still_owed(conn, incident_id),
        # Off the record rather than the account: the account says a lead was
        # weighed, and the record is where its words and standing are kept
        # together - the latest standing, which is the one the walk acted on.
        leads=conversation.get_leads_by_incident(conn, incident_id)
    )


def _what_is_still_owed(conn: psycopg.Connection, incident_id: str) -> str | None:
    """The action Argus named and declined to take, said as an instruction.

    Off the account rather than off the walk's state, as everything else here
    is: what the document describes is what was recorded, and a postmortem that
    read anything from somewhere the timeline cannot show would describe an
    incident nobody can check it against.

    Said through the narration's own renderer rather than assembled here. The
    dashboard, the Slack message and this document all say what Argus would
    have done, and three spellings of one action is three things a reader has
    to recognise as the same.

    The last one, for the reason the proposal above takes the last: the walk can
    reach the gate more than once, and what is owed is whatever stands at the
    end rather than whatever was refused first.
    """
    recommended = [
        what_the_action_does(event.action_type, event.subject or "")
        for event in events.get_by_incident(conn, incident_id)
        if isinstance(event, ActionRecommended)
    ]

    return recommended[-1] if recommended else None


def _what_was_proposed(conn: psycopg.Connection,
                       incident_id: str) -> OpenedPullRequest | None:
    """The fix Code-Fix opened, as it published it.

    Off the event's own field rather than off the event's presence: the step
    publishes whether or not it proposed anything, and "Argus read the code and
    found nothing to change" is a finding rather than a missing proposal (§10).
    An incident with a `FixAttempted` and no pull request has to come back with
    none, or the document offers a reader a link to nowhere.

    The last one, for the same reason the walk loops at all: an incident that
    went back to investigate can reach the code twice, and what a reader wants
    is the proposal that stands rather than the one that was superseded.
    """
    proposed = [event.pull_request
                for event in events.get_by_incident(conn, incident_id)
                if isinstance(event, FixAttempted) and event.pull_request]

    return proposed[-1] if proposed else None


def _what_code_fix_said(conn: psycopg.Connection, incident_id: str) -> str | None:
    """What Code-Fix last said of the code, as it published it - `None` where
    it said nothing.

    The last, for the reason the proposal is: an incident that went back to
    investigate can reach the code twice, and what stands is what was said of
    it last.
    """
    said = [event.explanation
            for event in events.get_by_incident(conn, incident_id)
            if isinstance(event, FixAttempted) and event.explanation]

    return said[-1] if said else None


def _when_it_actually_began(conn: psycopg.Connection,
                            incident_id: str) -> datetime | None:
    """The onset the Investigator measured, as it published it.

    Read from the account rather than re-derived: the onset was found by
    walking the metrics for a departure from baseline while the incident was
    live, and a postmortem measuring it again from a wider window would date
    the same incident differently from the page that showed it.

    `None` where no onset was ever published - an incident that never reached
    an investigation, or one whose metrics could not be read. The document
    then falls back to the alert's own time, which is late but real.
    """
    onsets = [event.onset
              for event in events.get_by_incident(conn, incident_id)
              if isinstance(event, OnsetDetected)]

    return parse_iso(onsets[0]) if onsets else None


def _when_it_came_back(conn: psycopg.Connection,
                       incident_id: str) -> datetime | None:
    """The minute Mitigation recorded the recovery at, as it published it.

    The onset's counterpart, and read the same way for the same reason: the
    minute was measured while the incident was live, on the window the
    verification wait was polling, and the document reads a window bounded by
    the incident's close. One rule evaluated over two different spans of minutes
    can disagree about which minute a service came back at, and then the page and
    the write-up date the same incident differently - which is the whole of why
    neither end of an incident is re-derived here.

    The **last** one, where the onset above takes the first, and the two are not
    inconsistent. An incident has one beginning: a second `OnsetDetected` is a
    re-read of it, and the first is the measurement. An incident can have more
    than one ending offered to it, because a walk that was refuted goes back and
    mitigates again - so what stands is the confirmation the incident actually
    ended on, which is the last.

    Where no look carried one, a person reporting the incident resolved dates
    it: their report is the fact (spec §16), and searching the series for a
    level falling would be Argus corroborating a claim it does not test. Second
    to a minute Argus measured, not over it - a recovery confirmed before the
    report is an earlier answer to when the service came back, not a
    contradiction of it.

    `None` where neither exists, which is three ordinary cases rather than a
    failure: an incident that escalated, one nobody mitigated, and a
    confirmation reached on a window with nothing in it to date. The document
    measures its own answer from the series there.
    """
    recorded = events.get_by_incident(conn, incident_id)
    recoveries = [event.recovered_minute
                  for event in recorded
                  if isinstance(event, RecoveryChecked)
                  and event.recovered_minute is not None]

    if recoveries:
        return parse_iso(recoveries[-1])

    resolved_by_a_person = [event.at
                            for event in recorded
                            if isinstance(event, StatusChanged)
                            and event.to_status is IncidentStatus.RESOLVED
                            and event.reported is not None]

    return resolved_by_a_person[-1] if resolved_by_a_person else None


def _it_was_watched_and_never_came_back(conn: psycopg.Connection,
                                        incident_id: str) -> bool:
    """Whether Mitigation looked for the recovery and never once saw it.

    The negative of the minute above, and read off the account for the same
    reason: the party that was watching at the time answered, and the document
    asking again of its own window would be one rule over different minutes. On
    a service that flaps, that is a lull read as a recovery in one run and not
    in the next.

    Any look that saw the service back makes this false, dated or not - a
    confirmation with nothing to date it by is a recovery the document dates
    from the series. So does no look at all: an incident that escalated before
    it acted, or one nobody mitigated, was never watched, and the series is the
    only answer there is.
    """
    looks = [event.recovered
             for event in events.get_by_incident(conn, incident_id)
             if isinstance(event, RecoveryChecked)]

    return bool(looks) and not any(looks)


def _the_rule_that_paged(alert_payload: dict[str, object]) -> str | None:
    """The rule the alert named, read back through the alert's own model.

    Through `Alert` rather than by key, so that what is read is the field the
    alert declares and not a string that happens to sit under its name.
    """
    return Alert.model_validate(alert_payload).rule


def _when_it_was_alerted(alert_payload: dict[str, object]) -> datetime | None:
    """When the alert fired, as its sender dated it, read back through the
    alert's own model as the rule is - `None` where the sender dated nothing."""
    return Alert.model_validate(alert_payload).started_at


def _what_was_alerted(alert_payload: dict[str, object]) -> str:
    """The alert in a line, for the postmortem's prompt.

    Two fields by name, and the naming is the safeguard rather than the
    brevity. `alert_payload` is a whole serialised `Alert`, so it holds
    `stale_entry_keys` as well - the addresses of the cache entries a
    reconciliation found stale. Those are an address rather than a
    description: the model is told how many entries disagree and by how much,
    which is what it reasons about, and never where they live. A line here
    that rendered more of this dict would put hundreds of keys into a prompt
    without anything complaining, which is why the two are picked out by hand
    and not the ones left over from a loop.
    """
    return f"{alert_payload.get('alert_name')} on {alert_payload.get('service')}"


def _what_the_alert_found(alert_payload: dict[str, object]) -> str | None:
    """The alert's own summary, as its sender wrote it - one field by name, for
    `_what_was_alerted`'s reason: the payload also holds `stale_entry_keys`,
    which no prompt should carry."""
    summary = alert_payload.get("summary")

    return summary if isinstance(summary, str) else None


def _what_happened(conn: psycopg.Connection,
                   incident_id: str,
                   considered: list[str]) -> list[TimelineEntry]:
    """The narration, as the page shows it: who did what, in order.

    The page's own renderer rather than a second one written here. The
    postmortem and the dashboard tell the same story, and two builders of it
    are two stories - the one a reader was shown while the incident ran, and a
    different one in the document written about it afterwards.

    Each line's moment, speaker and sentence, and nothing of how the page sets
    a word apart: that structure belongs to a page, and the sentence is the
    part that carries the account. Said in full, so what the page shows beside
    a sentence - the move, the candidates - is in the sentence here.

    A line that formed candidates also says where they sit in `considered`,
    the hypotheses in the order the document lists them. By id rather than by
    counting: that list is best first across every round, so a second round's
    best sits between the first round's own.

    Two things the page does not need and a document citing lines by number
    does: each wait told once, by the look that settled it, and every line
    saying whether it is the walk's own. Both are timing - how many looks a
    wait took, and where a person's message fell - and a document numbering
    by either would number one walk differently on every telling.

    And two lines the page shows and the document leaves out. What was filed
    for the next incident, or that nothing could be: that is Argus keeping its
    books for an incident that has not happened yet, and says nothing about
    this one. And a read of what a deployment changed, which the document
    gives a row of its own (`_what_each_deployment_changed`), so a line for it
    too would tell it twice.
    """
    about_this_incident = [
        event for event in events.get_by_incident(conn, incident_id)
        if not isinstance(event, IncidentRemembered | RememberingFailed | DeploymentChangesRead)
    ]

    return [
        TimelineEntry(at=line.at,
                      who=line.who,
                      text=said_in_full(line),
                      candidates=[considered.index(candidate.hypothesis_id)
                                  for candidate in line.candidates
                                  if candidate.hypothesis_id in considered],
                      outside_the_walk=line.outside_the_walk)
        for line in each_wait_told_once(build_narration(about_this_incident))
    ]


def _what_was_considered(considered: list[Hypothesis]) -> list[CandidateRecord]:
    """Every candidate ranked, tried or not.

    The untried ones are half of what a walk has to say: an investigation that
    was confident and right and one that ran out of options are told apart by
    what was left on the list.
    """
    return [
        CandidateRecord(summary=hypothesis.summary,
                        failure_mode=hypothesis.failure_mode,
                        confidence=hypothesis.confidence,
                        subject=hypothesis.subject,
                        from_state=hypothesis.from_state,
                        to_state=hypothesis.to_state,
                        tested=hypothesis.tested,
                        result=hypothesis.result)
        for hypothesis in considered
    ]


def _what_was_done(conn: psycopg.Connection, incident_id: str) -> list[ActionRecord]:
    """Every action, with what it came to and whether it still stands.

    Whether it still stands because a person who resolved the incident left
    every change in place, so a flag Argus turned off is off when this is
    written - and a responder reading the document has to know there is a
    change of Argus's standing in production.

    Dated by the account's line saying the change was made, not by the row:
    the row is a claim written before anything happens, and dated by it the
    action comes before the agent was even called in to take it. Said in the
    account's words for the same reason: the line is the action as a reader
    met it, where the row holds only its tag. The row stands only where the
    account holds no such line.
    """
    said = {event.hypothesis_id: event
            for event in events.get_by_incident(conn, incident_id)
            if isinstance(event, ActionTaken) and event.hypothesis_id is not None}

    return [
        ActionRecord(taken_at=_when_it_was_taken(taken_action, said),
                     action=_what_it_did(taken_action, said),
                     reversible=taken_action.has_a_way_back,
                     verdict=taken_action.outcome,
                     standing=_what_became_of(taken_action),
                     paused_sync_of=_whose_sync_it_left_stopped(taken_action))
        for taken_action in taken_actions.get_by_incident(conn, incident_id)
    ]


def _whose_sync_it_left_stopped(taken_action: TakenAction) -> str | None:
    """The application whose automatic sync the action stopped, where it is
    still stopped: the change stands, and sync was on when Argus found it.

    A change put back puts sync back with it, and an application nobody had
    syncing was not stopped by Argus - so neither owes anybody anything.
    """
    if not taken_action.has_a_way_back or taken_action.outcome is Verdict.REFUTED:
        return None

    match taken_action.undo_descriptor:
        case (DeploymentRollbackUndo() | ReplicaUndo() | AutoscalerUndo()
              | AcceleratorPinUndo()) as undo if undo.was_syncing_itself:
            return undo.application
        case _:
            return None


def _when_it_was_taken(taken_action: TakenAction, said: Mapping[str, ActionTaken]) -> datetime:
    line = said.get(taken_action.hypothesis_id or "")

    return line.at if line is not None else taken_action.taken_at


def _what_it_did(taken_action: TakenAction, said: Mapping[str, ActionTaken]) -> str:
    """The action in the account's words, read off its line where there is one
    and off the row's tag where the tag is one Argus still knows. A row written
    under a tag since renamed keeps its tag: history is not rewritten."""
    line = said.get(taken_action.hypothesis_id or "")
    if line is not None:
        return what_was_done(line.action_type, line.subject or "")

    known = next((tag for tag in get_args(ActionType.__value__) if tag == taken_action.type), None)
    if known is not None:
        return what_was_done(known, taken_action.subject or "")

    return f"{taken_action.type} on {taken_action.subject}"


def _what_changed(conn: psycopg.Connection, incident_id: str) -> list[ChangeEvent]:
    """Every change the walk read, in the order they were made: the
    investigation's, and each flag change the walk read for itself that the
    investigation did not.

    The flags too, because the walk acts on what it read of them, and a
    write-up has to be able to cite the change Argus acted on. The model's own
    reading of the changes is over a window it chose, and a flag switched a
    moment past that window's end is one it never saw - while the walk, reading
    over a window of its own, did, and turned it back.

    In time rather than in the order they were read, because a change is
    labelled by its place among the rest. A later round re-reads a window that
    can reach further back than the first, and a change carried where it was
    read would move down a place for everything earlier that turned up - so one
    run's write-up would name another run's changes. Changes made at the same
    instant keep the order they were read in.

    Each change once. A change carried once per read takes a label per read, so
    the numbering would turn on whether the first read happened to reach it.

    Only toggles from before the walk first acted. A later round re-reads the
    flag history with its far end open, and from the first action on, what it
    finds is the walk's own doing - already told as an action, and no cause of
    the incident it was acting on.
    """
    recorded = events.get_by_incident(conn, incident_id)
    read: list[ChangeEvent] = []
    for event in recorded:
        if isinstance(event, ChangesRetrieved):
            for change in event.changes:
                if not any(_the_same_change(change, seen) for seen in read):
                    read.append(change)
    first_acted = next(
        (event.at for event in recorded if isinstance(event, ActionTaken)), None
    )

    for event in recorded:
        if isinstance(event, FlagChangesRetrieved):
            for toggle in event.changes:
                if first_acted is not None and parse_iso(toggle.occurred_at) >= first_acted:
                    continue

                change = as_a_change(toggle)
                if not any(_the_same_change(change, seen) for seen in read):
                    read.append(change)

    return sorted(read, key=lambda change: parse_iso(change.occurred_at))


def _what_each_deployment_changed(conn: psycopg.Connection,
                                  incident_id: str) -> list[DeploymentChangesRecord]:
    """What each deployment the investigation looked into changed, in the order
    it first asked.

    Each deployment once. The model may ask after one deployment twice, and a
    row per read would number the deployments by how often it happened to.
    """
    read: dict[str, DeploymentChangesRecord] = {}
    for event in events.get_by_incident(conn, incident_id):
        if isinstance(event, DeploymentChangesRead) and event.revision not in read:
            read[event.revision] = DeploymentChangesRecord(revision=event.revision,
                                                           said=event.said)

    return list(read.values())


def _the_same_change(one: ChangeEvent, other: ChangeEvent) -> bool:
    """Whether two readings are of one change: the same thing, moved the same
    way, at the same instant - compared as instants, since two channels may
    spell one differently."""
    return (one.kind == other.kind
            and one.reference == other.reference
            and one.summary == other.summary
            and parse_iso(one.occurred_at) == parse_iso(other.occurred_at))


def _what_became_of(taken_action: TakenAction) -> str:
    """Whether an action's change still stands as the document is written.

    Nothing that ends in a postmortem is unwound, so the only change put back is
    one Mitigation undid itself, having found it did not help. A change with no
    way back - a discard of cached figures - owes nothing, and calling it still
    in place would send somebody looking for something to undo.
    """
    if not taken_action.has_a_way_back:
        return "nothing to put back"

    if taken_action.outcome is Verdict.REFUTED:
        return "put back when it did not help"

    return "still in place"


def _what_was_read(conn: psycopg.Connection, incident_id: str) -> list[str]:
    """The log lines the incident actually saw.

    From the published account rather than from the log store, which has moved
    on since. A postmortem explaining lines Argus never read would be
    explaining a different incident, fluently.

    Each line as often as one read returned it, and no more. An investigation
    that widens its window reads again the minutes it has read, and a line
    kept once per read is a failure counted twice - while two replicas logging
    the same line in one minute are two failures, and one read returns both.
    """
    kept: dict[str, int] = {}
    for event in events.get_by_incident(conn, incident_id):
        if isinstance(event, LogsRetrieved):
            for line, copies in Counter(event.lines).items():
                kept[line] = max(kept.get(line, 0), copies)

    return [line for line, copies in kept.items() for _ in range(copies)]
