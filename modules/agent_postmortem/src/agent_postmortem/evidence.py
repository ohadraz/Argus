"""Everything an incident left behind, handed over in one piece.

The agent holds no database connection. What it needs is scattered across four
tables the Orchestrator already owns - the incident's own row, its published
events, the candidates it ranked, the actions it took - and gathering them is
that module's business, not this one's. What arrives here is the result of
that gathering, in Argus's terms rather than in rows.

What the incident spent in tokens is not here: the count is of every call the
incident made, the write-up's own among them, so it can only be read once the
document is written - by whoever holds the replay log.
"""

from __future__ import annotations

from datetime import datetime

from argus_core.models import (
    ActionProgress,
    ChangeEvent,
    ChannelReading,
    CodeUse,
    DeploymentComparison,
    FileAsItRan,
    FirstTold,
    OpenedPullRequest,
    Refusal,
    ThreadMessage,
    TimelineEntry,
    Verdict,
)
from pydantic import BaseModel


class CandidateRecord(BaseModel):
    """One candidate the Investigator ranked, as it was recorded.

    Values rather than a rendered line, because the document reads them as
    values: the trigger is the subject and transition of the confirmed one, and
    the hypotheses section shows each result. Nothing here is a conclusion the
    postmortem reaches - every field was written while the incident ran.
    """

    summary: str
    failure_mode: str | None
    confidence: float | None
    subject: str | None
    from_state: str | None
    to_state: str | None
    tested: bool
    result: str | None
    # How far Argus's action to test it got - `None` where none was claimed. A
    # test a person's ending stopped leaves `tested` false, since nothing was
    # measured, and without this the candidate reads as never tried.
    progress: ActionProgress | None = None
    # Whether that action's row recorded a verdict. A change made with no
    # verdict on file was never judged, or was judged by a worker that died
    # before writing it down, and the row cannot tell which.
    verdict_recorded: bool = False
    # The service the fault is in, where it is not the one that alerted - a
    # dependency. Only the alerting service's deploys are read, so a cause in
    # another is one whose changes nobody looked at. `None` everywhere else.
    faulting_service: str | None = None


class ActionRecord(BaseModel):
    """One action Argus took, what it came to, and whether it still stands.

    `verdict` is the verdict as recorded, `None` where none was reached;
    `standing` is the sentence a responder needs about it now - still in place,
    put back, or nothing to put back.

    `paused_sync_of` is the application whose automatic sync from its
    repository the action stopped and left stopped, the change still standing:
    a platform refuses to have a live application changed under it otherwise,
    and would put the repository's version back at its next pass. `None`
    wherever sync is as Argus found it.

    `line` is where, in the incident's timeline, the line saying the action
    was taken sits - the line `taken_at` and `action` are read off - so the
    document can mark that line rather than say the action again beside it.
    `None` where the account holds no such line.

    `progress` is how far the action got, as its row knows it - not performed
    for an attempt that ended before its write, which `action` already says as
    not done and whose stop, where a person ended it first, was no test to
    judge; claimed or unknown for one nobody can say was done.
    """

    taken_at: datetime
    action: str
    has_a_way_back: bool
    verdict: str | None
    standing: str
    paused_sync_of: str | None = None
    line: int | None = None
    progress: ActionProgress = ActionProgress.PERFORMED
    # Whether what the action left behind is known, as its row records it: an
    # action nobody can account for is not one with nothing to put back.
    # Required, so a reader building one says which it is.
    left_behind_known: bool
    # The candidate it was for, by its place among the candidates (from 1) -
    # the place its label counts - and `None` where it was for none the
    # record holds.
    candidate: int | None = None
    # What this same action - its kind and the thing it was done to - came to
    # on each earlier incident this one recalled, one verdict per incident, in
    # the order they were recalled. A reader told only that the incident ran a
    # revert reads it as a fresh experiment where it was a repeat of one that
    # had already failed.
    tried_before: list[Verdict] = []
    # Whether the walk put the change back itself, having found it did not
    # help - the fact `standing` says in words. Not one left as found, which
    # somebody had changed since, nor one with nothing to put back.
    put_back: bool = False


class DeploymentChangesRecord(BaseModel):
    """What one deployment changed, as the Investigator read it: every line the
    read tier said, under the revision it was read for.

    Lines rather than files and hunks, because the lines are what the model was
    shown and what the write-up is shown again - and what names the deploy
    that carried a change is what its own diff shows.

    `lists_every_file` is whether they name every file the deploy changed -
    where they do, a file they leave out is as it was before it.

    `comparison` is whether they are a diff at all: where nothing was
    compared, the write-up says what the history held in its own words, of
    `service`, the one whose history was read.
    """

    revision: str
    said: list[str]
    lists_every_file: bool = False
    comparison: DeploymentComparison = DeploymentComparison.COMPARED
    service: str | None = None


class RefusalRecord(BaseModel):
    """One refusal to act at the gate: where in the timeline its line sits, and
    which refusal it was - the line says it in words, and the review reads the
    kind to say whether the next step is a person's."""

    line: int
    refusal: Refusal


