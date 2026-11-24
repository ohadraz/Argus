from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from core.ids import UuidStr
from core.models.alert import Alert
from core.models.incident_status import IncidentStatus
from core.models.lifespan import Lifespan


class IncidentStanding(BaseModel):
    """Which incident it is, where it stands, and when it was going on - what
    the doors matching a delivery to an incident decide by, and nothing they
    do not read.

    Apart from the whole incident, so a lookup that decides only by these
    reads no stored alert: an incident whose alert cannot be read then stops
    no later delivery from finding the incident it is about.
    """

    id: UuidStr
    status: IncidentStatus
    created_at: datetime
    # Absent while the incident is still being worked, which is a state it
    # spends most of its life in and `fixing` keeps it in despite reading like
    # an ending.
    ended_at: datetime | None

    @property
    def lifespan(self) -> Lifespan:
        """From the moment Argus heard of the incident to the moment it ended,
        or to now while it is still being worked."""
        return Lifespan(began_at=self.created_at, ended_at=self.ended_at)


class Incident(IncidentStanding):
    """An incident whole: where it stands, and the alert it was opened for."""

    alert: Alert
    # The trace the alert arrived in, as the propagator wrote it, which every
    # walk of the incident continues. Empty for one started outside any trace.
    trace_context: dict[str, str] = Field(default_factory=dict)
