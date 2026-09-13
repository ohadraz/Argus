from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from argus_core.ids import UuidStr
from argus_core.models.incident_status import IncidentStatus


class Incident(BaseModel):
    id: UuidStr
    alert_payload: dict[str, object]
    status: IncidentStatus
    pr_url: str | None
    created_at: datetime
    # Absent while the incident is still being worked, which is a state it
    # spends most of its life in and `fixing` keeps it in despite reading like
    # an ending.
    ended_at: datetime | None
