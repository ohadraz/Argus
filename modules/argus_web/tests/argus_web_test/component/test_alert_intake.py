from __future__ import annotations

from typing import Any

import pytest
from argus_core import connect_from_env
from argus_core.models import IncidentStatus
from argus_incidents.repository import events, incidents, runs
from argus_testkit import Assertion, Scenario, all_of
from argus_web.app import app
from fastapi.testclient import TestClient

from argus_web_test.framework.builders import a_grafana_payload

# The state a run is in when nothing has picked it up yet. Named from the
# repository's own vocabulary rather than spelled out here, so a rename moves
# this with it.
QUEUED = runs.RunState.QUEUED


@pytest.mark.component
def test_an_accepted_alert_is_acknowledged_before_anyone_is_on_it() -> None:
    # The status is the incident's, not the graph's: Argus has the alert and
    # has committed to handling it, and nothing is investigating until a worker
    # takes the run. Saying `investigating` here would be claiming attention
    # that a queued incident does not have - and that a worker outage would
    # never correct.
    some_payload = a_grafana_payload(service="kuki-service")

    with TestClient(app) as client:
        Scenario() \
            .when(
                lambda: client.post("/webhooks/alerts", json=some_payload)
            ) \
            .then(all_of(
                _the_incident_is_acknowledged(),
                _the_account_says_only_that_the_alert_arrived(),
            ))


@pytest.mark.component
def test_the_alert_is_answered_with_an_incident_that_has_not_been_walked() -> None:
    # The whole point of the handoff: the answer comes back while the
    # investigation has not started, so the connection that delivered the alert
    # is not what a run depends on. Proven by what the incident looks like at
    # the moment of the answer - one line of account, a queued run - because a
    # graph that had run would have left more of both.
    some_service = "kuki-service"
    some_payload = a_grafana_payload(service=some_service)

    with TestClient(app) as client:
        Scenario() \
            .when(
                lambda: client.post("/webhooks/alerts", json=some_payload)
            ) \
            .then(all_of(
                _the_alert_was_accepted(),
                _an_incident_was_created_for(some_service),
                _a_run_is_queued_for_it(),
                _the_graph_has_not_walked_it(),
            ))


@pytest.mark.component
def test_a_resolved_alert_opens_no_incident() -> None:
    # Grafana sends one when a rule stops firing. It is news about an incident
    # that may already be open, never the start of one - and whether a rule has
    # stopped firing is read from the rule, not from this.
    some_service = "kuki-resolved-only"
    a_resolution = a_grafana_payload(
        service=some_service, rule_uid="some-rule-that-resolved", status="resolved"
    )

    with TestClient(app) as client:
        Scenario() \
            .when(
                lambda: client.post("/webhooks/alerts", json=a_resolution)
            ) \
            .then(all_of(
                _it_was_answered_without_an_incident(),
                _no_incident_is_open_for(some_service),
            ))


@pytest.mark.component
def test_a_rule_firing_again_joins_the_incident_it_opened() -> None:
    # The rule resolved and fired again while Argus was still on it - which is
    # the incident going on, not a second one beside it.
    some_rule = "some-rule-firing-twice"
    some_service = "kuki-fires-twice"
    an_alert = a_grafana_payload(service=some_service, rule_uid=some_rule)

    with TestClient(app) as client:
        Scenario() \
            .given(
                first := client.post("/webhooks/alerts", json=an_alert)
            ) \
            .when(
                lambda: client.post("/webhooks/alerts", json=an_alert)
            ) \
            .then(all_of(
                _it_was_answered_with(first.json()["incident_id"]),
                _incidents_were_opened_for(some_service, count=1),
            ))


def _the_incident_is_acknowledged() -> Assertion[Any]:
    def assertion(response: Any) -> bool:
        with connect_from_env() as conn:
            incident = incidents.get(conn, response.json()["incident_id"])

        if incident is None:
            raise AssertionError(
                "Expected the answered id to name an incident, found none."
            )

        if incident.status != IncidentStatus.ACKNOWLEDGED:
            raise AssertionError(
                f"Expected an accepted alert to leave the incident "
                f"[{IncidentStatus.ACKNOWLEDGED}], got [{incident.status}]."
            )

        return True

    return assertion


