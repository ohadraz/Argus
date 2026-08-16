from __future__ import annotations

import pytest
from argus_core.models.alert import Alert
from argus_core.models.incident_state import IncidentState
from orchestrator.graph import (
    route_after_codefix,
    route_after_investigation,
    route_after_mitigation,
    tier_gate_node,
)


@pytest.mark.unit
def test_tier_gate_node_is_a_no_op_pass_through_TEMPORARY() -> None:
    assert tier_gate_node(_a_state("investigating")) == {}


@pytest.mark.unit
def test_route_after_investigation_goes_to_mitigation_when_mitigating() -> None:
    assert route_after_investigation(_a_state("mitigating")) == "mitigating"


@pytest.mark.unit
def test_route_after_investigation_escalates_otherwise() -> None:
    assert route_after_investigation(_a_state("escalated")) == "escalated"


@pytest.mark.unit
def test_route_after_mitigation_resolves() -> None:
    assert route_after_mitigation(_a_state("resolved")) == "resolved"


@pytest.mark.unit
def test_route_after_mitigation_routes_to_fixing() -> None:
    assert route_after_mitigation(_a_state("fixing")) == "fixing"


@pytest.mark.unit
def test_route_after_mitigation_escalates_otherwise() -> None:
    assert route_after_mitigation(_a_state("escalated")) == "escalated"


@pytest.mark.unit
def test_route_after_codefix_resolves_only_when_resolved() -> None:
    assert route_after_codefix(_a_state("resolved")) == "resolved"
    assert route_after_codefix(_a_state("fixing")) == "escalated"


def _a_state(status: str) -> IncidentState:
    some_service = "kuki"
    some_alert_name = "HighErrorRate"
    some_incident_id = "buki-123"
    some_alert = Alert(service=some_service, alert_name=some_alert_name)

    return IncidentState(incident_id=some_incident_id, alert=some_alert, status=status)  # type: ignore[arg-type]
