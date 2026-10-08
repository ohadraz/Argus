from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from argus_core.ids import UuidStr
from argus_core.models.incident_status import IncidentStatus


class Incident(BaseModel):
    id: UuidStr
    alert_payload: dict[str, object]
    status: IncidentStatus
    created_at: datetime
    # Absent while the incident is still being worked, which is a state it
    # spends most of its life in and `fixing` keeps it in despite reading like
    # an ending.
    ended_at: datetime | None
    # The trace the alert arrived in, as the propagator wrote it, which every
    # walk of the incident continues. Empty for one started outside any trace.
    trace_context: dict[str, str] = Field(default_factory=dict)
