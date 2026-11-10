"""Rows these repository suites need to exist before they can read anything, and
the documents they write into them."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TypedDict, Unpack

import psycopg
from argus_core import utc_now
from argus_core.models import (
    ActionItem,
    ActionItemStatus,
    ActionItemType,
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
    DetectionMeasuredFrom,
    HypothesisConsidered,
    Impact,
    ImpactExtent,
    Lessons,
    NoTrigger,
    OpenedPullRequest,
    PostmortemDocument,
    PostmortemLead,
    ResolutionStep,
    ReviewCriterion,
    RevisionSource,
    Standing,
    TimelineEntry,
    TimelineMarker,
    Trigger,
    Weighing,
    WhyNoTrigger,
)
from argus_incidents.repository import incidents

DONT_CARE_MOMENT = datetime(2026, 10, 11, 14, 3, tzinfo=UTC)


def an_incident_created_for(conn: psycopg.Connection, alert: Alert) -> str:
    """One incident, written through the repository rather than by hand.

    Through the repository on purpose: every one of these suites reads rows
    that only exist because an incident does, and a fixture inserting them
    directly would be a second statement of the schema that stops agreeing
    with the first the day a column moves.
    """
    return incidents.create(conn, alert, at=utc_now())


class _WhatADocumentHolds(TypedDict, total=False):
    """Every field of a postmortem document, each typed as the model types it.

    Typed rather than `Any`, so mypy checks every name and value a case passes
    against this list, and this list against the model's own constructor: a
    field renamed in the model fails the typecheck here rather than being
    dropped while the case goes on asserting against the default.
    """

    root_cause: str | None
    cause_in_plain_words: str | None
    executive_summary: str | None
    symptom: str | None
    customer_loss_estimate: Decimal | None
    estimate_currency: str | None
    engineer_minutes: int | None
    responders: int | None
    paged: bool | None
    responder_titles: list[str]
    responder_cost_estimate: Decimal | None
    responder_cost_minimum: Decimal | None
    responder_cost_maximum: Decimal | None
    responder_cost_currency: str | None
    response_cost_basis: list[str]
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


def a_postmortem_document(**fields: Unpack[_WhatADocumentHolds]) -> PostmortemDocument:
    """A document holding the fields given and nothing else.

    Everything a case leaves alone is absent: what these suites check is how a
    value crosses the boundary, and figures filled in around it would be
    asserting `writing`'s arrangement through a database.
    """
    empty: _WhatADocumentHolds = {
        "root_cause": None,
        "executive_summary": None,
        "customer_loss_estimate": None,
        "estimate_currency": None,
        "engineer_minutes": None,
        "responders": None,
        "tokens_spent": None,
        "assumptions": []
    }

    return PostmortemDocument(**(empty | fields))


def a_postmortem_document_with_every_field() -> PostmortemDocument:
    """A document with no field left absent or empty - every figure, every
    section of the template, and a fix proposed.

    No value here is read by anything: each is there only to be something
    other than nothing, so a column nothing writes is the one way a row of it
    can come back empty.
    """
    titles = ["dont care", "dont care either"]
    amount = Decimal("1.00")
    figures: _WhatADocumentHolds = {
        "root_cause": "dont care",
        "cause_in_plain_words": "dont care",
        "executive_summary": "dont care",
        "symptom": "dont care",
        "customer_loss_estimate": amount,
        "estimate_currency": "usd",
        "engineer_minutes": 1,
        "responders": len(titles),
        "paged": True,
        "responder_titles": titles,
        "responder_cost_estimate": amount,
        "responder_cost_minimum": amount,
        "responder_cost_maximum": amount,
        "responder_cost_currency": "usd",
        "response_cost_basis": ["dont care"],
        "tokens_spent": 1,
        "assumptions": ["dont care"],
        "pull_request": an_opened_pull_request(),
        "recommended_action": "dont care",
        "disproven_at": DONT_CARE_MOMENT,
        "leads": [a_lead_weighed_as(Standing.SUPPORTED, effect="dont care")],
        "fix_branch_read": "dont care",
        "deploys_reading": ChannelReading.READ,
        "flags_reading": ChannelReading.READ,
        "logs_reading": ChannelReading.READ
    }

    return a_postmortem_document(**(figures | every_section_of_the_template()))


def an_opened_pull_request(number: int = 7) -> OpenedPullRequest:
    """A fix proposed as pull request `number`, at the address that number has."""
    return OpenedPullRequest(number=number,
                             url=f"https://github.invalid/ohadraz/io-shop/pull/{number}",
                             branch="argus/dont-care")


def every_section_of_the_template() -> _WhatADocumentHolds:
    """One of everything the template adds, each with every field filled, and
    each label one section cites standing for a row another section holds."""
    onset = DONT_CARE_MOMENT
    gap = timedelta(minutes=2, seconds=40)
    revision = "7c3ca00c7528df68d533f6e87acd4f23a55ab342"
    repository = "some-owner/some-repository"
    repository_address = f"https://github.com/{repository}"
    deploy = CitedChange(
        label="P1",
        change=ChangeEvent(
            kind=ChangeKind.DEPLOY,
            occurred_at=(onset - timedelta(minutes=5)).isoformat(),
            reference=revision,
            summary=f"deployed revision {revision}",
            actor="dont care",
            revision_source=RevisionSource(
                repository=repository,
                repository_address=repository_address,
                revision_address=f"{repository_address}/commit/{revision}",
                directory="deploy",
                directory_address=f"{repository_address}/tree/{revision}/deploy")),
        short_reference=revision[:7])
    values_file = "deploy/values-production.yaml"
    log_message = CitedEvidence(label="G3fa2", text="ZeroDivisionError in monthly_average")
    hypothesis = HypothesisConsidered(summary="dont care",
                                      confidence=0.8,
                                      result="confirmed",
                                      label="C1")
    action_item = ActionItem(number="AI-1",
                             text="dont care",
                             type=ActionItemType.MITIGATE,
                             owner="Argus",
                             tracking=an_opened_pull_request().url,
                             status=ActionItemStatus.DONE)

    return {
        "detection": Detection(alerted_at=onset + gap,
                               rule="HighErrorRate",
                               onset_at=onset,
                               gap=gap),
        "trigger": Trigger(subject="monthly-spend-feature",
                           from_state="off",
                           to_state="on",
                           changed_at=onset - timedelta(seconds=8)),
        "no_trigger": NoTrigger(why=WhyNoTrigger.CARRIED_BY_SEVERAL_BY_THE_ONSET,
                                candidate=hypothesis.label,
                                subject=values_file,
                                service="io-pricing",
                                deploys=[deploy.label]),
        "resolution": [ResolutionStep(at=onset + gap,
                                      action="dont care",
                                      by="Argus",
                                      has_a_way_back=True,
                                      outcome="dont care",
                                      label="M1")],
        "causal_chain": [ChainStep(text="dont care", cites=[log_message])],
        "contributing_factors": [ContributingFactor(text="dont care",
                                                    addressed_by=[action_item.number])],
        "hypotheses": [hypothesis],
        "action_items": [action_item],
        "lessons": Lessons(went_well=["dont care"],
                           went_wrong=["dont care"],
                           got_lucky=["dont care"]),
        "detection_lesson": DetectionLesson(gap=gap,
                                            measured_from=DetectionMeasuredFrom.LINE_PASSED,
                                            rule_waits=timedelta(minutes=1),
                                            rule_looks_back=timedelta(minutes=5),
                                            rule_evaluated_every=timedelta(seconds=30),
                                            scraping_and_storing=timedelta(seconds=30)),
        "timeline": [TimelineEntry(at=onset,
                                   who="Investigator",
                                   text="dont care",
                                   marker=TimelineMarker.IMPACT_BEGINS)],
        "changes_read": [deploy],
        "log_messages_read": [log_message],
        "deployment_changes_read": [CitedEvidence(label="D1",
                                                  text=f"modified {values_file}\n"
                                                       "  -  model: v1\n"
                                                       "  +  model: v2")],
        "code_read": [CitedEvidence(label="F1", text="dont care")],
        "as_it_ran_read": [CitedEvidence(label="R1", text="dont care")],
        "uses_outside_read": [CitedEvidence(label="U1", text="dont care")],
        "cause_measured": [CitedEvidence(label="K1", text="dont care")],
        "review": [ReviewCriterion(criterion="dont care", met=True),
                   ReviewCriterion(criterion="dont care either", met=None)],
        "impact": Impact(duration=timedelta(minutes=47),
                         extent=ImpactExtent.AT_LEAST,
                         peak_error_rate=0.42)
    }


def a_lead_weighed_as(standing: Standing | None, effect: str | None) -> PostmortemLead:
    """One thing a person told the incident, as the document reports it -
    weighed as `standing`, or never weighed where that is `None`."""
    return PostmortemLead(label="L1",
                          person_id="U-some-person",
                          person_name="Some Person",
                          text="dont care",
                          written_at=DONT_CARE_MOMENT,
                          weighing=(Weighing(standing=standing, reason="dont care")
                                    if standing is not None else None),
                          effect=effect)
