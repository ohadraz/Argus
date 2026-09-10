from __future__ import annotations

from typing import Any

import pytest
from argus_core.models.alert import Alert
from argus_core.models.incident_state import IncidentState
from argus_core.models.incident_status import IncidentStatus
from argus_testkit import Assertion, Scenario, all_of
from orchestrator.walk.fixing import codefix_node, route_after_codefix
from orchestrator.walk.narrating import Narration
from orchestrator.walk.routes import ESCALATED_ROUTE, RESOLVED_ROUTE

"""Looking for a permanent fix, and admitting there isn't one.

Code-Fix is still a stub, so what is worth asserting is not the fix but the
answer: an incident that reaches here leaves here, saying it found nothing.
Silence was how an incident could reach the end of the graph still marked
`fixing`, which is a status nothing was working on.
"""

type NodeResult = dict[str, Any]

DONT_CARE_ALERT = Alert(service="kuki", alert_name="HighErrorRate")
DONT_CARE_INCIDENT_ID = "buki-123"


@pytest.mark.unit
def test_the_stub_reports_that_no_fix_was_found() -> None:
    Scenario() \
        .given(an_incident_being_fixed := _an_incident_in(IncidentStatus.FIXING)) \
        .when(lambda: codefix_node(an_incident_being_fixed)) \
        .then(all_of(_the_updates_carry("fix_found", False),
                     _the_work_was_narrated()))


@pytest.mark.unit
def test_route_after_codefix_resolves_only_when_resolved() -> None:
    Scenario() \
        .given(a_fixed_incident := _an_incident_in(IncidentStatus.RESOLVED)) \
        .when(lambda: route_after_codefix(a_fixed_incident)) \
        .then(_the_route_is(RESOLVED_ROUTE))


@pytest.mark.unit
def test_route_after_codefix_escalates_an_incident_it_could_not_fix() -> None:
    Scenario() \
        .given(an_unfixed_incident := _an_incident_in(IncidentStatus.FIXING)) \
        .when(lambda: route_after_codefix(an_unfixed_incident)) \
        .then(_the_route_is(ESCALATED_ROUTE))


def _an_incident_in(status: IncidentStatus) -> IncidentState:
    return IncidentState(incident_id=DONT_CARE_INCIDENT_ID,
                         alert=DONT_CARE_ALERT,
                         status=status)


def _the_updates_carry(field: str, expected: Any) -> Assertion[NodeResult]:
    def assertion(updates: NodeResult) -> bool:
        if field not in updates:
            raise AssertionError(
                f"expected the updates to carry [{field}], they carry {sorted(updates)}"
            )

        if updates[field] != expected:
            raise AssertionError(
                f"expected [{field}] to be [{expected}], it was [{updates[field]}]"
            )

        return True

    return assertion


def _the_work_was_narrated() -> Assertion[NodeResult]:
    """Something was said, not what. A node that moves the incident and says
    nothing raises in `with_status`, and the words themselves are not a promise
    to anybody."""
    def assertion(updates: NodeResult) -> bool:
        if not isinstance(updates.get("narration"), Narration):
            raise AssertionError(
                f"expected the node to narrate what it did, it returned "
                f"{updates.get('narration')!r}"
            )

        return True

    return assertion


def _the_route_is(expected: str) -> Assertion[str]:
    def assertion(route: str) -> bool:
        if route != expected:
            raise AssertionError(f"expected the route [{expected}], got [{route}]")

        return True

    return assertion
