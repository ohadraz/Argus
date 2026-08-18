from __future__ import annotations

from collections.abc import Callable
from http import HTTPStatus as HttpStatus
from typing import Any

import httpx
import psycopg
import pytest

from tests.e2e.framework.assertions import Assertion, eventually
from tests.e2e.framework.builders import a_grafana_style_alert_with
from tests.e2e.framework.scenario import Scenario

ARGUS_WEB_BASE_URL = "http://localhost:8000"
TARGET_SERVICE_BASE_URL = "http://localhost:8080"
DATABASE_URL = "postgresql://argus:argus@localhost:5432/argus"

WEBHOOK_PATH = "/webhooks/alerts"


@pytest.mark.e2e
def test_investigator_diagnoses_a_feature_flag_toggle_as_the_cause() -> None:
    some_service = "kukibuki-service"
    some_alert_name = "HighErrorRate"
    some_severity = "critical"
    expected_cause_type = "feature-flag-toggle"
    some_alert = a_grafana_style_alert_with(service=some_service,
                                            alert_name=some_alert_name,
                                            severity=some_severity)

    try:
        Scenario() \
            .given(
                _a_feature_flag_was_toggled_on()
            ) \
            .when(
                _argus_is_triggered_with_alert(some_alert)
            ) \
            .then(
                eventually(
                    _argus_diagnosed_the_cause_as(expected_cause_type)
                )
            )
    finally:
        _reset_target_service_scenario()


def _a_feature_flag_was_toggled_on() -> Callable[[], bool]:
    def toggle_feature_flag() -> bool:
        response = httpx.post(
            f"{TARGET_SERVICE_BASE_URL}/scenario/seed",
            json={"scenario_id": "feature-flag-toggle"},
            timeout=10.0,
        )

        return response.status_code == HttpStatus.OK

    return toggle_feature_flag


def _reset_target_service_scenario() -> None:
    httpx.post(f"{TARGET_SERVICE_BASE_URL}/scenario/reset", timeout=10.0)


def _incident_id_from(response: httpx.Response) -> str | None:
    return response.json().get("incident_id")


def _argus_diagnosed_the_cause_as(expected_cause_type: str) -> Assertion:
    def assertion(response: httpx.Response) -> bool:
        incident_id = _incident_id_from(response)

        if not incident_id:
            raise AssertionError("no incident_id in response")

        with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cursor:
            cursor.execute(
                "SELECT cause_type "
                "  FROM hypothesis "
                " WHERE incident_id = %s "
                "ORDER BY created_at "
                " LIMIT 1",
                (incident_id,)
            )

            row = cursor.fetchone()

            if row is None:
                raise AssertionError(f"no hypothesis found for incident [{incident_id}].")

            actual_cause_type = row[0]

            if actual_cause_type != expected_cause_type:
                raise AssertionError(
                    f"Expected cause_type [{expected_cause_type!r}], got [{actual_cause_type!r}]."
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
