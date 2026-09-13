"""An incident's rows, arranged into the walk a reader follows.

Every argument arrives already ordered by the repository that returned it, and
that order is kept rather than re-imposed: ranking candidates and sequencing
actions are decisions the investigation made, and a view that sorted them again
would be a second opinion about them.

Attempts hang on the candidate they name, because "what did we try for this
explanation?" is the question a reader has while looking at one.
"""

from __future__ import annotations

from datetime import datetime

from argus_core.ids import UuidStr
from argus_core.models.actor import Actor
from argus_core.models.alert import Alert
from argus_core.models.cause import CauseType
from argus_core.models.evidence import Evidence
from argus_core.models.hypothesis import Hypothesis
from argus_core.models.incident import Incident
from argus_core.models.incident_status import IncidentStatus
from argus_core.models.taken_action import TakenAction
from argus_core.models.timeline_event import TimelineEvent
from argus_narration import said_as_a_state
from pydantic import BaseModel

# The verdict a reversible action gets when the service did not recover. The
# walk undoes such an action before returning it - see `agent_mitigation` - so
# "refuted" is also the record that the change was put back. Named here because
# that is an inference from the walk's contract rather than something the row
# states, and if the contract ever changes the fix is to record the revert, not
# to re-derive it from a different string.
_REFUTED = "refuted"


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
    # The two ends of the change blamed on that subject, said the way the flag
    # table says them. Already in the page's voice, unlike `confidence` beside
    # it: a percentage is formatted from a number the template also compares,
    # where a state is only ever shown.
    moved_from: str = ""
    moved_to: str = ""
    evidence: list[Evidence]
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
    timeline: list[TimelineEvent]
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

    for taken_action in attempts:
        shown = _an_attempt(taken_action)
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
            _a_candidate(candidate, attached.get(candidate.id, []))
            for candidate in candidates
        ],
        unattributed_attempts=unattributed,
        timeline=[_a_timeline_entry(event) for event in timeline]
    )


def _an_attempt(taken_action: TakenAction) -> Attempt:
    """One action row, as a reader sees it.

    An action with no outcome yet is undecided rather than undone: it was taken
    a moment ago and the service has not answered. That is a state to show, not
    an absence to hide - the same way the shop's console shows a minute still
    in progress.
    """
    return Attempt(
        action_type=taken_action.type,
        outcome=taken_action.outcome,
        undone=taken_action.outcome == _REFUTED,
        taken_at=taken_action.taken_at
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
        moved_from=said_as_a_state(hypothesis.from_state),
        moved_to=said_as_a_state(hypothesis.to_state),
        evidence=hypothesis.supporting_evidence,
        tested=hypothesis.tested,
        result=hypothesis.result,
        attempts=attempts
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
        confidence=event.confidence
    )
