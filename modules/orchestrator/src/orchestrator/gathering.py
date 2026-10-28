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
from typing import Final, get_args

import psycopg
from agent_postmortem import (
    ActionRecord,
    CandidateRecord,
    DeploymentChangesRecord,
    IncidentEvidence,
    RefusalRecord,
    ResolutionRecord,
    Sources,
    write_postmortem,
)
from argus_core import Connections, parse_iso
from argus_core.events import (
    ActionRecommended,
    ActionRefused,
    ActionTaken,
    ChangesRetrieved,
    DeploymentChangesRead,
    FixAttempted,
    FlagChangesRetrieved,
    IncidentEvent,
    IncidentRemembered,
    LeadWeighed,
    LogsRetrieved,
    MessageUnderstood,
    OnsetDetected,
    PersonWrote,
    QuestionAnswered,
    RecoveryChecked,
    RememberingFailed,
    ResolutionOffered,
    RetrievalRequested,
    RetrievalUnanswered,
    StatusChanged,
    WithdrawalOffered,
    the_escalations,
)
from argus_core.llm import ClientFor
from argus_core.models import (
    CHAT_THREAD,
    AcceleratorPinUndo,
    ActionProgress,
    ActionType,
    Alert,
    AutoscalerUndo,
    ChangeEvent,
    ChannelReading,
    DeploymentRollbackUndo,
    FirstTold,
    FlagUndo,
    ForCandidate,
    Hypothesis,
    IncidentStatus,
    Meaning,
    OpenedPullRequest,
    PostmortemDocument,
    Reference,
    ReplicaUndo,
    ReportChannel,
    RetrievalChannel,
    TakenAction,
    TimelineEntry,
    Undone,
    Verdict,
    as_a_change,
)
from argus_core.replay import Recorder, Replay
from argus_core.replay import nobody as records_nothing
from argus_incidents import when_it_was_taken
from argus_incidents.repository import (
    conversation,
    events,
    hypotheses,
    incidents,
    references,
    replay,
    taken_actions,
)
from argus_narration import (
    NarrationLine,
    build_narration,
    each_wait_told_once,
    said_as_meant,
    said_in_full,
    what_the_action_does,
    what_to_do,
    what_was_done,
    what_was_not_done,
)

from orchestrator.walk.investigating import ASKING_THE_FLAG_PROVIDER

