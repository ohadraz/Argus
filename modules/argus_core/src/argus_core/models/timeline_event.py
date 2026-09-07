from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from argus_core.ids import UuidStr
from argus_core.models.actor import Actor
from argus_core.models.incident_status import IncidentStatus


class TimelineEvent(BaseModel):
    id: UuidStr
    incident_id: UuidStr
    to_status: IncidentStatus
    actor: Actor | None
    action: str | None
    result: str | None
    confidence: float | None
    created_at: datetime
