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
from argus_core.models import IncidentStatus, OpenedPullRequest, Postmortem
from argus_narration import where_a_report_came_from
from pydantic import BaseModel


class PostmortemView(BaseModel):
    """The postmortem, served on its own because it is the largest body Argus
    writes and the incident detail beside it is polled every two seconds."""

    root_cause: str | None
    customer_loss_estimate: Decimal | None
    estimate_currency: str | None
    engineer_minutes: int | None
    responders: int | None
    responder_titles: list[str] | None
    responder_cost_estimate: Decimal | None
    responder_cost_minimum: Decimal | None
    responder_cost_maximum: Decimal | None
    responder_cost_currency: str | None
    tokens_spent: int | None
    assumptions: list[str] | None
    executive_summary: str | None
    # Where the fix can be read, for the incidents that produced one - the one
    # thing on this page a reader goes on to do something with. `None` for the
    # ordinary ending, where a flag went back and the code was left alone.
    pull_request: OpenedPullRequest | None
    checklist_complete: bool
    created_at: datetime


def build_postmortem_view(postmortem: Postmortem) -> PostmortemView:
    """Shapes the postmortem row for transport."""
    return PostmortemView(
        root_cause=postmortem.root_cause,
        customer_loss_estimate=postmortem.customer_loss_estimate,
        estimate_currency=postmortem.estimate_currency,
        engineer_minutes=postmortem.engineer_minutes,
        responders=postmortem.responders,
        responder_titles=postmortem.responder_titles,
        responder_cost_estimate=postmortem.responder_cost_estimate,
        responder_cost_minimum=postmortem.responder_cost_minimum,
        responder_cost_maximum=postmortem.responder_cost_maximum,
        responder_cost_currency=postmortem.responder_cost_currency,
        tokens_spent=postmortem.tokens_spent,
        assumptions=postmortem.assumptions,
        executive_summary=postmortem.executive_summary,
        pull_request=postmortem.pull_request,
        checklist_complete=postmortem.checklist_complete,
        created_at=postmortem.created_at,
    )


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
