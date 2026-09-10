"""The postmortem row, shaped for transport.

Served on its own because it is the largest body Argus writes and the incident
detail beside it is polled every two seconds. Nothing here is derived: every
field is one the Postmortem agent wrote down, carried across unchanged.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from argus_core.models.postmortem import Postmortem
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
        checklist_complete=postmortem.checklist_complete,
        created_at=postmortem.created_at,
    )
