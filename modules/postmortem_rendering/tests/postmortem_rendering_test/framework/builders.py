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
    ChangeEvent,
    ChangeKind,
    CitedChange,
    IncidentStatus,
    Postmortem,
    Report,
    ReportChannel,
    RevisionSource,
    TimelineEntry,
    TimelineMarker,
)

DONT_CARE_MOMENT = datetime(2026, 10, 11, 14, 30, tzinfo=UTC)

# A revision deployed from a repository on GitHub, and the repository's page.
SOME_DEPLOYED_REVISION = "7c3ca00c7528df68d533f6e87acd4f23a55ab342"
SOME_REPOSITORY_ADDRESS = "https://github.com/acme/shop"


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


def a_change_read(label: str = "P1", summary: str = "dont care") -> CitedChange:
    """A flag toggled, read under `label` and saying `summary`, with nowhere it
    can be opened and nobody named for it."""
    return CitedChange(label=label,
                       change=ChangeEvent(kind=ChangeKind.FLAG_TOGGLE,
                                          occurred_at="2026-10-11T14:00:00Z",
                                          reference="dont-care",
                                          summary=summary),
                       short_reference="dont-care")


def a_deploy_read(label: str = "P1") -> CitedChange:
    """`SOME_DEPLOYED_REVISION` deployed by kuki from the `deploy/` directory of
    the repository at `SOME_REPOSITORY_ADDRESS`, read under `label` and said as
    the read tier says a deploy."""
    return CitedChange(
        label=label,
        change=ChangeEvent(
            kind=ChangeKind.DEPLOY,
            occurred_at="2026-10-11T14:00:00Z",
            reference=SOME_DEPLOYED_REVISION,
            summary=(f"deployed revision {SOME_DEPLOYED_REVISION} from the acme/shop "
                     f"repository's deploy/ directory"),
            actor="kuki",
            revision_source=RevisionSource(
                repository="acme/shop",
                repository_address=SOME_REPOSITORY_ADDRESS,
                revision_address=f"{SOME_REPOSITORY_ADDRESS}/commit/{SOME_DEPLOYED_REVISION}",
                directory="deploy",
                directory_address=(f"{SOME_REPOSITORY_ADDRESS}/tree/"
                                   f"{SOME_DEPLOYED_REVISION}/deploy"))),
        short_reference=SOME_DEPLOYED_REVISION[:7])


def a_person_resolved_it(by: str,
                         at: datetime = DONT_CARE_MOMENT,
                         channel: ReportChannel = ReportChannel.ARGUS_UI,
                         note: str | None = None) -> StatusChanged:
    """The event a person's report of the incident over is recorded as."""
    return StatusChanged(incident_id=new_id(),
                         at=at,
                         to_status=IncidentStatus.RESOLVED,
                         reported=Report(by=by, channel=channel, note=note))
