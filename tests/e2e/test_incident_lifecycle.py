from __future__ import annotations

from collections.abc import Callable
from http import HTTPStatus as HttpStatus
from typing import Any

import httpx
import psycopg
import pytest
from argus_testkit import Assertion, Scenario, all_of, eventually
from orchestrator.repository import incidents, postmortems, timeline

from tests.e2e.framework.builders import a_grafana_style_alert_with

ARGUS_WEB_BASE_URL = "http://localhost:8000"
DATABASE_URL = "postgresql://argus:argus@localhost:5432/argus"

WEBHOOK_PATH = "/webhooks/alerts"


@pytest.mark.e2e
def test_firing_alert_with_no_cause_to_find_escalates_with_a_postmortem() -> None:
    # No scenario is seeded, so there is nothing in the logs to explain the
    # alert. Argus must say so and escalate - not resolve an incident it never
    # diagnosed. This is the honest-failure path (spec §9); before the ReAct
    # change the Investigator returned a fabricated hypothesis at a fixed 0.9
    # here, and this test asserted the resolve that followed from it.
    some_service = "kuki-service"
    some_alert_name = "HighErrorRate"
    some_severity = "critical"
    some_alert = a_grafana_style_alert_with(service=some_service,
                                            alert_name=some_alert_name,
                                            severity=some_severity)

    Scenario() \
        .when(
            _argus_is_triggered_with_alert(some_alert)
        ) \
        .then(all_of(
            _argus_returns_status(HttpStatus.ACCEPTED),
            eventually(
                all_of(
                    _argus_registered_an_incident_for_the_alert(some_alert),
                    _argus_went_through_statuses(
                        "investigating",
                        "escalated",
                    ),
                    _argus_ended_with_status("escalated"),
                    _argus_created_a_postmortem_for_the_incident(),
                )
            )
        ))


def _incident_id_from(response: httpx.Response) -> str | None:
    return response.json().get("incident_id")

def _argus_registered_an_incident_for_the_alert(
    alert_payload: dict[str, Any]
) -> Assertion[httpx.Response]:
    def assertion(response: httpx.Response) -> bool:
        incident_id = _incident_id_from(response)

        if not incident_id:
            raise AssertionError("no incident_id in response")

        alert = alert_payload["alerts"][0]

        with psycopg.connect(DATABASE_URL) as conn:
            incident = incidents.get(conn, incident_id)

            if incident is None:
                raise AssertionError(f"no incident found with id [{incident_id}].")

            alert_in_db = incident.alert_payload
            expected_service = alert["labels"]["service"]
            actual_service = alert_in_db['service']
            expected_alertname = alert["labels"]["alertname"]
            actual_alertname = alert_in_db['alert_name']

            if actual_service != expected_service:
                raise AssertionError(
                    f"Expected service [{expected_service!r}], got [{actual_service!r}].")

            if actual_alertname != expected_alertname:
                raise AssertionError(
                    f"Expected alert_name [{expected_alertname!r}], got [{actual_alertname!r}].")

            if "labels" in alert_in_db:
                raise AssertionError(
                    f"Expected alert_payload to not leak Grafana's raw 'labels' "
                    f"nesting: [{alert_in_db!r}].")

            return True

    return assertion

def _argus_went_through_statuses(*expected: str) -> Assertion[httpx.Response]:
    def assertion(response: httpx.Response) -> bool:
        incident_id = _incident_id_from(response)

        if not incident_id:
            raise AssertionError("no incident_id in response")

        with psycopg.connect(DATABASE_URL) as conn:
            events = timeline.get_timeline_events(conn, incident_id)

        actual = [event.to_status for event in events]

        if actual != list(expected):
            raise AssertionError(
                f"expected status transitions {list(expected)}, "
                f"got {actual}"
            )

        return True

    return assertion


def _argus_ended_with_status(expected_status: str) -> Assertion[httpx.Response]:
    def assertion(response: httpx.Response) -> bool:
        incident_id = _incident_id_from(response)

        if not incident_id:
            raise AssertionError("no incident_id in response.")

        with psycopg.connect(DATABASE_URL) as conn:
            incident = incidents.get(conn, incident_id)

            if incident is None:
                raise AssertionError(f"No incident found with id [{incident_id}].")
            if incident.status != expected_status:
                raise AssertionError(
                    f"Expected incident [{incident_id}] to be {expected_status}, "
                    f"but got status [{incident.status}]."
                )

            return True

    return assertion


def _argus_created_a_postmortem_for_the_incident() -> Assertion[httpx.Response]:
    def assertion(response: httpx.Response) -> bool:
        incident_id = _incident_id_from(response)

        if not incident_id:
            raise AssertionError("no incident_id in response")

        with psycopg.connect(DATABASE_URL) as conn:
            if postmortems.get_by_incident(conn, incident_id) is None:
                raise AssertionError(
                    f"no postmortem exists for incident {incident_id}"
                )

        return True

    return assertion

def _argus_is_triggered_with_alert(payload: dict[str, Any]) -> Callable[[], httpx.Response]:
    def step() -> httpx.Response:
        return httpx.post(
            f"{ARGUS_WEB_BASE_URL}{WEBHOOK_PATH}",
            json=payload,
            timeout=10.0,
        )

    return step


def _argus_returns_status(expected_status: int | HttpStatus) -> Callable[[httpx.Response], bool]:
    def assertion(response: httpx.Response) -> bool:
        if response.status_code != expected_status:
            raise AssertionError(
                f"Expected status [{expected_status}], but got [{response.status_code}]."
            )

        return True

    return assertion