def _the_account_says_only_that_the_alert_arrived() -> Assertion[Any]:
    """One line, and it is the alert being received.

    Acknowledging is an event rather than a status - it adds nowhere for the
    incident to go - so a queued incident's whole account is that first line,
    and any transition at all would mean the graph had already run.
    """
    def assertion(response: Any) -> bool:
        with connect_from_env() as conn:
            recorded = events.get_by_incident(conn, response.json()["incident_id"])

        said = [event.kind for event in recorded]

        if said != ["alert-acknowledged"]:
            raise AssertionError(
                f"Expected the account of a queued incident to be the alert "
                f"arriving and nothing else, got {said}."
            )

        return True

    return assertion


def _the_alert_was_accepted() -> Assertion[Any]:
    def assertion(response: Any) -> bool:
        if response.status_code != 202:
            raise AssertionError(
                f"Expected the alert to be accepted with [202], got "
                f"[{response.status_code}]: {response.text}"
            )

        if not response.json().get("incident_id"):
            raise AssertionError(
                f"Expected the answer to carry the incident's id, got "
                f"{response.json()}."
            )

        return True

    return assertion


def _an_incident_was_created_for(service: str) -> Assertion[Any]:
    def assertion(response: Any) -> bool:
        with connect_from_env() as conn:
            incident = incidents.get(conn, response.json()["incident_id"])

        if incident is None:
            raise AssertionError(
                "Expected the answered id to name an incident, found none."
            )

        if incident.alert_payload.get("service") != service:
            raise AssertionError(
                f"Expected the incident to be for [{service}], got "
                f"[{incident.alert_payload.get('service')}]."
            )

        return True

    return assertion


def _a_run_is_queued_for_it() -> Assertion[Any]:
    def assertion(response: Any) -> bool:
        with connect_from_env() as conn:
            run = runs.get_run_for_incident(
                conn, response.json()["incident_id"])

        if run is None:
            raise AssertionError(
                "Expected the alert to leave a run for a worker to take, "
                "found none."
            )

        if run.state != QUEUED:
            raise AssertionError(
                f"Expected the run to be waiting to be taken [{QUEUED}], got "
                f"[{run.state}]."
            )

        return True

    return assertion


def _the_graph_has_not_walked_it() -> Assertion[Any]:
    def assertion(response: Any) -> bool:
        with connect_from_env() as conn:
            recorded = events.get_by_incident(conn, response.json()["incident_id"])

        if len(recorded) != 1:
            raise AssertionError(
                f"Expected the answer to come back before the graph walked "
                f"anything - one line, the alert arriving - got "
                f"{[event.kind for event in recorded]}."
            )

        return True

    return assertion


def _it_was_answered_without_an_incident() -> Assertion[Any]:
    def assertion(response: Any) -> bool:
        if response.status_code != 202 or response.json() != {"incident_id": None}:
            raise AssertionError(
                f"Expected a resolved alert to be accepted with no incident, got "
                f"[{response.status_code}] {response.json()}."
            )

        return True

    return assertion


def _it_was_answered_with(incident_id: str) -> Assertion[Any]:
    def assertion(response: Any) -> bool:
        answered = response.json().get("incident_id")

        if answered != incident_id:
            raise AssertionError(
                f"Expected the alert to be answered with the open incident "
                f"[{incident_id}], got [{answered}]."
            )

        return True

    return assertion


def _incidents_were_opened_for(service: str, count: int) -> Assertion[Any]:
    def assertion(_: Any) -> bool:
        with connect_from_env() as conn:
            opened = [
                incident
                for incident in incidents.get_recent(conn)
                if incident.alert_payload.get("service") == service
            ]

        if len(opened) != count:
            raise AssertionError(
                f"Expected [{count}] incidents for [{service}], got [{len(opened)}]."
            )

        return True

    return assertion


def _no_incident_is_open_for(service: str) -> Assertion[Any]:
    return _incidents_were_opened_for(service, count=0)
