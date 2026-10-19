"""Who reported an incident resolved, and when Argus escalated it, read off
its events.

Beside the postmortem rather than inside it. A document written before the
report is not rewritten, and one written after is the model's prose - so what
the person did is read off the account each time the document is shown, and
shown as it was recorded, whichever came first.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from argus_core.events import IncidentEvent, StatusChanged
from argus_core.models import IncidentStatus
from argus_narration import where_a_report_came_from
from pydantic import BaseModel, ConfigDict


class ReportedResolution(BaseModel):
    """Who reported the incident resolved, through which door, when, and what
    they said."""

    model_config = ConfigDict(frozen=True)

    by: str
    channel: str
    at: datetime
    note: str | None


class Escalation(BaseModel):
    """When Argus handed the incident to a person, and the reason it gave."""

    model_config = ConfigDict(frozen=True)

    at: datetime
    detail: str | None


def the_escalation(recorded: Sequence[IncidentEvent]) -> Escalation | None:
    """Argus's last move of the incident to escalated, if it made one - how an
    incident it could not end, and nobody has, did end."""
    escalations = [event for event in recorded
                   if isinstance(event, StatusChanged)
                   and event.to_status is IncidentStatus.ESCALATED
                   and event.reported is None]

    if not escalations:
        return None

    return Escalation(at=escalations[-1].at, detail=escalations[-1].detail)


def the_reported_resolution(recorded: Sequence[IncidentEvent]) -> ReportedResolution | None:
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

    return ReportedResolution(by=resolution.reported.by,
                              channel=where_a_report_came_from(resolution.reported.channel),
                              at=resolution.at,
                              note=resolution.reported.note)
