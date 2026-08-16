from __future__ import annotations

import pytest
from argus_core.models.alert import Alert
from argus_core.models.incident_state import IncidentState
from pydantic import ValidationError


@pytest.mark.unit
def test_alert_optional_fields_default_to_none() -> None:
    alert = Alert(service="checkout", alert_name="HighErrorRate")

    assert alert.severity is None
    assert alert.summary is None


@pytest.mark.unit
def test_alert_missing_required_field_raises() -> None:
    with pytest.raises(ValidationError):
        Alert(alert_name="HighErrorRate")  # type: ignore[call-arg]


@pytest.mark.unit
def test_incident_state_requires_alert() -> None:
    alert = Alert(service="checkout", alert_name="HighErrorRate")

    state = IncidentState(incident_id="abc-123", alert=alert, status="investigating")

    assert state.hypothesis is None
    assert state.confidence is None
