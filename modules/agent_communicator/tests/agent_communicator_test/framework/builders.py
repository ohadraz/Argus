"""The events an incident produced, as a human would be told them."""

from __future__ import annotations

from argus_core.events import ActionTaken, IncidentEvent, OnsetDetected, StatusChanged
from argus_core.models import IncidentStatus


def three_steps_of(incident_id: str) -> list[IncidentEvent]:
    """An incident's onset, the action taken for it, and where it ended.

    Three things a human is meant to hear, so that what these tests measure is
    the reading, the order and the place rather than the policy. Three rather
    than one because the questions worth asking of a relay - did it keep the
    order, did it stop where it said it stopped - cannot be asked of a single
    event.
    """
    return [
        OnsetDetected(incident_id=incident_id, onset="2026-08-30T10:03:00Z"),
        ActionTaken(
            incident_id=incident_id,
            hypothesis_id=None,
            action_type="revert-feature-flag",
            subject="monthly-spend-feature",
            enabled=False
        ),
        StatusChanged(incident_id=incident_id, to_status=IncidentStatus.RESOLVED)
    ]
