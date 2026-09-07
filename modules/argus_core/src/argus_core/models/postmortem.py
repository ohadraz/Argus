from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel

from argus_core.ids import UuidStr


class Postmortem(BaseModel):
    id: UuidStr
    incident_id: UuidStr
    root_cause: str | None
    # What the incident cost, in three units. Only the first is an estimate;
    # the other two are measured, and none of them is convertible into the
    # others - a rate to do that belongs to the reader, not to this row.
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