# The kind a line telling an announcement carries: the event's own, read off
# its type rather than spelled a second time.
_ACTION_TAKEN: Final[str] = ActionTaken.model_fields["kind"].default
# And the kind a line telling the gate refusing to act carries.
_ACTION_REFUSED: Final[str] = ActionRefused.model_fields["kind"].default
# The kinds of a line telling a person's message and an incident's move.
_PERSON_WROTE: Final[str] = PersonWrote.model_fields["kind"].default
_STATUS_CHANGED: Final[str] = StatusChanged.model_fields["kind"].default
# The moves as the narration sets them apart: a move to act, and a person's
# report that the incident is over.
_TO_ACT: Final = str(IncidentStatus.MITIGATING).upper()
_RESOLVED: Final = str(IncidentStatus.RESOLVED).upper()
# What a person can mean that bears on the incident whatever else came of it:
# it ends, or they take it over.
_AN_ENDING: Final = (Meaning.RESOLVE, Meaning.WITHDRAW)


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

    The tokens spent are read off the replay log once the document is written,
    not before: the log is the one count of every call the incident made, the
    write-up's own among them, and a total read before the writer ran left its
    calls out of a figure that claims to be all of them. Recording is done
    before a client returns, so every call the writer made is there to count.
    """
    with connections() as conn:
        evidence = gather_evidence(conn, incident_id)

    document = write_postmortem(
        evidence, sources, client_for(Replay(incident_id, recorder))
    )

    with connections() as conn:
        return document.model_copy(
            update={"tokens_spent": replay.get_tokens_spent(conn, incident_id)}
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
    # The account read once and told once, for the same reason: the timeline,
    # and where in it each action's line sits.
    account = events.get_by_incident(conn, incident_id)
    told = _the_account_told(account)
    reading = _the_reading_that_stands(account)

    return IncidentEvidence(
        incident_id=incident_id,
        started_at=incident.created_at,
        ended_at=incident.ended_at,
        alerted_at=_when_it_was_alerted(incident.alert_payload) or incident.created_at,
        onset_at=_when_it_actually_began(conn, incident_id),
        onset_stated_by_the_alert=_when_the_alert_said_it_began(incident.alert_payload),
        recorded_recovery_at=_when_it_came_back(conn, incident_id),
        resolution=_the_resolution(account, told),
        people_wrote=any(line.kind == _PERSON_WROTE for line in told),
        first_told=_when_people_were_first_told(conn, incident_id),
        watched_and_never_recovered=_it_was_watched_and_never_came_back(conn, incident_id),
        escalated=_it_was_handed_to_a_person(account),
        rule=_the_rule_that_paged(incident.alert_payload),
        alert_title=_what_was_alerted(incident.alert_payload),
        alert_finding=_what_the_alert_found(incident.alert_payload),
        timeline=_what_happened(told, [hypothesis.id for hypothesis in considered]),
        candidates=_what_was_considered(
            considered,
            {taken.hypothesis_id: taken
             for taken in taken_actions.get_by_incident(conn, incident_id)
             if taken.hypothesis_id is not None}),
        actions=_what_was_done(conn, incident_id, account, told,
                               [hypothesis.id for hypothesis in considered]),
        log_lines=_what_was_read(conn, incident_id),
        logs_read_until=_how_far_the_logs_were_read(account),
        changes=_what_changed(conn, incident_id),
        deployment_changes=_what_each_deployment_changed(conn, incident_id),
        pull_request=_what_was_proposed(conn, incident_id),
        fix_explanation=reading.explanation if reading is not None else None,
        fix_branch_read=reading.branch_read if reading is not None else None,
        fix_holds_what_ran=reading.holds_what_ran if reading is not None else None,
        files_as_they_ran=reading.as_it_ran if reading is not None else [],
        uses_outside=reading.uses_outside if reading is not None else [],
        recommended_action=_what_is_still_owed(conn, incident_id),
        refusals=_what_was_refused(account, told),
        # Off the record rather than the account: the account says a lead was
        # weighed, and the record is where its words and standing are kept
        # together - the latest standing, which is the one the walk acted on.
        leads=conversation.get_leads_by_incident(conn, incident_id),
        deploys_reading=_how_the_investigation_read(account, RetrievalChannel.CHANGES,
                                                    ChangesRetrieved),
        flags_reading=_how_the_flags_were_read(account),
        logs_reading=_how_the_investigation_read(account, RetrievalChannel.LOGS,
                                                 LogsRetrieved)
    )


def _when_people_were_first_told(conn: psycopg.Connection,
                                 incident_id: str) -> FirstTold | None:
    """When the chat platform accepted Argus's first post about the incident,
    and which platform it was - `None` where none was accepted.

    Off the incident's thread rather than the account: the thread is written
    down once the platform accepted the line that opened it, and is the only
    record a line was said - the account records only a line that never will
    be (`CommunicationFailed`).
    """
    thread = references.get_first_by_kind(conn, incident_id, CHAT_THREAD)
    if thread is None:
        return None

    return FirstTold(channel=ReportChannel(thread.reference.source), at=thread.recorded_at)


def _what_was_refused(account: list[IncidentEvent],
                      told: list[NarrationLine]) -> list[RefusalRecord]:
    """Each refusal to act, by its line and with which refusal it was.

    By the line, as an action is found: the document says a refusal as the
    timeline does, and `told` is that timeline. By order, as a placement is
    found (`_what_happened`): each refusal published is told as a line of its
    own, in the order published.
    """
    refused = [event.refusal for event in account if isinstance(event, ActionRefused)]
    lines = [position for position, line in enumerate(told) if line.kind == _ACTION_REFUSED]

    return [RefusalRecord(line=line, refusal=refusal)
            for line, refusal in zip(lines, refused, strict=True)]


def _what_is_still_owed(conn: psycopg.Connection, incident_id: str) -> str | None:
    """The action Argus named and declined to take, said as an instruction.

    Off the account rather than off the walk's state, as everything else here
    is: what the document describes is what was recorded, and a postmortem that
    read anything from somewhere the timeline cannot show would describe an
    incident nobody can check it against.

    Said through the narration's own renderer rather than assembled here. The
    dashboard, the Slack message and this document all say what Argus would
    have done, and three verbs for one action is three things a reader has to
    recognise as the same. Told rather than named, because here it becomes an
    action item.

    The last one, for the reason the proposal above takes the last: the walk can
    reach the gate more than once, and what is owed is whatever stands at the
    end rather than whatever was refused first.
    """
    recommended = [
        what_to_do(event.action_type, event.subject or "")
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


def _the_reading_that_stands(account: list[IncidentEvent]) -> FixAttempted | None:
    """The attempt whose account of the code stands - the last that said
    anything of it - or `None` where none did.

    The last, for the reason the proposal is: an incident that went back to
    investigate can reach the code twice, and what stands is what was said of
    it last. One attempt for what was said and for the branch it was said of,
    because the branch is a fact about that reading and an earlier attempt's
    would describe a reading the document no longer shows.
    """
    said = [event for event in account
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

    Never a person's report, which is carried apart
    (`_when_a_person_said_it_was_over`): the document searches the series from
    this minute for where the service was back to normal, and a report is not
    a minute to search from.

    `None` where no look carried one, which is three ordinary cases rather than
    a failure: an incident that escalated, one nobody mitigated, and a
    confirmation reached on a window with nothing in it to date.
    """
    recoveries = [event.recovered_minute
                  for event in events.get_by_incident(conn, incident_id)
                  if isinstance(event, RecoveryChecked)
                  and event.recovered_minute is not None]

    return parse_iso(recoveries[-1]) if recoveries else None


