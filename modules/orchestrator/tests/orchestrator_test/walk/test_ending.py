"""The ways out of the walk that are the same wherever they are asked.

A person can end an incident at any point in the walk, in one of two ways, and
the walk does opposite things with them: a withdrawal leaves the graph at once,
and a resolution goes on to remember what was tried and write the incident up.

The routers decide from the state, and a node that did nothing changed none -
so an incident a person ended would be sent round the same loop until
LangGraph's recursion limit recorded the run as failed. Wrapped at
registration rather than checked inside each router, for the reason every node
is wrapped: five of them cannot each be trusted to remember, and the one that
forgot would be the loop.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from argus_core.models import Alert, IncidentStatus
from argus_testkit import Assertion, Scenario, all_of
from orchestrator.walk.choosing import route_after_next_candidate
from orchestrator.walk.ending import stopping_when_a_person_ended_it
from orchestrator.walk.fixing import route_after_codefix
from orchestrator.walk.gating import route_after_gate
from orchestrator.walk.investigating import route_after_investigation
from orchestrator.walk.mitigating import route_after_mitigation
from orchestrator.walk.routes import FIXING_ROUTE, RESOLVED_ROUTE, WITHDRAWN_ROUTE
from orchestrator.walk.state import IncidentState

from orchestrator_test.framework.assertions import the_route_is

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
        .when(lambda: stopping_when_a_person_ended_it(route_after_mitigation)(
            a_withdrawn_incident)) \
        .then(the_route_is(WITHDRAWN_ROUTE))


@pytest.mark.unit
def test_a_resolved_incident_is_routed_to_be_written_up() -> None:
    # Not out of the walk, as a withdrawal is. The person who reported it over
    # is owed the postmortem, and the next incident is owed what this one tried.
    Scenario() \
        .given(a_resolved_incident := _an_incident_in(IncidentStatus.RESOLVED)) \
        .when(lambda: stopping_when_a_person_ended_it(route_after_mitigation)(
            a_resolved_incident)) \
        .then(the_route_is(RESOLVED_ROUTE))


@pytest.mark.unit
def test_a_live_incident_is_routed_by_the_router_it_wraps() -> None:
    Scenario() \
        .given(a_mitigated_incident := _an_incident_in(IncidentStatus.MITIGATED)) \
        .when(lambda: stopping_when_a_person_ended_it(route_after_mitigation)(
            a_mitigated_incident)) \
        .then(the_route_is(FIXING_ROUTE))


@pytest.mark.unit
@pytest.mark.parametrize(("ending", "route"), [(IncidentStatus.WITHDRAWN, WITHDRAWN_ROUTE),
                                               (IncidentStatus.RESOLVED, RESOLVED_ROUTE)])
def test_every_router_routes_a_persons_ending_the_same_way(ending: IncidentStatus,
                                                           route: str) -> None:
    Scenario() \
        .given(an_ended_incident := _an_incident_in(ending)) \
        .when(lambda: [stopping_when_a_person_ended_it(router)(an_ended_incident)
                       for router in EVERY_ROUTER]) \
        .then(all_of(*(_the_route_at(position, EVERY_ROUTER[position], route)
                       for position in range(len(EVERY_ROUTER)))))


def _an_incident_in(status: IncidentStatus) -> IncidentState:
    return IncidentState(incident_id=DONT_CARE_INCIDENT_ID,
                         alert=DONT_CARE_ALERT,
                         status=status)


def _the_route_at(position: int, router: Route, expected: str) -> Assertion[list[str]]:
    """One assertion per router, so a router that forgot is named rather than
    reported as "one of five"."""
    def assertion(routes: list[str]) -> bool:
        if routes[position] != expected:
            raise AssertionError(
                f"Expected [{router.__name__}] to route an incident a person ended "
                f"to [{expected}], it routed to [{routes[position]}]."
            )

        return True

    return assertion
