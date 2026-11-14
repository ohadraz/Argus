"""Postmortems, alerts and events, built with nothing in them a case does not ask
for.

Every field a case leaves alone is empty - `None`, or an empty list - so what a
case reads back can only have come from what it put in.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TypedDict, Unpack

from argus_core import new_id
from argus_core.events import StatusChanged
from argus_core.models import (
    ActionItem,
    ActionItemStatus,
    ActionItemType,
    AlarmClaim,
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
    ImpactExtent,
    IncidentStatus,
    Lessons,
    LogsInTheGap,
    NoTrigger,
    OpenedPullRequest,
    Postmortem,
    PostmortemLead,
    Report,
    ReportChannel,
    ResolutionStep,
    ReviewCriterion,
    RevisionSource,
    RuledOut,
    Standing,
    TimelineEntry,
    TimelineMarker,
    Trigger,
    Weighing,
)

DONT_CARE_MOMENT = datetime(2026, 10, 11, 14, 30, tzinfo=UTC)
# When the filled postmortem's incident began.
_FILLED_ONSET = datetime(2026, 10, 11, 14, 3, tzinfo=UTC)
# The labels the filled postmortem's rows go by, each named once: each is a
# row, and what another part of the document cites.
_THE_FIRST_LINE = "T1"
_THE_LOG_GROUP = "G3fa2"
_THE_ITEM = "AI-1"
_THE_CODE_READ = "F1"

# A revision deployed from a repository on GitHub, and the repository's page.
SOME_DEPLOYED_REVISION = "7c3ca00c7528df68d533f6e87acd4f23a55ab342"
SOME_REPOSITORY_ADDRESS = "https://github.com/acme/shop"


def an_alert(alert_name: str = "HighErrorRate",
             service: str = "io-shop",
             summary: str | None = None,
             claim: AlarmClaim = AlarmClaim.A_SERIES_CONDITION) -> Alert:
    """An alert on `service` - one watching a series, unless a case says it
    reports a finding of its own (`summary`, `claim`)."""
    return Alert(alert_name=alert_name, service=service, summary=summary, claim=claim)


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
    disproven_at: datetime | None
    leads: list[PostmortemLead]
    impact: Impact | None
    detection: Detection | None
    trigger: Trigger | None
    no_trigger: NoTrigger | None
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
    cause_measured: list[CitedEvidence]
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


def a_deploy_read(label: str = "P1", revision: str = SOME_DEPLOYED_REVISION) -> CitedChange:
    """`revision` - `SOME_DEPLOYED_REVISION` unless a test needs two deploys
    told apart - deployed by kuki from the `deploy/` directory of the
    repository at `SOME_REPOSITORY_ADDRESS`, read under `label` and said as
    the read tier says a deploy."""
    return CitedChange(
        label=label,
        change=ChangeEvent(
            kind=ChangeKind.DEPLOY,
            occurred_at="2026-10-11T14:00:00Z",
            reference=revision,
            summary=(f"deployed revision {revision} from the acme/shop "
                     f"repository's deploy/ directory"),
            actor="kuki",
            revision_source=RevisionSource(
                repository="acme/shop",
                repository_address=SOME_REPOSITORY_ADDRESS,
                revision_address=f"{SOME_REPOSITORY_ADDRESS}/commit/{revision}",
                directory="deploy",
                directory_address=(f"{SOME_REPOSITORY_ADDRESS}/tree/"
                                   f"{revision}/deploy"))),
        short_reference=revision[:7])


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


def a_postmortem_with_every_section_filled() -> Postmortem:
    """A postmortem with something in every section, and a row of every kind
    a label names, each worded so it can be found in what is made of it and
    nowhere else there."""
    return a_postmortem(
        executive_summary="The account page failed for most of an hour.",
        impact=Impact(duration=timedelta(minutes=40), extent=ImpactExtent.METRICS_MISSING,
                      peak_error_rate=None,
                      logs_in_the_gap=LogsInTheGap(
                          read=True, labels=[_THE_LOG_GROUP],
                          reach_until=_FILLED_ONSET + timedelta(minutes=10),
                          read_until=_FILLED_ONSET + timedelta(minutes=11),
                          read_until_the_alert=True)),
        recommended_action="Ask the owning team to guard the divisor.",
        root_cause="The divisor was never guarded.",
        causal_chain=[ChainStep(text="Requests failed on the account page.",
                                cites=[CitedEvidence(label=_THE_FIRST_LINE, text="errors rose")],
                                ruled_out=[RuledOut(text="The earlier deploy was healthy.",
                                                    cites=[CitedEvidence(label="T2",
                                                                         text="read")])])],
        contributing_factors=[ContributingFactor(text="Nothing reviewed the divisor.",
                                                 addressed_by=[_THE_ITEM])],
        hypotheses=[HypothesisConsidered(summary="An empty month reached the statement.",
                                         confidence=0.8, result="confirmed", label="C1")],
        trigger=Trigger(subject="monthly-spend", from_state="off", to_state="on",
                        changed_at=_FILLED_ONSET, kind=ChangeKind.FLAG_TOGGLE, actor="dana"),
        resolution=[ResolutionStep(at=_FILLED_ONSET + timedelta(minutes=5),
                                   action="Turned the flag off", by="Argus", has_a_way_back=True,
                                   outcome="recovered", label="M1")],
        detection=Detection(alerted_at=_FILLED_ONSET + timedelta(minutes=1), rule="HighErrorRate",
                            onset_at=_FILLED_ONSET, gap=timedelta(minutes=1),
                            said=CitedEvidence(label="AL1",
                                               text="Checkout errors crossed the threshold.")),
        action_items=[ActionItem(number=_THE_ITEM, text="Guard the divisor.",
                                 type=ActionItemType.PREVENT, owner=None, tracking=None,
                                 status=ActionItemStatus.OPEN)],
        lessons=Lessons(went_well=["The alert fired at once."],
                        went_wrong=["Nobody reviewed it."],
                        got_lucky=["It was a quiet hour."]),
        timeline=[a_marker(TimelineMarker.IMPACT_BEGINS, _FILLED_ONSET),
                  TimelineEntry(at=_FILLED_ONSET, who="Argus", text="The flag went on.",
                                label=_THE_FIRST_LINE)],
        leads=[PostmortemLead(label="L1", person_id="dont care", person_name="Dana",
                              text="I turned the flag on at two.", written_at=_FILLED_ONSET,
                              weighing=Weighing(standing=Standing.SUPPORTED,
                                                reason="The flag history shows it."),
                              effect="It pointed the walk at the flag.")],
        changes_read=[a_change_read("P1", summary="A deploy switched the model.")],
        log_messages_read=[CitedEvidence(label=_THE_LOG_GROUP, text="The divisor was zero.")],
        deployment_changes_read=[CitedEvidence(label="D1", text="The deploy changed the pool.")],
        code_read=[CitedEvidence(label=_THE_CODE_READ,
                                 text="The statement divides by the month.")],
        as_it_ran_read=[CitedEvidence(label="S1", text="The statement as it ran.")],
        uses_outside_read=[CitedEvidence(label="U1", text="The export calls the statement.")],
        cause_measured=[CitedEvidence(label="R1", text="Statements failed every minute.")],
        engineer_minutes=42,
        tokens_spent=12345,
        assumptions=["The flag was the only change."],
        review=[ReviewCriterion(criterion="Key incident data collected", met=True),
                ReviewCriterion(criterion="Document reviewed and shared", met=None),
                ReviewCriterion(criterion="Root-cause analysis complete", met=None,
                                because=f"the cause rests on {_THE_CODE_READ}, a reading of "
                                        f"the source nothing ran; running the proposed fix's "
                                        f"tests against the current code would confirm it "
                                        f"(AI-2)")])