def _the_resolution(account: list[IncidentEvent],
                    told: list[NarrationLine]) -> ResolutionRecord | None:
    """A person reporting the incident resolved - when, who, and where in
    `told` the line saying so sits - or `None` where nobody did.

    Their report is the fact (spec §16), and the document ends the incident at
    it as said - searching the series for a level falling would be Argus
    corroborating a claim it does not test. Which of this and a recovery Argus
    recorded ends the incident is the document's to say, so both are carried.

    The last, as the line is: an incident resolved is over, and a report before
    it was undone by whatever reopened it.
    """
    reports = [event for event in account
               if isinstance(event, StatusChanged)
               and event.to_status is IncidentStatus.RESOLVED
               and event.reported is not None]
    if not reports:
        return None

    lines = [position for position, line in enumerate(told)
             if line.kind == _STATUS_CHANGED and line.outside_the_walk
             and line.emphasis == _RESOLVED]
    report = reports[-1]
    assert report.reported is not None

    return ResolutionRecord(at=report.at, by=report.reported.by,
                            line=lines[-1] if lines else None)


def _it_was_handed_to_a_person(account: list[IncidentEvent]) -> bool:
    """Whether Argus ran out of moves and handed the incident over - its own
    move to escalated, off the account like every other ending here. A
    person's report never escalates; it withdraws or resolves."""
    return bool(the_escalations(account))


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


def _when_the_alert_said_it_began(alert_payload: dict[str, object]) -> datetime | None:
    """When the alert said the incident began, read back through the alert's
    own model as the rule is - `None` where it said nothing, as almost every
    alert does."""
    return Alert.model_validate(alert_payload).stated_onset


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


