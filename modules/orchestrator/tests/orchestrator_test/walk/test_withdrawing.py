from __future__ import annotations

from collections.abc import Callable

import pytest
from argus_core.models.alert import Alert
from argus_core.models.incident_state import IncidentState
from argus_core.models.incident_status import IncidentStatus
from argus_testkit import Assertion, Scenario, all_of
from orchestrator.walk.choosing import route_after_next_candidate
from orchestrator.walk.fixing import route_after_codefix
from orchestrator.walk.gating import route_after_gate
from orchestrator.walk.investigating import route_after_investigation
from orchestrator.walk.mitigating import route_after_mitigation
from orchestrator.walk.routes import RESOLVED_ROUTE, WITHDRAWN_ROUTE
from orchestrator.walk.withdrawing import stopping_when_withdrawn

"""The one way out of the walk that is the same wherever it is asked.

The routers decide from the state, and a node that did nothing changed none -
so a withdrawn incident would be sent round the same loop until LangGraph's
recursion limit recorded the run as failed. Wrapped at registration rather than
checked inside each router, for the reason every node is wrapped: five of them
cannot each be trusted to remember, and the one that forgot would be the loop.
"""

type Route = Callable[[IncidentState], str]

DONT_CARE_ALERT = Alert(service="kuki", alert_name="HighErrorRate")
DONT_CARE_INCIDENT_ID = "buki-123"

EVERY_ROUTER: tuple[Route, ...] = (
    route_after_investigation,
    route_after_gate,
    route_after_mitigation,
    route_after_next_candidate,
    route_after_codefix
)


@pytest.mark.unit
def test_a_withdrawn_incident_is_routed_out_of_the_walk() -> None:
    Scenario() \
        .given(a_withdrawn_incident := _an_incident_in(IncidentStatus.WITHDRAWN)) \
        .when(lambda: stopping_when_withdrawn(route_after_mitigation)(a_withdrawn_incident)) \
        .then(_the_route_is(WITHDRAWN_ROUTE))


@pytest.mark.unit
def test_a_live_incident_is_routed_by_the_router_it_wraps() -> None:
    Scenario() \
        .given(a_resolved_incident := _an_incident_in(IncidentStatus.RESOLVED)) \
        .when(lambda: stopping_when_withdrawn(route_after_mitigation)(a_resolved_incident)) \
        .then(_the_route_is(RESOLVED_ROUTE))


@pytest.mark.unit
def test_every_router_stops_a_withdrawn_incident_the_same_way() -> None:
    Scenario() \
        .given(a_withdrawn_incident := _an_incident_in(IncidentStatus.WITHDRAWN)) \
        .when(lambda: [stopping_when_withdrawn(route)(a_withdrawn_incident)
                       for route in EVERY_ROUTER]) \
        .then(all_of(*(_the_route_at(position, EVERY_ROUTER[position], WITHDRAWN_ROUTE)
                       for position in range(len(EVERY_ROUTER)))))


def _an_incident_in(status: IncidentStatus) -> IncidentState:
    return IncidentState(incident_id=DONT_CARE_INCIDENT_ID,
                         alert=DONT_CARE_ALERT,
                         status=status)


def _the_route_is(expected: str) -> Assertion[str]:
    def assertion(route: str) -> bool:
        if route != expected:
            raise AssertionError(f"expected the route [{expected}], got [{route}]")

        return True

    return assertion


def _the_route_at(position: int, router: Route, expected: str) -> Assertion[list[str]]:
    """One assertion per router, so a router that forgot is named rather than
    reported as "one of five"."""
    def assertion(routes: list[str]) -> bool:
        if routes[position] != expected:
            raise AssertionError(
                f"expected [{router.__name__}] to route a withdrawn incident to "
                f"[{expected}], it routed to [{routes[position]}]"
            )

        return True

    return assertion
