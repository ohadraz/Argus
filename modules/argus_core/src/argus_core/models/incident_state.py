from __future__ import annotations

from pydantic import BaseModel

from .alert import Alert
from .incident_status import IncidentStatus


class IncidentState(BaseModel):
    """LangGraph `StateGraph` state (spec §7.1), mirroring the Postgres
    schema (§11.1) with the slice this change's stub nodes read/write."""

    incident_id: str
    alert: Alert
    status: IncidentStatus
    hypothesis: str | None = None
    confidence: float | None = None
    action_outcome: str | None = None