def _what_happened(told: list[NarrationLine], considered: list[str]) -> list[TimelineEntry]:
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
    counting: that list holds every round's candidates, and a line forms only
    its own round's. And a line acting for a candidate says where that one sits,
    and in what words the line names it, so the document can say it by its
    label.
    """
    return [
        TimelineEntry(at=line.at,
                      who=line.who,
                      text=said_in_full(line),
                      candidates=[considered.index(candidate.hypothesis_id)
                                  for candidate in line.candidates
                                  if candidate.hypothesis_id in considered],
                      for_candidate=_the_candidate_it_acted_for(line, considered),
                      outside_the_walk=line.outside_the_walk)
        for line in told
    ]


def _the_candidate_it_acted_for(line: NarrationLine,
                                considered: list[str]) -> ForCandidate | None:
    """Where the candidate a line acted for sits in `considered`, and the
    words the line names it in - `None` where it names none the record holds."""
    named = line.names_candidate
    if named is None or named.hypothesis_id not in considered:
        return None

    return ForCandidate(place=considered.index(named.hypothesis_id), said_as=named.said_as)


def _the_account_told(account: list[IncidentEvent]) -> list[NarrationLine]:
    """The incident's account in lines, as the document numbers them.

    Two things the page does not need and a document citing lines by number
    does: each wait told once, by the look that settled it, and every line
    saying whether it is the walk's own. Both are timing - how many looks a
    wait took, and where a person's message fell - and a document numbering
    by either would number one walk differently on every telling.

    And one line the page shows and the document leaves out: what was filed
    for the next incident, or that nothing could be. That is Argus keeping its
    books for an incident that has not happened yet, and says nothing about
    this one.

    A read of what a deployment changed stays a line, though the document gives
    what was read a row of its own (`_what_each_deployment_changed`). The row
    says what changed; only the line says when it was read, among the steps the
    investigation took - and left out, the timeline skipped the one it turned on.

    What people wrote is kept only where it bore on the incident
    (`_what_bore_on_it`), and said as what it meant (`said_as_meant`). And a
    move to act that no act followed is left out: a person ended the incident
    first, and a timeline holding the move after their report reads as Argus
    pressing on regardless of it - where the walk held off from the moment the
    move was written.
    """
    about_this_incident: list[IncidentEvent] = [
        event for event in account
        if not isinstance(event, IncidentRemembered | RememberingFailed)
    ]
    kept = _what_bore_on_it(about_this_incident)
    told = _without_a_move_nothing_came_of(each_wait_told_once(build_narration(kept)))

    return _each_message_as_meant(told, kept, about_this_incident)


def _what_bore_on_it(account: list[IncidentEvent]) -> list[IncidentEvent]:
    """The account less what people wrote that bore on nothing, and less the
    offers back to them.

    A message bore on the incident where it ended it or handed it over - a
    resolution or a withdrawal - or where the investigation weighed it as a
    lead, whatever it found: a lead ruled out is as much of the story as one
    that turned it. A question, a thank-you or anything never weighed did not,
    and goes with what was made of it and any answer to it.

    The offer is how a report is confirmed, and says nothing the report and the
    move it made do not.
    """
    understood = [event for event in account if isinstance(event, MessageUnderstood)]
    weighed = [event.message for event in account if isinstance(event, LeadWeighed)]
    bore = [*(event.message for event in understood if event.meaning in _AN_ENDING), *weighed]

    return [event for event in account
            if not isinstance(event, ResolutionOffered | WithdrawalOffered)
            and not (isinstance(event, PersonWrote | MessageUnderstood | QuestionAnswered)
                     and event.message not in bore)]


def _without_a_move_nothing_came_of(told: list[NarrationLine]) -> list[NarrationLine]:
    """`told` less a move to act after which the walk did nothing."""
    return [line for position, line in enumerate(told)
            if not (line.kind == _STATUS_CHANGED and not line.outside_the_walk
                    and line.emphasis == _TO_ACT
                    and all(later.outside_the_walk for later in told[position + 1:]))]


def _each_message_as_meant(told: list[NarrationLine],
                           kept: list[IncidentEvent],
                           account: list[IncidentEvent]) -> list[NarrationLine]:
    """`told` with each person's message said as what it was understood to
    mean, by the name it was offered back to them under - read off `account`,
    since the offer itself is not among what was `kept`.

    By order, as an action's line is found: each message kept is told as a line
    of its own, in the order published.
    """
    written = iter([event.message for event in kept if isinstance(event, PersonWrote)])

    return [_a_message_as_meant(line, next(written), account)
            if line.kind == _PERSON_WROTE else line
            for line in told]


def _a_message_as_meant(line: NarrationLine,
                        message: Reference,
                        account: list[IncidentEvent]) -> NarrationLine:
    """One message's line said as what it was understood to mean, or as it was
    written where nothing understood it."""
    meaning = next((event.meaning for event in account
                    if isinstance(event, MessageUnderstood) and event.message == message), None)
    name = next((event.person_name for event in account
                 if isinstance(event, ResolutionOffered | WithdrawalOffered)
                 and event.message == message), None)

    return line if meaning is None else said_as_meant(line, meaning, name)


def _what_was_considered(considered: list[Hypothesis],
                         actions: Mapping[str, TakenAction]) -> list[CandidateRecord]:
    """Every candidate formed, tried or not - and how far Argus's action on
    each got, `actions` being the action rows by the candidate they name: a row
    is also written for an attempt that ended before the action itself was
    done, and for one nobody can say the end of.

    The untried ones are half of what a walk has to say: an investigation that
    was confident and right and one that ran out of options are told apart by
    what was left on the list. An action is what tells a test a person's ending
    stopped from one never started: neither measured anything.
    """
    return [_a_candidate(hypothesis, actions.get(hypothesis.id)) for hypothesis in considered]


def _a_candidate(hypothesis: Hypothesis, action: TakenAction | None) -> CandidateRecord:
    """One candidate as recorded, with how far its action got - where it had one."""
    return CandidateRecord(summary=hypothesis.summary,
                           failure_mode=hypothesis.failure_mode,
                           confidence=hypothesis.confidence,
                           subject=hypothesis.subject,
                           from_state=hypothesis.from_state,
                           to_state=hypothesis.to_state,
                           tested=hypothesis.tested,
                           result=hypothesis.result,
                           progress=action.progress if action is not None else None,
                           verdict_recorded=action is not None and action.outcome is not None)


def _what_was_done(conn: psycopg.Connection,
                   incident_id: str,
                   account: list[IncidentEvent],
                   told: list[NarrationLine],
                   considered: list[str]) -> list[ActionRecord]:
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

    And where that line sits in `told`, the timeline the document numbers, so
    the document can mark the line rather than say the action again beside it.
    `told` is `account` told, so the two cannot disagree about how many
    announcements there were. A walk resumed after announcing an action and
    before taking it announces it again; the last announcement is the one it
    was taken by, and the one all three are read off.

    And which candidate it was for, by its place in `considered`, the
    candidates' ids in the order the document lists them - the place their
    labels count.
    """
    announced = [event for event in account if isinstance(event, ActionTaken)]
    said = {event.hypothesis_id: event for event in announced if event.hypothesis_id is not None}
    where = _where_each_is_said(announced, told)

    return [
        ActionRecord(taken_at=when_it_was_taken(taken_action, announced),
                     action=_what_it_did(taken_action, said),
                     has_a_way_back=_whether_it_left_a_way_back(taken_action),
                     verdict=taken_action.outcome,
                     standing=_what_became_of(taken_action),
                     paused_sync_of=_whose_sync_it_left_stopped(taken_action),
                     line=where.get(taken_action.hypothesis_id or ""),
                     progress=taken_action.progress,
                     left_behind_known=_whether_what_it_left_is_known(taken_action),
                     candidate=(considered.index(taken_action.hypothesis_id) + 1
                                if taken_action.hypothesis_id in considered else None))
        for taken_action in taken_actions.get_by_incident(conn, incident_id)
    ]


