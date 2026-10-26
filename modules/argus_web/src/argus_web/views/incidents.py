"""An incident's rows, arranged into the walk a reader follows.

Every argument arrives already ordered by the repository that returned it, and
that order is kept rather than re-imposed: ranking candidates and sequencing
actions are decisions the investigation made, and a view that sorted them again
would be a second opinion about them.

Attempts hang on the candidate they name, because "what did we try for this
explanation?" is the question a reader has while looking at one.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from types import MappingProxyType
from typing import Final

from argus_core import UuidStr, to_iso
from argus_core.events import IncidentEvent
from argus_core.models import (
    Alert,
    FailureMode,
    Hypothesis,
    Incident,
    IncidentStatus,
    TakenAction,
    Verdict,
)
from argus_incidents import when_it_was_taken
from argus_narration import (
    Finding,
    ShownRevision,
    a_finding,
    said_as_a_state,
    said_as_shown,
    said_plainly,
    the_links_in,
)
from pydantic import BaseModel, Field

# A walk shown with no revision the incident read to say short.
_NO_REVISIONS: Final[Mapping[str, ShownRevision]] = MappingProxyType({})


class Attempt(BaseModel):
    """One action the walk took, as a reader sees it."""

    action_type: str
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
    failure_mode: FailureMode | None
    confidence: float | None
    subject: str | None
    # The two ends of the change blamed on that subject, said the way the flag
    # table says them. Already in the page's voice, unlike `confidence` beside
    # it: a percentage is formatted from a number the template also compares,
    # where a state is only ever shown.
    moved_from: str = ""
    moved_to: str = ""
    # Each in the words the timeline says it in: a finding is shown, never the
    # record it is kept in.
    evidence: list[Finding]
    tested: bool
    result: str | None
    attempts: list[Attempt]
    # Each revision its claim, subject and findings name, by the short form
    # they say it by, and where it opens - as a line of the timeline leads.
    links: dict[str, str] = Field(default_factory=dict)


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
        created_at=incident.created_at
    )


def build_incident_detail(
    incident: Incident,
    candidates: list[Hypothesis],
    attempts: list[TakenAction],
    account: Sequence[IncidentEvent],
    minutes: Sequence[str] = (),
    logged: Sequence[str] = (),
    revisions: Mapping[str, ShownRevision] = _NO_REVISIONS
) -> IncidentDetail:
    """Arranges an incident's rows into the walk a reader follows.

    Every argument is already ordered by the repository that returned it, and
    that order is kept rather than re-imposed: ranking candidates and sequencing
    actions are decisions the investigation made, and a view that sorted them
    again would be a second opinion about them.

    Attempts are attached to the candidate they name, because "what did we try
    for this explanation?" is the question a reader has while looking at one.
    Each is dated as the postmortem dates it, by `account` - the incident's
    events - through `when_it_was_taken`: dated by its row, the page put a
    roll-back a second before the postmortem did.

    `minutes` and `logged` are the rows the page holds - the minutes read and
    the minutes logged - so a finding naming one of them leads to it, as the
    same finding does in the timeline. Empty, a finding leads nowhere.

    A candidate's words are said as the timeline says them, an instant in
    them on the clock and read against the day the incident opened, and each
    of `revisions` - the ones the incident read - by its short form, leading
    to its commit.
    """
    attached: dict[str, list[Attempt]] = {}
    unattributed: list[Attempt] = []

    for taken_action in attempts:
        shown = _an_attempt(taken_action, account)
        if taken_action.hypothesis_id is None:
            unattributed.append(shown)
        else:
            attached.setdefault(taken_action.hypothesis_id, []).append(shown)

    return IncidentDetail(
        id=incident.id,
        alert=Alert.model_validate(incident.alert_payload),
        status=incident.status,
        created_at=incident.created_at,
        candidates=[
            _a_candidate(candidate, attached.get(candidate.id, []), minutes, logged,
                         opened=to_iso(incident.created_at), revisions=revisions)
            for candidate in candidates
        ],
        unattributed_attempts=unattributed
    )


def _an_attempt(taken_action: TakenAction, account: Sequence[IncidentEvent]) -> Attempt:
    """One action row, as a reader sees it.

    An action with no outcome yet is undecided rather than undone: it was taken
    a moment ago and the service has not answered. That is a state to show, not
    an absence to hide - the same way the shop's console shows a minute still
    in progress.

    Undone is the verdict an action gets when the service did not recover and
    the action left something to put back: the walk puts such an action back
    before returning it - see `agent_mitigation` - so `REFUTED` is also the
    record that the change was reverted. An action that left nothing behind is
    refuted with nothing undone, which is a cleaner ending and reads as one.
    That is an inference from the walk's contract rather than something the row
    states, and if the contract changes the fix is to record the revert, not to
    read it off a different verdict.

    The outcome is shown as the page was handed it, which is the spelling the
    column holds even where no verdict spells it. A row an older version wrote
    is still an action a human is looking at, and blanking it would hide the
    one part of it nobody can otherwise recover.
    """
    return Attempt(
        action_type=taken_action.type,
        outcome=taken_action.outcome,
        undone=taken_action.outcome is Verdict.REFUTED,
        taken_at=when_it_was_taken(taken_action, account)
    )


def _a_candidate(hypothesis: Hypothesis,
                 attempts: list[Attempt],
                 minutes: Sequence[str],
                 logged: Sequence[str],
                 opened: str,
                 revisions: Mapping[str, ShownRevision]) -> Candidate:
    """One hypothesis row, with the attempts made for it.

    A candidate the walk never reached comes back with no attempts and
    `tested` false, which is the difference between an investigation that ran
    out of options and one that stopped because it was right.
    """
    summary = said_as_shown(said_plainly(hypothesis.summary, beside=opened), revisions)
    subject = (said_as_shown(hypothesis.subject, revisions)
               if hypothesis.subject is not None else None)
    moved_from = said_as_shown(said_as_a_state(hypothesis.from_state), revisions)
    moved_to = said_as_shown(said_as_a_state(hypothesis.to_state), revisions)
    evidence = [finding.model_copy(update={"text": said_as_shown(finding.text, revisions)})
                for finding in (a_finding(cited, minutes, logged, beside=opened)
                                for cited in hypothesis.supporting_evidence)]

    return Candidate(
        rank=hypothesis.rank,
        summary=summary,
        failure_mode=hypothesis.failure_mode,
        confidence=hypothesis.confidence,
        subject=subject,
        moved_from=moved_from,
        moved_to=moved_to,
        evidence=evidence,
        tested=hypothesis.tested,
        result=hypothesis.result,
        attempts=attempts,
        links=the_links_in([summary, subject or "", moved_from, moved_to,
                            *(finding.text for finding in evidence)], revisions)
    )
