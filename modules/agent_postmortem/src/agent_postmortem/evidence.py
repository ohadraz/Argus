"""Everything an incident left behind, handed over in one piece.

The agent holds no database connection. What it needs is scattered across four
tables the Orchestrator already owns - the incident's own row, its published
events, the candidates it ranked, the actions it took - and gathering them is
that module's business, not this one's. What arrives here is the result of
that gathering, in Argus's terms rather than in rows.

`tokens_spent` is summed rather than listed for the same reason: what the
replay log holds is one row per call, and adding them up is a query, not a
judgment.
"""

from __future__ import annotations

from datetime import datetime

from argus_core.models import (
    ChangeEvent,
    OpenedPullRequest,
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
    """

    taken_at: datetime
    action: str
    reversible: bool
    verdict: str | None
    standing: str
    paused_sync_of: str | None = None
    line: int | None = None


class DeploymentChangesRecord(BaseModel):
    """What one deployment changed, as the Investigator read it: every line the
    read tier said, under the revision it was read for.

    Lines rather than files and hunks, because the lines are what the model was
    shown and what the write-up is shown again - and what names the deploy
    that carried a change is what its own diff shows.
    """

    revision: str
    said: list[str]


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
    # What changed on the service, as the investigation read it - what dates
    # the change the confirmed candidate blamed.
    changes: list[ChangeEvent] = []
    # What each deployment the investigation looked into changed, in the order
    # it first asked - the one thing that tells a broken configuration from bad
    # code, and what names the deploy that carried a change.
    deployment_changes: list[DeploymentChangesRecord] = []
    tokens_spent: int
    # The fix Code-Fix proposed, where it proposed one. Structured rather than
    # left in `timeline` for the model to notice: the address is what a reader
    # of the finished document goes on to open, and a summary is free to be
    # written well without mentioning it.
    pull_request: OpenedPullRequest | None = None
    # What Code-Fix said of the code - why its change, or why there was none to
    # make - where it said anything. The one account of the mechanism read off
    # the source, and a static reading: nothing ran it.
    fix_explanation: str | None = None
    # The action the gate declined because nothing could confirm it. Structured
    # rather than left in `timeline` for the model to notice, for the reason the
    # pull request is: what a reader of the finished document goes on to do is
    # exactly this, and a summary is free to be written well without mentioning
    # it.
    recommended_action: str | None = None
    # What people told the incident in its thread, as leads, each with what the
    # investigation last made of it. Structured rather than left to the
    # timeline's one line per weighing: the document reports the words, the
    # standing and what each changed, and the timeline carries only the second.
    leads: list[ThreadMessage] = []

    @property
    def credited_action(self) -> ActionRecord | None:
        """The action credited with ending the incident - the first the service
        confirmed - or `None` where none was confirmed."""
        return next((action for action in self.actions
                     if action.verdict == Verdict.CONFIRMED), None)