def _where_each_is_said(announced: list[ActionTaken],
                        told: list[NarrationLine]) -> dict[str, int]:
    """Where in `told` each candidate's action is said, by its last
    announcement.

    By order rather than by moment. Every announcement is told as a line of its
    own, in the order it was published, so the k-th line about an action taken
    is the k-th announcement - where two announcements can share a moment under
    a frozen clock, and a resumed walk's two of one action share a candidate.
    """
    lines = [position for position, line in enumerate(told) if line.kind == _ACTION_TAKEN]

    return {event.hypothesis_id: position
            for event, position in zip(announced, lines, strict=True)
            if event.hypothesis_id is not None}


def _whether_it_left_a_way_back(taken_action: TakenAction) -> bool:
    """Whether there is anything of the action's to put back - what its kind
    leaves, for an action performed, and what it left on the way, for one that
    never was: a rollback the platform refused has nothing to put back, unless
    it suspended the sync first."""
    if taken_action.progress is ActionProgress.NOT_PERFORMED:
        return taken_action.undo_descriptor is not None

    return taken_action.has_a_way_back


def _whether_what_it_left_is_known(taken_action: TakenAction) -> bool:
    """Whether what an action left is known, where its row can be in doubt.

    Only for an action never performed, whose way back is what it left on the
    way: one performed has its kind's way back, and how far it got already
    says what is in doubt about it."""
    if taken_action.progress is ActionProgress.NOT_PERFORMED:
        return taken_action.left_behind_known

    return True


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


