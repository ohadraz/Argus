from __future__ import annotations

from collections.abc import Callable
from http import HTTPStatus as HttpStatus
from typing import Any

import httpx
import psycopg
from argus_core.config import get_settings
from argus_core.models.incident_status import IncidentStatus
from argus_testkit import Assertion, all_of
from orchestrator.repository import hypotheses, incidents, postmortems, timeline

"""Talking to a running Argus stack, and asserting on what it did.

Shared by every e2e test rather than restated in each: an assertion about
"the incident this webhook call created" is the same assertion whichever
scenario is driving it, and two copies drift the moment one is fixed.

Everything here takes the webhook's `httpx.Response`, because that is what a
`Scenario`'s `when` produces and the only handle a test has on the incident
Argus created for it.
"""

ARGUS_WEB_BASE_URL = "http://localhost:8000"
TARGET_SERVICE_BASE_URL = "http://localhost:8080"
DATABASE_URL = "postgresql://argus:argus@localhost:5432/argus"
ANTHROPIC_DOUBLE_BASE_URL = "http://localhost:8091"

WEBHOOK_PATH = "/webhooks/alerts"

# A real investigation is up to `investigation_max_iterations` model calls,
# each one adaptive thinking at high effort. Argus answers in seconds when it
# is confident on the first pass; this bound is what "the loop ran out of
# iterations" looks like in wall-clock time, not the expected duration.
A_GENEROUS_MODEL_CALL_SECONDS = 90
AN_INVESTIGATION_TIMEOUT_SECONDS = (
    get_settings().investigation_max_iterations * A_GENEROUS_MODEL_CALL_SECONDS
)


def argus_is_triggered_with_alert(
    payload: dict[str, Any]
) -> Callable[[], httpx.Response]:
    """Fires the alert, and waits for the investigation it starts.

    The wait is the whole investigation, not a round trip: the webhook runs the
    graph in-process and answers only once it has finished. So this call is
    bounded by the same budget the `then` clauses wait on - one that against a
    replayed model is never approached, and against a real one is the
    difference between a slow answer and a failed run.
    """
    def step() -> httpx.Response:
        return httpx.post(
            f"{ARGUS_WEB_BASE_URL}{WEBHOOK_PATH}",
            json=payload,
            timeout=AN_INVESTIGATION_TIMEOUT_SECONDS,
        )

    return step


def incident_id_from(response: httpx.Response) -> str:
    incident_id = response.json().get("incident_id")

    if not incident_id:
        raise AssertionError(f"No incident_id in response: [{response.text}].")

    return str(incident_id)


def argus_returns_status(expected_status: int | HttpStatus) -> Assertion[httpx.Response]:
    def assertion(response: httpx.Response) -> bool:
        if response.status_code != expected_status:
            raise AssertionError(
                f"Expected status [{expected_status}], but got [{response.status_code}]."
            )

        return True

    return assertion


def about_the_hypothesis(
    *hypothesis_assertions: Assertion[Any]
) -> Assertion[httpx.Response]:
    """Adapts assertions about a `Hypothesis` to the webhook response a
    scenario ends with, so the domain assertions in `tests/framework` stay
    shared with the eval and integration tiers rather than being restated
    against a database row here.
    """
    def assertion(response: httpx.Response) -> bool:
        incident_id = incident_id_from(response)

        with psycopg.connect(DATABASE_URL) as conn:
            hypothesis = hypotheses.get_latest_by_incident(conn, incident_id)

        if hypothesis is None:
            raise AssertionError(f"No hypothesis found for incident [{incident_id}].")

        return all_of(*hypothesis_assertions)(hypothesis)

    return assertion


def argus_ended_with_status(expected_status: IncidentStatus) -> Assertion[httpx.Response]:
    def assertion(response: httpx.Response) -> bool:
        incident_id = incident_id_from(response)

        with psycopg.connect(DATABASE_URL) as conn:
            incident = incidents.get(conn, incident_id)

        if incident is None:
            raise AssertionError(f"No incident found with id [{incident_id}].")

        if incident.status != expected_status:
            raise AssertionError(
                f"Expected incident [{incident_id}] to be [{expected_status}], "
                f"got [{incident.status}]."
            )

        return True

    return assertion


