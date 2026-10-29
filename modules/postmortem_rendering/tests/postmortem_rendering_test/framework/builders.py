"""Postmortems, alerts and events, built with nothing in them a case does not ask
for.

Every field a case leaves alone is empty - `None`, or an empty list - so what a
case reads back can only have come from what it put in.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import TypedDict, Unpack

from argus_core import new_id
from argus_core.events import StatusChanged
from argus_core.models import (
    ActionItem,
    Alert,
    ChainStep,
    ChangeEvent,
    ChangeKind,
    ChannelReading,
    CitedChange,
    CitedEvidence,
    ContributingFactor,
    Detection,
    DetectionLesson,
    HypothesisConsidered,
    Impact,
    IncidentStatus,
    Lessons,
    OpenedPullRequest,
    Postmortem,
    PostmortemLead,
    Report,
    ReportChannel,
    ResolutionStep,
    ReviewCriterion,
    RevisionSource,
    TimelineEntry,
    TimelineMarker,
    Trigger,
)

DONT_CARE_MOMENT = datetime(2026, 10, 11, 14, 30, tzinfo=UTC)

# A revision deployed from a repository on GitHub, and the repository's page.
SOME_DEPLOYED_REVISION = "7c3ca00c7528df68d533f6e87acd4f23a55ab342"
SOME_REPOSITORY_ADDRESS = "https://github.com/acme/shop"


def an_alert(alert_name: str = "HighErrorRate", service: str = "io-shop") -> Alert:
    return Alert(alert_name=alert_name, service=service)


class _WhatAPostmortemHolds(TypedDict, total=False):
    """Every field of a written postmortem, each typed as the model types it.

    Typed rather than `Any`, so mypy checks every name and value a case passes
    against this list, and this list against the model's own constructor: a
    field renamed in the model fails the typecheck here rather than being
    dropped while the case goes on asserting against the default.
    """

    id: str
    incident_id: str
    created_at: datetime
    root_cause: str | None
    executive_summary: str | None
    symptom: str | None
    customer_loss_estimate: Decimal | None
    estimate_currency: str | None
    engineer_minutes: int | None
    responders: int | None
    responder_titles: list[str]
    responder_cost_estimate: Decimal | None
    responder_cost_minimum: Decimal | None
    responder_cost_maximum: Decimal | None
    responder_cost_currency: str | None
    tokens_spent: int | None
    assumptions: list[str]
    pull_request: OpenedPullRequest | None
    recommended_action: str | None
    leads: list[PostmortemLead]
    impact: Impact | None
    detection: Detection | None
    trigger: Trigger | None
    resolution: list[ResolutionStep]
    causal_chain: list[ChainStep]
    contributing_factors: list[ContributingFactor]
    hypotheses: list[HypothesisConsidered]
    action_items: list[ActionItem]
    lessons: Lessons | None
    detection_lesson: DetectionLesson | None
    timeline: list[TimelineEntry]
    changes_read: list[CitedChange]
    log_messages_read: list[CitedEvidence]
    deployment_changes_read: list[CitedEvidence]
    code_read: list[CitedEvidence]
    as_it_ran_read: list[CitedEvidence]
    uses_outside_read: list[CitedEvidence]
    fix_branch_read: str | None
    deploys_reading: ChannelReading | None
    flags_reading: ChannelReading | None
    logs_reading: ChannelReading | None
    review: list[ReviewCriterion]


def a_postmortem(**fields: Unpack[_WhatAPostmortemHolds]) -> Postmortem:
    """A written postmortem holding the fields given and nothing else."""
    empty: _WhatAPostmortemHolds = {
        "id": new_id(),
        "incident_id": new_id(),
        "root_cause": None,
        "executive_summary": None,
        "customer_loss_estimate": None,
        "estimate_currency": None,
        "engineer_minutes": None,
        "responders": None,
        "tokens_spent": None,
        "assumptions": [],
        "created_at": DONT_CARE_MOMENT
    }

    return Postmortem(**(empty | fields))


def a_marker(marker: TimelineMarker, at: datetime) -> TimelineEntry:
    """A timeline line carrying one of the four markers, saying nothing else."""
    return TimelineEntry(at=at, who=None, text="dont care", marker=marker)


def a_change_read(label: str = "P1", summary: str = "dont care") -> CitedChange:
    """A flag toggled, read under `label` and saying `summary`, with nowhere it
    can be opened and nobody named for it."""
    return CitedChange(label=label,
                       change=ChangeEvent(kind=ChangeKind.FLAG_TOGGLE,
                                          occurred_at="2026-10-11T14:00:00Z",
                                          reference="dont-care",
                                          summary=summary),
                       short_reference="dont-care")


def a_deploy_read(label: str = "P1") -> CitedChange:
    """`SOME_DEPLOYED_REVISION` deployed by kuki from the `deploy/` directory of
    the repository at `SOME_REPOSITORY_ADDRESS`, read under `label` and said as
    the read tier says a deploy."""
    return CitedChange(
        label=label,
        change=ChangeEvent(
            kind=ChangeKind.DEPLOY,
            occurred_at="2026-10-11T14:00:00Z",
            reference=SOME_DEPLOYED_REVISION,
            summary=(f"deployed revision {SOME_DEPLOYED_REVISION} from the acme/shop "
                     f"repository's deploy/ directory"),
            actor="kuki",
            revision_source=RevisionSource(
                repository="acme/shop",
                repository_address=SOME_REPOSITORY_ADDRESS,
                revision_address=f"{SOME_REPOSITORY_ADDRESS}/commit/{SOME_DEPLOYED_REVISION}",
                directory="deploy",
                directory_address=(f"{SOME_REPOSITORY_ADDRESS}/tree/"
                                   f"{SOME_DEPLOYED_REVISION}/deploy"))),
        short_reference=SOME_DEPLOYED_REVISION[:7])


def the_page_of(incident_id: str) -> str:
    """Where an incident's page is, by its id, as the server showing a document
    addresses it - this incident's own, or an earlier one a line is about."""
    return f"http://argus.example/incidents/{incident_id}"


def a_person_resolved_it(by: str,
                         at: datetime = DONT_CARE_MOMENT,
                         channel: ReportChannel = ReportChannel.ARGUS_UI,
                         note: str | None = None) -> StatusChanged:
    """The event a person's report of the incident over is recorded as."""
    return StatusChanged(incident_id=new_id(),
                         at=at,
                         to_status=IncidentStatus.RESOLVED,
                         reported=Report(by=by, channel=channel, note=note))
