from __future__ import annotations

import pytest
from argus_core.models.alert import Alert
from argus_core.models.incident_state import IncidentState
from argus_core.models.incident_status import IncidentStatus
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
def test_incident_state_optional_fields_default_to_none() -> None:
    some_service = "kuki-service"
    some_alert_name = "HighErrorRate"
    some_incident_id = "buki-123"
    some_alert = Alert(service=some_service, alert_name=some_alert_name)

    state = IncidentState(incident_id=some_incident_id, 
                          alert=some_alert, 
                          status=IncidentStatus.INVESTIGATING)

    assert state.hypothesis is None
    assert state.confidence is None


@pytest.mark.unit
def test_incident_state_missing_alert_raises() -> None:
    with pytest.raises(ValidationError):
        IncidentState(incident_id="buki-123", 
                      status=IncidentStatus.INVESTIGATING)  # type: ignore[call-arg]