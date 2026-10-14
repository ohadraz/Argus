"""The postmortem row, shaped for transport.

Served on its own because it is the largest body Argus writes and the incident
detail beside it is polled every two seconds. Nothing here is derived: every
field is one the Postmortem agent wrote down, carried across unchanged.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal

from argus_core.events import IncidentEvent, StatusChanged
from argus_core.models import (
    ActionItem,
    ChainStep,
    ContributingFactor,
    Detection,
    HypothesisConsidered,
    Impact,
    IncidentStatus,
    Lessons,
    OpenedPullRequest,
    Postmortem,
    PostmortemLead,
    ResolutionStep,
    ReviewCriterion,
    TimelineEntry,
    Trigger,
)
from argus_narration import where_a_report_came_from
from pydantic import BaseModel


class PostmortemView(BaseModel):
    """The postmortem, served on its own because it is the largest body Argus
    writes and the incident detail beside it is polled every two seconds.

    Every field of the row but which row it is and which incident it belongs
    to, which the page already knows, and what the response cost - stored,
    and never shown, figure or range. Divided by the minutes beside it, any of
    them is a rate of pay, and with one responder and their title on the page
    it is that person's band.
    """

    root_cause: str | None
    executive_summary: str | None
    symptom: str | None
    customer_loss_estimate: Decimal | None
    estimate_currency: str | None
    engineer_minutes: int | None
    responders: int | None
    responder_titles: list[str]
    tokens_spent: int | None
    assumptions: list[str]
    # Where the fix can be read, for the incidents that produced one - the one
    # thing on this page a reader goes on to do something with. `None` for the
    # ordinary ending, where a flag went back and the code was left alone.
    pull_request: OpenedPullRequest | None
    # What Argus worked out to do and declined, for a person to do instead.
    # `None` for every ending Argus reached itself.
    recommended_action: str | None
    # What people told the incident in its thread, what the investigation made
    # of each, and whether it changed what was done - the answer the person who
    # wrote one comes here for. Empty where nobody wrote.
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
    timeline: list[TimelineEntry]
    evidence_read: int | None
    review: list[ReviewCriterion]
    created_at: datetime


def build_postmortem_view(postmortem: Postmortem) -> PostmortemView:
    """Shapes the postmortem row for transport.

    Filled by name from the row rather than field by field: a hand-written
    mapping of thirty fields is thirty chances to cross two of them.
    """
    return PostmortemView.model_validate(
        postmortem.model_dump(include=set(PostmortemView.model_fields)))


class ResolutionView(BaseModel):
    """Who reported the incident resolved, through which door, when, and what
    they said.

    Beside the postmortem rather than inside it. A document written before the
    report is not rewritten, and one written after is the model's prose - so
    what the person did is read off the account and shown as it was recorded,
    whichever came first.
    """

    by: str
    channel: str
    at: datetime
    note: str | None


def build_resolution_view(recorded: Sequence[IncidentEvent]) -> ResolutionView | None:
    """The person's resolution among an incident's events, if a person
    resolved it.

    The last, though an incident is resolved at most once: the row refuses a
    second, so there is one to find or none.
    """
    resolutions = [event for event in recorded
                   if isinstance(event, StatusChanged)
                   and event.to_status is IncidentStatus.RESOLVED
                   and event.reported is not None]

    if not resolutions:
        return None

    resolution = resolutions[-1]
    assert resolution.reported is not None

    return ResolutionView(by=resolution.reported.by,
                          channel=where_a_report_came_from(resolution.reported.channel),
                          at=resolution.at,
                          note=resolution.reported.note)