def argus_went_through_statuses(*expected: IncidentStatus) -> Assertion[httpx.Response]:
    def assertion(response: httpx.Response) -> bool:
        incident_id = incident_id_from(response)

        with psycopg.connect(DATABASE_URL) as conn:
            events = timeline.get_timeline_events(conn, incident_id)

        actual = [event.to_status for event in events]

        if actual != list(expected):
            raise AssertionError(
                f"Expected status transitions {[str(status) for status in expected]}, "
                f"got {actual}."
            )

        return True

    return assertion


def argus_registered_an_incident_for_the_alert(
    alert_payload: dict[str, Any]
) -> Assertion[httpx.Response]:
    """The alert reached the database in Argus's own shape.

    The absent `labels` key is the point: a vendor's nesting must not survive
    past the webhook adapter (spec §7.9, §25).
    """
    def assertion(response: httpx.Response) -> bool:
        incident_id = incident_id_from(response)
        alert = alert_payload["alerts"][0]

        with psycopg.connect(DATABASE_URL) as conn:
            incident = incidents.get(conn, incident_id)

        if incident is None:
            raise AssertionError(f"No incident found with id [{incident_id}].")

        alert_in_db = incident.alert_payload
        expected_service = alert["labels"]["service"]
        actual_service = alert_in_db["service"]
        expected_alert_name = alert["labels"]["alertname"]
        actual_alert_name = alert_in_db["alert_name"]

        if actual_service != expected_service:
            raise AssertionError(
                f"Expected service [{expected_service!r}], got [{actual_service!r}]."
            )

        if actual_alert_name != expected_alert_name:
            raise AssertionError(
                f"Expected alert_name [{expected_alert_name!r}], got [{actual_alert_name!r}]."
            )

        if "labels" in alert_in_db:
            raise AssertionError(
                f"Expected alert_payload to not leak Grafana's raw 'labels' "
                f"nesting: [{alert_in_db!r}]."
            )

        return True

    return assertion


def argus_created_a_postmortem_for_the_incident() -> Assertion[httpx.Response]:
    def assertion(response: httpx.Response) -> bool:
        incident_id = incident_id_from(response)

        with psycopg.connect(DATABASE_URL) as conn:
            if postmortems.get_by_incident(conn, incident_id) is None:
                raise AssertionError(
                    f"No postmortem exists for incident [{incident_id}]."
                )

        return True

    return assertion


def the_model_answers_from(recording: str) -> Callable[[], bool]:
    """A `given` step naming the stored answer the model gives for this case.

    The counterpart to seeding the Target Service's scenario: one says what the
    service did, the other says what the model said about it. Both are
    stand-ins, so both are arranged in the test rather than one being supplied
    invisibly by a fixture - and a case wanting a mismatched pair (a deploy
    scenario the model finds nothing in) can write one.

    Resets first, because a seed from an earlier case answers until it is
    cleared, and a test whose verdict came from the previous test's recording
    is worse than a failing one.

    `repeat: null` - answer every call until reset - rather than a count,
    because the investigation loop asks the model between one and
    `investigation_max_iterations` times depending on what it retrieved. A
    count here would couple every e2e case to the current iteration budget.
    How many times the model was asked is asserted in the Investigator's own
    unit tests, where it is free.

    Against `nox -s e2e` this seeds a double nothing is pointed at, and is
    harmlessly ignored - which is what lets one set of cases serve both the
    paid path and the replayed one.
    """
    def step() -> bool:
        with httpx.Client(base_url=ANTHROPIC_DOUBLE_BASE_URL, timeout=10.0) as control:
            control.post("/double-control/reset").raise_for_status()
            response = control.post(
                "/double-control/seed",
                json={"recording": recording, "repeat": None},
            )

        return response.status_code == HttpStatus.OK

    return step