class ResolutionRecord(BaseModel):
    """A person reporting the incident resolved: when, who, and where in the
    incident's timeline the line saying so sits - so the document can mark
    that line as the end rather than say the end again beside it. `line` is
    `None` where the account holds no such line."""

    at: datetime
    by: str
    line: int | None = None


class IncidentEvidence(BaseModel):
    """One incident, as the postmortem reads it.

    Recorded values rather than conclusions: the narration's lines, the
    candidates and actions as their rows hold them, the changes the
    investigation read. A postmortem that re-derived the story from them would
    be re-deciding what happened, and what happened was decided while it was
    happening - so what the agent does with these is arrange and label them,
    never judge them again.
    """

    incident_id: str
    # The service the alert named - the one whose deploys the investigation
    # reads, and no other's.
    service: str
    started_at: datetime
    ended_at: datetime
    # When the alert fired, as its sender dated it - not when the incident
    # opened. A sender holds an alert back before delivering it, grouping and
    # waiting, and detection measured to the opening would count the delivery
    # as the alert's own delay. The opening where the sender dated nothing.
    alerted_at: datetime
    # When the service actually began to fail, as the Investigator measured it
    # from the metrics - not when Argus was told. The two differ by however
    # long the alert took to fire, and those minutes are the worst ones to get
    # wrong: counted as calm, they inflate the baseline the loss is measured
    # against; left out of the incident, the damage they did is invisible.
    #
    # `None` where nothing measured one, in which case the alert's own time is
    # the best available answer and the document is written from that.
    onset_at: datetime | None = None
    # When the alert said the incident began, where it said - a check that
    # reconciles stored figures dates the fault by the oldest record it found
    # wrong, and finds it on its own schedule. `onset_at` is this where no
    # series measured one, and then the time to the alert is that schedule
    # rather than anything detection took. `None` where the alert said nothing.
    onset_stated_by_the_alert: datetime | None = None
    # The minute the investigation looked from where nothing dated the incident:
    # the one the alarm fired in. Never an onset, and never read as one - the
    # document dates such an incident from the alert, as it dates any incident
    # nothing measured. Carried for what it says of the walk, that it had a
    # minute to read from, which `onset_at` being `None` does not say. `None`
    # where an onset anchored the walk, or nothing did.
    anchored_at: datetime | None = None
    # When the service came back, as Mitigation recorded it at the time - the
    # onset's counterpart, read off the account for the same reason. The minute
    # was measured on the window the verification wait was polling, and this
    # document reads a window bounded by the incident's close, so deriving it
    # again here would be deriving it over different minutes: one incident, two
    # recovery times, and nothing to say which is the one Argus acted on.
    #
    # `None` wherever nothing recorded one - an incident that escalated, one
    # nobody mitigated, or a confirmation nothing could date. The measurement
    # then falls back to the series, which is the best available answer and the
    # only one there is.
    recorded_recovery_at: datetime | None = None
    # A person reporting the incident resolved, where one did. Their report is
    # the fact (spec §16), so it ends the incident as said - never a minute the
    # series is searched from, as a recorded recovery is, which would be Argus
    # looking for a level falling to corroborate a claim it does not test.
    # Second to a recorded recovery, not over it: a recovery confirmed before
    # the report is an earlier answer to when the service came back.
    resolution: ResolutionRecord | None = None
    # That a person wrote in the incident's thread something the timeline
    # keeps. A message never stops a step already running, and a model not told
    # so reads the steps after a message as Argus pressing on regardless of it.
    people_wrote: bool = False
    # When Argus first posted about the incident where people could read it, and
    # where. Told only that nobody was paged, a write-up said nobody was told at
    # all, of an incident Argus had announced in its thread. `None` where no post
    # was accepted.
    first_told: FirstTold | None = None
    # That Mitigation watched for the service to come back and never saw it -
    # every look it recorded found it still broken. An answer rather than the
    # absence of one, so the measurement takes it as it takes a recorded minute:
    # asked again of this document's window, a service that flaps shows a lull
    # in one run and not in the next, and the incident is reported recovered or
    # not by when the run happened to read it.
    #
    # `False` where anything else is true: a recovery recorded, one confirmed
    # with nothing to date it by, or nobody watching at all - an incident that
    # escalated before acting, or one nobody mitigated.
    watched_and_never_recovered: bool = False
    # That Argus ran out of moves and handed the incident to a person - how the
    # incident ended, which a summary saying only what Argus did would leave
    # reading as one it closed. Argus's own move, never a person's report.
    escalated: bool = False
    # That Argus closed the incident as disproven: the window held none of what
    # the alarm claimed, so there was no incident - which the document says
    # instead of measuring one from the alert to the close, where it read as a
    # service broken for seconds and never back. The close is the disproof's
    # moment, since the ending is terminal.
    disproven: bool = False
    # The alert rule that paged, as the alert addressed it. `measure` reads the
    # metrics again over the whole incident, and read for this rule they carry its
    # own series - the one a fault in what the service answers departs in alone.
    # `None` for an incident paged by nothing that named a rule.
    rule: str | None = None
    # The alert in a line - its name and the service it named, `HighErrorRate
    # on io-shop`. A title rather than the alert's summary, which is the
    # sender's own words and is `alert_finding` below.
    alert_title: str
    # What the alert said it found, in its sender's words. A check that
    # reconciles stored figures against the records behind them reports how
    # many disagree, by how much and since when - figures nothing Argus reads
    # again can supply, and which a document without them credits to the
    # investigation or to nobody. `None` where the sender said nothing.
    alert_finding: str | None = None
    timeline: list[TimelineEntry]
    candidates: list[CandidateRecord]
    actions: list[ActionRecord]
    log_lines: list[str]
    # Where the furthest read of the logs ended - by default at the alert, though
    # the investigation picks its own windows. What the lines cannot say of
    # themselves: where they stop is where the reading stopped as often as
    # where the service did. `None` where no read is recorded.
    log_reading_ended: datetime | None = None
    # What changed on the service, as the investigation read it - what dates
    # the change the confirmed candidate blamed.
    changes: list[ChangeEvent] = []
    # Those of `changes` only Argus's own read of the flag provider's history
    # found - not returned by the Investigator's read of the changes where it
    # made one, and never seen by it where it made none. Listed among the
    # investigation's reads with nothing to tell them apart, a write-up
    # credited the Investigator with ruling out a flag it never saw.
    changes_the_walk_alone_read: list[ChangeEvent] = []
    # Where the furthest of the investigation's reads of the changes ended - a
    # window it picks for itself. Told only that a change was the walk's alone,
    # a write-up said the changes feed had failed to return one made past that
    # end, and asked for the feed to be fixed. `None` where no read is recorded.
    change_reading_ended: datetime | None = None
    # What each deployment the investigation looked into changed, in the order
    # it first asked - the one thing that tells a broken configuration from bad
    # code, and what names the deploy that carried a change.
    deployment_changes: list[DeploymentChangesRecord] = []
    # The fix Code-Fix proposed, where it proposed one. Structured rather than
    # left in `timeline` for the model to notice: the address is what a reader
    # of the finished document goes on to open, and a summary is free to be
    # written well without mentioning it.
    pull_request: OpenedPullRequest | None = None
    # What Code-Fix said of the code - why its change, or why there was none to
    # make - where it said anything. The one account of the mechanism read off
    # the source, and a static reading: nothing ran it.
    fix_explanation: str | None = None
    # The branch that reading was made on, and whether it contains the revision
    # running when the alert fired - `None` for either where it was not
    # established. A fix written against a branch that does not hold what ran
    # changes nothing that runs once merged, not until a deploy carries it.
    fix_branch_read: str | None = None
    fix_holds_what_ran: bool | None = None
    # Whether that reading's fix helps only once code outside the repository
    # changes too - and so was not kept: nothing of it is anywhere to open, and
    # its change to the repository has to be written again with the one outside.
    fix_needs_code_outside: bool = False
    # Each file that reading names, read again at the revision that ran - the
    # file as it ran where it differs from what was read, and what settles a
    # reading made on other text. Empty where none was read.
    files_as_they_ran: list[FileAsItRan] = []
    # How the code outside that reading's patch uses what it changes, said by
    # the syntax tree - what the reading got wrong when it surveyed those
    # readers in its own words. Empty where nothing does.
    uses_outside: list[CodeUse] = []
    # The action the gate declined because nothing could confirm it. Structured
    # rather than left in `timeline` for the model to notice, for the reason the
    # pull request is: what a reader of the finished document goes on to do is
    # exactly this, and a summary is free to be written well without mentioning
    # it.
    recommended_action: str | None = None
    # Each refusal to act at the gate, by where its line sits in `timeline`. A
    # refusal is a decision about how the incident ended - an action declined,
    # or none there to take - and the resolution lists it beside the actions
    # taken, said and dated as its line is. Empty where the gate refused
    # nothing.
    refusals: list[RefusalRecord] = []
    # What people told the incident in its thread, as leads, each with what the
    # investigation last made of it. Structured rather than left to the
    # timeline's one line per weighing: the document reports the words, the
    # standing and what each changed, and the timeline carries only the second.
    leads: list[ThreadMessage] = []
    # What came of reading the deploys, the flags and the logs - what an empty
    # list of each cannot say, which is whether anybody asked and whether
    # anything came back. Never asked by default, which is what a channel with
    # nothing in the record about it is.
    deploys_reading: ChannelReading = ChannelReading.NOT_ASKED
    flags_reading: ChannelReading = ChannelReading.NOT_ASKED
    logs_reading: ChannelReading = ChannelReading.NOT_ASKED

    @property
    def credited_action(self) -> ActionRecord | None:
        """The action credited with ending the incident - the first the service
        confirmed - or `None` where none was confirmed."""
        return next((action for action in self.actions
                     if action.verdict == Verdict.CONFIRMED), None)
