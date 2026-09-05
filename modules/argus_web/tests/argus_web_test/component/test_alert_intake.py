from __future__ import annotations

from typing import Any

import pytest
from argus_core.db import connect
from argus_core.models.incident_status import IncidentStatus
from argus_testkit import Assertion, Scenario, all_of
from argus_web.app import app
from fastapi.testclient import TestClient
from orchestrator.repository import incidents, runs, timeline

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
    some_payload = _a_grafana_payload(service="kuki-service")

    with TestClient(app) as client:
        Scenario() \
            .when(
                client.post("/webhooks/alerts", json=some_payload)
            ) \
            .then(all_of(
                _the_incident_is_acknowledged(),
                _the_timeline_says_only_that_it_was_acknowledged(),
            ))


@pytest.mark.component
def test_the_alert_is_answered_with_an_incident_that_has_not_been_walked() -> None:
    # The whole point of the handoff: the answer comes back while the
    # investigation has not started, so the connection that delivered the alert
    # is not what a run depends on. Proven by what the incident looks like at
    # the moment of the answer - one timeline event, a queued run - because a
    # graph that had run would have left more of both.
    some_service = "kuki-service"
    some_payload = _a_grafana_payload(service=some_service)

    with TestClient(app) as client:
        Scenario() \
            .when(
                client.post("/webhooks/alerts", json=some_payload)
            ) \
            .then(all_of(
                _the_alert_was_accepted(),
                _an_incident_was_created_for(some_service),
                _a_run_is_queued_for_it(),
                _the_graph_has_not_walked_it(),
            ))


def _the_incident_is_acknowledged() -> Assertion[Any]:
    def assertion(response: Any) -> bool:
        with connect() as conn:
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
def _the_timeline_says_only_that_it_was_acknowledged() -> Assertion[Any]:
    def assertion(response: Any) -> bool:
        with connect() as conn:
            events = timeline.get_timeline_events(
                conn, response.json()["incident_id"])

        recorded = [event.to_status for event in events]

        if recorded != [IncidentStatus.ACKNOWLEDGED]:
            raise AssertionError(
                f"Expected the timeline of a queued incident to record only "
                f"[{IncidentStatus.ACKNOWLEDGED}], got {recorded}."
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
        with connect() as conn:
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
        with connect() as conn:
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
        with connect() as conn:
            events = timeline.get_timeline_events(
                conn, response.json()["incident_id"])

        if len(events) != 1:
            raise AssertionError(
                f"Expected the answer to come back before the graph walked "
                f"anything - one timeline event, the incident's creation - got "
                f"{[event.action for event in events]}."
            )

        return True

    return assertion


def _a_grafana_payload(service: str = "kukibuki",
                       alert_name: str = "HighErrorRate") -> dict[str, Any]:
    return {
        "receiver": "argus-webhook",
        "status": "firing",
        "alerts": [
            {
                "status": "firing",
                "labels": {
                    "alertname": alert_name,
                    "service": service,
                    "severity": "critical",
                },
                "annotations": {"summary": f"Error rate above threshold on {service}"},
                "startsAt": "2026-08-14T10:15:00Z",
                "endsAt": "0001-01-01T00:00:00Z",
            }
        ],
    }
