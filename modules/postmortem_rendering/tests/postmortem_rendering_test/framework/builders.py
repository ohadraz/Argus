"""Postmortems, alerts and events, built with nothing in them a case does not ask
for.

Every field a case leaves alone is empty - `None`, or an empty list - so what a
case reads back can only have come from what it put in.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from argus_core import new_id
from argus_core.events import StatusChanged
from argus_core.models import (
    Alert,
    IncidentStatus,
    Postmortem,
    Report,
    ReportChannel,
    TimelineEntry,
    TimelineMarker,
)

DONT_CARE_MOMENT = datetime(2026, 10, 11, 14, 30, tzinfo=UTC)


def an_alert(alert_name: str = "HighErrorRate", service: str = "io-shop") -> Alert:
    return Alert(alert_name=alert_name, service=service)


def a_postmortem(**fields: Any) -> Postmortem:
    """A written postmortem holding the fields given and nothing else."""
    empty: dict[str, Any] = {
        "id": new_id(),
        "incident_id": new_id(),
        "root_cause": None,
        "executive_summary": None,
        "customer_loss_estimate": None,
        "estimate_currency": None,
        "engineer_minutes": None,
        "responders": None,
        "tokens_spent": None,
        "assumptions": [],
        "created_at": DONT_CARE_MOMENT
    }

    return Postmortem(**(empty | fields))


def a_marker(marker: TimelineMarker, at: datetime) -> TimelineEntry:
    """A timeline line carrying one of the four markers, saying nothing else."""
    return TimelineEntry(at=at, who=None, text="dont care", marker=marker)


def a_person_resolved_it(by: str,
                         at: datetime = DONT_CARE_MOMENT,
                         channel: ReportChannel = ReportChannel.ARGUS_UI,
                         note: str | None = None) -> StatusChanged:
    """The event a person's report of the incident over is recorded as."""
    return StatusChanged(incident_id=new_id(),
                         at=at,
                         to_status=IncidentStatus.RESOLVED,
                         reported=Report(by=by, channel=channel, note=note))
