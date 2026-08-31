from __future__ import annotations

import pytest
from argus_core.models.action import Action
from argus_core.models.alert import Alert
from argus_core.models.incident_state import IncidentState
from orchestrator.graph import (
    route_after_codefix,
    route_after_gate,
    route_after_investigation,
    route_after_mitigation,
)


@pytest.mark.unit
def test_route_after_investigation_goes_to_mitigation_when_mitigating() -> None:
    assert route_after_investigation(_a_state("mitigating")) == "mitigating"


@pytest.mark.unit
def test_route_after_investigation_escalates_otherwise() -> None:
    assert route_after_investigation(_a_state("escalated")) == "escalated"


@pytest.mark.unit
def test_route_after_the_gate_reaches_the_action_when_the_gate_let_it_through() -> None:
    assert route_after_gate(_a_state_proposing(_an_action())) == "mitigating"


@pytest.mark.unit
def test_route_after_the_gate_hands_a_rejected_action_to_the_walk() -> None:
    # The gate clears the action it refused rather than marking the incident
    # escalated: the refusal is about this action, and the explanations after
    # it on the list may be perfectly reversible. Whether anything follows is
    # the walk's decision, made in one place - so a rejected action reaches no
    # state-changing call, and no premature ending either.
    assert route_after_gate(_a_state("mitigating")) == "next_candidate"


@pytest.mark.unit
def test_route_after_mitigation_resolves() -> None:
    assert route_after_mitigation(_a_state("resolved")) == "resolved"


@pytest.mark.unit
def test_route_after_mitigation_hands_a_refuted_action_to_the_walk() -> None:
    # A refuted action stays in `mitigating` - the same phase of the same
    # incident, with another explanation about to be tried. It asks the walk
    # whether there is one, and Code-Fix is what happens when there is not.
    assert route_after_mitigation(_a_state("mitigating")) == "next_candidate"


@pytest.mark.unit
def test_route_after_mitigation_escalates_otherwise() -> None:
    assert route_after_mitigation(_a_state("escalated")) == "escalated"


@pytest.mark.unit
def test_route_after_codefix_resolves_only_when_resolved() -> None:
    assert route_after_codefix(_a_state("resolved")) == "resolved"
    assert route_after_codefix(_a_state("fixing")) == "escalated"


def _an_action() -> Action:
    return Action(
        action_type="revert_feature_flag",
        flag="monthly-spend-feature",
        enabled=False,
        undo_descriptor={"tool": "set_feature_flag", "was_enabled": True},
    )


def _a_state_proposing(action: Action) -> IncidentState:
    return _a_state("mitigating").model_copy(update={"proposed_action": action})


def _a_state(status: str) -> IncidentState:
    some_service = "kuki"
    some_alert_name = "HighErrorRate"
    some_incident_id = "buki-123"
    some_alert = Alert(service=some_service, alert_name=some_alert_name)

    return IncidentState(incident_id=some_incident_id, alert=some_alert, status=status)  # type: ignore[arg-type]