def _what_it_did(taken_action: TakenAction, said: Mapping[str, ActionTaken]) -> str:
    """The action in the account's words, read off its line where there is one
    and off the row's tag where the tag is one Argus still knows. A row written
    under a tag since renamed keeps its tag: history is not rewritten.

    An action never performed is said as not done. It has no line - nothing is
    announced until a change is made - and said off its tag in the past tense,
    it would tell a reader the service was changed when nothing was."""
    line = said.get(taken_action.hypothesis_id or "")
    if line is not None:
        return what_was_done(line.action_type, line.subject or "")

    known = next((tag for tag in get_args(ActionType.__value__) if tag == taken_action.type), None)
    if known is not None and taken_action.progress is ActionProgress.NOT_PERFORMED:
        return what_was_not_done(known, taken_action.subject or "")

    # A claim that never said more: nobody knows whether it was done, so it is
    # named as the thing it does rather than said in either tense.
    if known is not None and taken_action.progress in (ActionProgress.CLAIMED,
                                                       ActionProgress.UNKNOWN):
        named = what_the_action_does(known, taken_action.subject or "")
        return named[:1].upper() + named[1:]

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
    first_acted = _when_it_first_acted(recorded)

    for event in recorded:
        if isinstance(event, FlagChangesRetrieved):
            for toggle in event.changes:
                if first_acted is not None and parse_iso(toggle.occurred_at) >= first_acted:
                    continue

                change = as_a_change(toggle)
                if not any(_the_same_change(change, seen) for seen in read):
                    read.append(change)

    return sorted(read, key=lambda change: parse_iso(change.occurred_at))


def _when_it_first_acted(account: list[IncidentEvent]) -> datetime | None:
    """When the walk first acted - after which a flag history read back holds
    the walk's own doing rather than a cause - or `None` where it never did."""
    return next((event.at for event in account if isinstance(event, ActionTaken)), None)


def _how_the_investigation_read(account: list[IncidentEvent],
                                channel: RetrievalChannel,
                                answered: type[ChangesRetrieved] | type[LogsRetrieved]
                                ) -> ChannelReading:
    """What came of the investigation's reads of `channel`, whose answers are
    `answered`.

    Read where any one was answered, however often it was asked. Asked with no
    answer where it published a request and no reading followed - a source that
    failed and a walk stopped mid-read leave the same account, so neither is
    said. Otherwise never asked.
    """
    if any(isinstance(event, answered) for event in account):
        return ChannelReading.READ

    if any(isinstance(event, RetrievalRequested) and event.channel is channel
           for event in account):
        return ChannelReading.UNANSWERED

    return ChannelReading.NOT_ASKED


