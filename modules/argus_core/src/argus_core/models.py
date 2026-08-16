from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

IncidentStatus = Literal["investigating", "mitigating", "resolved", "fixing", "escalated"]


class Alert(BaseModel):
    """Argus's own normalized alert shape (spec §7.9, §25).

    Built by a vendor-specific adapter (e.g. argus_web's Grafana parser) at
    the system boundary - nothing past that boundary ever sees a vendor's
    raw payload shape.
    """

    service: str
    alert_name: str
    severity: str | None = None
    summary: str | None = None
    started_at: datetime | None = None


class IncidentState(BaseModel):
    """LangGraph `StateGraph` state (spec §7.1), mirroring the Postgres
    schema (§11.1) with the slice this change's stub nodes read/write."""

    incident_id: str
    alert: Alert
    status: IncidentStatus
    hypothesis: str | None = None
    confidence: float | None = None
    action_outcome: str | None = None
