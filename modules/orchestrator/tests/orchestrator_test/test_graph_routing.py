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
    route_after_next_candidate,
    stopping_when_withdrawn,
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


@pytest.mark.unit
def test_a_withdrawn_incident_is_routed_out_of_the_walk() -> None:
    # The routers decide from the state, and a node that did nothing changed
    # none - so a withdrawn incident would be sent round the same loop forever,
    # until LangGraph's recursion limit recorded the run as failed. The way out
    # is the one thing about a withdrawn incident that is true at every point in
    # the graph: there is nowhere left to go.
    routed = stopping_when_withdrawn(route_after_mitigation)

    assert routed(_a_state("withdrawn")) == "withdrawn"


@pytest.mark.unit
def test_a_live_incident_is_routed_by_the_router_it_wraps() -> None:
    routed = stopping_when_withdrawn(route_after_mitigation)

    assert routed(_a_state("resolved")) == "resolved"


@pytest.mark.unit
def test_every_router_stops_a_withdrawn_incident_the_same_way() -> None:
    # Wrapped at registration rather than checked inside each router, for the
    # reason every node is wrapped: five of them cannot each be trusted to
    # remember, and the one that forgot would be the loop.
    for route in (
        route_after_investigation,
        route_after_gate,
        route_after_mitigation,
        route_after_next_candidate,
        route_after_codefix,
    ):
        assert stopping_when_withdrawn(route)(_a_state("withdrawn")) == "withdrawn"


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