def _how_the_flags_were_read(account: list[IncidentEvent]) -> ChannelReading:
    """What came of the walk's reads of the flag history.

    Only changes made since Argus first acted where every toggle any read
    returned is from once the walk had acted: a later round reads the history
    again and finds what the walk did, which is not carried - so the read shows
    no rows, though it was not empty. Said by when rather than by whom, as the
    cut it explains is made. The walk publishes no request before it reads, so a read with
    no answer is the one it says went unanswered.
    """
    reads = [event for event in account if isinstance(event, FlagChangesRetrieved)]
    if not reads:
        unanswered = any(isinstance(event, RetrievalUnanswered)
                         and event.what_was_asked == ASKING_THE_FLAG_PROVIDER
                         for event in account)

        return ChannelReading.UNANSWERED if unanswered else ChannelReading.NOT_ASKED

    came_back = [toggle for read in reads for toggle in read.changes]
    first_acted = _when_it_first_acted(account)
    if (came_back and first_acted is not None
            and all(parse_iso(toggle.occurred_at) >= first_acted for toggle in came_back)):
        return ChannelReading.ONLY_SINCE_ARGUS_ACTED

    return ChannelReading.READ


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
            read[event.revision] = DeploymentChangesRecord(
                revision=event.revision,
                said=event.said,
                lists_every_file=event.lists_every_file,
                comparison=event.comparison,
                service=event.service
            )

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

    A change made with no verdict on file may already be back: a refuted change
    is put back before its verdict is written, so a worker that died in between
    left it put back and recorded nothing. And a claim that never said more may
    never have been made at all.

    An action never performed changed nothing where its row knows so - a tier
    that refused before asking for any change, a platform that said it did not
    handle one, an action with nowhere left to go, a person's ending before the
    write - unless it left something on the way, which its undo says: a
    suspension before a rollback that was refused. Where a change request's
    answer was lost, or what failed said nothing about the estate, nobody can
    say what was changed beyond what the undo carries.

    A flag revert is the one whose undo is its own write: nothing changes
    before it, so a flag revert carrying one was taken by the provider and
    never seen evaluating - made, not "not made".
    """
    if taken_action.progress is ActionProgress.NOT_PERFORMED:
        if isinstance(taken_action.undo_descriptor, FlagUndo):
            return "made at the provider but never seen in effect; still in place"

        if taken_action.undo_descriptor is not None:
            if taken_action.left_behind_known:
                return "not made; what it changed on the way is still in place"

            return "not known whether it was made; what it changed on the way is still in place"

        if taken_action.left_behind_known:
            return "nothing was changed"

        return "not known whether anything was changed"

    if not taken_action.has_a_way_back:
        return "nothing to put back"

    # Refuted, and left as somebody else had since set it: not put back, and a
    # reader told it was would take the subject for Argus's again.
    if taken_action.outcome is Verdict.REFUTED and taken_action.undone is Undone.LEFT_AS_FOUND:
        return ("left as found when it did not help: it had been changed from "
                "outside since Argus set it")

    if taken_action.outcome is Verdict.REFUTED:
        return "put back when it did not help"

    if taken_action.outcome is None:
        if taken_action.progress is ActionProgress.PERFORMED:
            return "may still be in place"

        if taken_action.progress in (ActionProgress.CLAIMED, ActionProgress.UNKNOWN):
            return "not known whether it was made"

    return "still in place"


def _how_far_the_logs_were_read(account: list[IncidentEvent]) -> datetime | None:
    """Where the furthest read of the logs ended - nothing after it was read -
    or `None` where none was.

    What the lines cannot say of themselves: where they stop is as often where
    the reading stopped as where the service did.
    """
    ends = [parse_iso(event.window_end) for event in account if isinstance(event, LogsRetrieved)]

    return max(ends, default=None)


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
