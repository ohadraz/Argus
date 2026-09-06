from __future__ import annotations

from http import HTTPStatus as HttpStatus

import httpx
import pytest
from argus_core.db import connect
from argus_core.models.actor import Actor
from argus_core.models.alert import Alert
from argus_core.models.incident_status import IncidentStatus
from argus_testkit import Assertion, Scenario, all_of
from argus_web.app import app
from fastapi.testclient import TestClient
from orchestrator.repository import incidents

"""The button that stops Argus, from the outside.

`argus_web` decides nothing here. It names the incident and reports what the
Orchestrator answered - which is the same arrangement as the alert webhook, and
for the same reason: whether a withdrawal is permitted is a fact about the
incident, and the incident does not live in the web process.
"""


@pytest.mark.component
def test_withdrawing_a_running_incident_stops_it() -> None:
    some_alert = Alert(service="kuki-service", alert_name="HighErrorRate")

    with connect() as conn:
        incident_id = incidents.create(conn, some_alert)

    with TestClient(app) as client:
        Scenario() \
            .given(
                incident_id
            ) \
            .when(
                client.post(f"/incidents/{incident_id}/withdraw")
            ) \
            .then(all_of(
                _the_answer_was(HttpStatus.OK),
                _the_incident_is(incident_id, IncidentStatus.WITHDRAWN),
            ))


@pytest.mark.component
def test_withdrawing_an_incident_that_already_ended_is_refused() -> None:
    # Refused rather than ignored. An incident that resolved was resolved by a
    # mitigation holding the service up, and a page that answered "done" to
    # this would have somebody believe they had stopped something.
    some_alert = Alert(service="buki-service", alert_name="HighErrorRate")
    some_actor = Actor.MITIGATION

    with connect() as conn:
        incident_id = incidents.create(conn, some_alert)
        incidents.transition(
            conn,
            incident_id,
            IncidentStatus.RESOLVED,
            actor=some_actor,
            action="dont care",
        )

    with TestClient(app) as client:
        Scenario() \
            .given(
                incident_id
            ) \
            .when(
                client.post(f"/incidents/{incident_id}/withdraw")
            ) \
            .then(all_of(
                _the_answer_was(HttpStatus.CONFLICT),
                _the_incident_is(incident_id, IncidentStatus.RESOLVED),
            ))


@pytest.mark.component
def test_withdrawing_an_incident_nobody_has_is_not_found() -> None:
    some_id_that_never_existed = "00000000-0000-0000-0000-000000000000"

    with TestClient(app) as client:
        Scenario() \
            .when(
                client.post(f"/incidents/{some_id_that_never_existed}/withdraw")
            ) \
            .then(
                _the_answer_was(HttpStatus.NOT_FOUND)
            )


def _the_answer_was(expected: HttpStatus) -> Assertion[httpx.Response]:
    def assertion(response: httpx.Response) -> bool:
        if response.status_code != expected:
            raise AssertionError(
                f"Expected [{expected}], got [{response.status_code}]: "
                f"{response.text}."
            )

        return True

    return assertion


def _the_incident_is(incident_id: str,
                     status: IncidentStatus) -> Assertion[httpx.Response]:
    def assertion(_response: httpx.Response) -> bool:
        with connect() as conn:
            incident = incidents.get(conn, incident_id)

        if incident is None:
            raise AssertionError(f"No incident found with id [{incident_id}].")

        if incident.status != status:
            raise AssertionError(
                f"Expected status [{status!r}], got [{incident.status!r}]."
            )

        return True

    return assertion
