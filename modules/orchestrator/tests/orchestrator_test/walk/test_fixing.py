"""Looking for a permanent fix, and reporting what came back.

Code-Fix is still a stub that offers nothing, so most of what happens here is
an incident admitting there is no fix and going to a human. What is asserted is
the reporting rather than the stub: the node says what the agent answered, so
that the day the agent answers something the graph carries it - rather than
going on reporting no fix while the agent quietly proposes one.

Silence is the other failure, and the older one: an incident that reached here
and said nothing ended the graph still marked `fixing`, which is a status
nothing was working on.
"""

from __future__ import annotations

from typing import Any

import pytest
from argus_core.models import Alert, Hypothesis, IncidentStatus
from argus_testkit import Assertion, Scenario, all_of
from orchestrator.walk.deltas import Narration, StateDelta
from orchestrator.walk.fixing import codefix_node, route_after_codefix
from orchestrator.walk.ports import ProposeFix
from orchestrator.walk.routes import ESCALATED_ROUTE, RESOLVED_ROUTE
from orchestrator.walk.state import IncidentState

from orchestrator_test.framework.builders import a_determined_hypothesis

DONT_CARE_ALERT = Alert(service="kuki", alert_name="HighErrorRate")
DONT_CARE_INCIDENT_ID = "buki-123"


@pytest.mark.unit
def test_an_agent_with_no_fix_to_offer_is_reported_as_finding_none() -> None:
    # The only answer today's stub gives, and a real one: no fix found is what
    # carries the incident on to a human.
    Scenario() \
        .given(
            an_incident_being_fixed := _an_incident_in(IncidentStatus.FIXING),
            an_agent_with_nothing := _an_agent_offering(None)
        ) \
        .when(
            lambda: codefix_node(an_incident_being_fixed, an_agent_with_nothing)
        ) \
        .then(all_of(
            _the_updates_carry("fix_found", False),
            _the_work_was_narrated()
        ))


@pytest.mark.unit
def test_a_fix_the_agent_proposed_is_reported_as_found() -> None:
    # The answer nothing could give before: the node called Code-Fix and threw
    # the reply away, so an agent that proposed a fix would have had the graph
    # report no fix and escalate - a failure that would read as an agent bug
    # rather than as a node that never listened.
    Scenario() \
        .given(
            an_incident_being_fixed := _an_incident_in(IncidentStatus.FIXING),
            an_agent_with_a_fix := _an_agent_offering("widen the retry window")
        ) \
        .when(
            lambda: codefix_node(an_incident_being_fixed, an_agent_with_a_fix)
        ) \
        .then(all_of(
            _the_updates_carry("fix_found", True),
            _the_work_was_narrated()
        ))


@pytest.mark.unit
def test_the_agent_is_asked_about_the_hypothesis_the_walk_reached() -> None:
    # The one thing Code-Fix is told, and the only reason it can do anything at
    # all. An incident asked about the wrong thing would answer honestly about
    # something that never happened.
    a_hypothesis = a_determined_hypothesis(DONT_CARE_INCIDENT_ID)

    Scenario() \
        .given(
            an_incident_with_a_hypothesis := _an_incident_in(
                IncidentStatus.FIXING, hypothesis=a_hypothesis
            ),
            the_agent := _AnAgentRememberingWhatItWasAsked()
        ) \
        .when(
            lambda: codefix_node(an_incident_with_a_hypothesis, the_agent.propose)
        ) \
        .then(
            _the_agent_was_asked_about(the_agent, a_hypothesis.summary)
        )


@pytest.mark.unit
def test_an_incident_with_no_hypothesis_is_still_asked_about() -> None:
    # A walk can reach here having concluded nothing. Code-Fix is asked anyway,
    # about nothing, because "I looked and found nothing" and "I never looked"
    # reach the same human and only one of them would be true.
    Scenario() \
        .given(
            an_incident_that_concluded_nothing := _an_incident_in(IncidentStatus.FIXING),
            the_agent := _AnAgentRememberingWhatItWasAsked()
        ) \
        .when(
            lambda: codefix_node(an_incident_that_concluded_nothing, the_agent.propose)
        ) \
        .then(
            _the_agent_was_asked_about(the_agent, "")
        )


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


class _AnAgentRememberingWhatItWasAsked:
    """Code-Fix as a seam, holding on to the one thing it was told.

    A small class rather than `create_autospec`, because the test reads the
    question back afterwards and a named attribute says what is being read more
    plainly than a call record does.
    """

    def __init__(self) -> None:
        self.hypothesis: str | None = None

    def propose(self, hypothesis: str) -> str | None:
        self.hypothesis = hypothesis

        return None


def _an_agent_offering(fix: str | None) -> ProposeFix:
    """Code-Fix, answering the same thing however it is asked."""
    def propose(dont_care_hypothesis: str) -> str | None:
        return fix

    return propose


def _an_incident_in(status: IncidentStatus,
                    hypothesis: Hypothesis | None = None) -> IncidentState:
    return IncidentState(incident_id=DONT_CARE_INCIDENT_ID,
                         alert=DONT_CARE_ALERT,
                         status=status,
                         hypothesis=hypothesis)


def _the_agent_was_asked_about(
    agent: _AnAgentRememberingWhatItWasAsked, hypothesis: str
) -> Assertion[StateDelta]:
    def assertion(_updates: StateDelta) -> bool:
        if agent.hypothesis != hypothesis:
            raise AssertionError(
                f"Expected Code-Fix to be asked about [{hypothesis}], "
                f"it was asked about [{agent.hypothesis}]."
            )

        return True

    return assertion


def _the_updates_carry(field: str, expected: Any) -> Assertion[StateDelta]:
    def assertion(updates: StateDelta) -> bool:
        if field not in updates.model_fields_set:
            raise AssertionError(
                f"Expected the updates to carry [{field}], they carry "
                f"{sorted(updates.model_fields_set)}."
            )

        if getattr(updates, field) != expected:
            raise AssertionError(
                f"Expected [{field}] to be [{expected}], it was "
                f"[{getattr(updates, field)}]."
            )

        return True

    return assertion


def _the_work_was_narrated() -> Assertion[StateDelta]:
    """Something was said, not what. A node that moves the incident and says
    nothing raises in `with_status`, and the words themselves are not a promise
    to anybody."""
    def assertion(updates: StateDelta) -> bool:
        if not isinstance(updates.narration, Narration):
            raise AssertionError(
                f"Expected the node to narrate what it did, it returned "
                f"{updates.narration!r}."
            )

        return True

    return assertion


def _the_route_is(expected: str) -> Assertion[str]:
    def assertion(route: str) -> bool:
        if route != expected:
            raise AssertionError(f"Expected the route [{expected}], got [{route}].")

        return True

    return assertion
