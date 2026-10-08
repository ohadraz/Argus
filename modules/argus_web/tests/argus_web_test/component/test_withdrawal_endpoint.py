"""The button that stops Argus, from the outside.

`argus_web` decides nothing here. It names the incident and reports what the
Orchestrator answered - which is the same arrangement as the alert webhook, and
for the same reason: whether a withdrawal is permitted is a fact about the
incident, and the incident does not live in the web process.
"""

from __future__ import annotations

import logging
from http import HTTPStatus as HttpStatus

import httpx2
import pytest
from argus_core import connect_from_env
from argus_core.models import Alert, IncidentStatus
from argus_core.telemetry import ARGUS_INCIDENT_ID
from argus_incidents.repository import incidents
from argus_testkit import Assertion, Scenario, all_of, calling, one_record_was_logged
from argus_web.app import app
from fastapi.testclient import TestClient
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from argus_web_test.framework.assertions import the_response_was
from argus_web_test.framework.observing import observing_the_app, the_span_named

# The context an incident kept from the span its alert was received in, as the
# propagator wrote it: a trace, and the span within it.
SOME_TRACE = "4bf92f3577b34da6a3ce929d0e0e4736"
SOME_SPAN = "00f067aa0ba902b7"
SOME_TRACE_CONTEXT = {"traceparent": f"00-{SOME_TRACE}-{SOME_SPAN}-01"}


@pytest.mark.component
def test_withdrawing_a_running_incident_stops_it() -> None:
    some_alert = Alert(service="kuki-service", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)

    with TestClient(app) as client:
        Scenario() \
            .given(
                incident_id
            ) \
            .when(
                lambda: client.post(f"/incidents/{incident_id}/withdraw")
            ) \
            .then(all_of(
                the_response_was(HttpStatus.OK),
                _the_incident_is(incident_id, IncidentStatus.WITHDRAWN)
            ))


@pytest.mark.component
def test_withdrawing_an_incident_that_already_ended_is_refused() -> None:
    # Refused rather than ignored. An incident that resolved was resolved by a
    # mitigation holding the service up, and a page that answered "done" to
    # this would have somebody believe they had stopped something.
    some_alert = Alert(service="buki-service", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)
        incidents.transition(
            conn,
            incident_id,
            IncidentStatus.RESOLVED
        )

    with TestClient(app) as client:
        Scenario() \
            .given(
                incident_id
            ) \
            .when(
                lambda: client.post(f"/incidents/{incident_id}/withdraw")
            ) \
            .then(all_of(
                the_response_was(HttpStatus.CONFLICT),
                _the_incident_is(incident_id, IncidentStatus.RESOLVED)
            ))


@pytest.mark.component
def test_withdrawing_an_incident_nobody_has_is_not_found() -> None:
    some_id_that_never_existed = "00000000-0000-0000-0000-000000000000"

    with TestClient(app) as client:
        Scenario() \
            .when(
                lambda: client.post(f"/incidents/{some_id_that_never_existed}/withdraw")
            ) \
            .then(
                the_response_was(HttpStatus.NOT_FOUND)
            )


@pytest.mark.component
def test_a_withdrawal_continues_the_incidents_trace() -> None:
    # A person stopping the response is part of the incident's story, so it is
    # part of the incident's trace - read beside the walk it interrupted.
    some_alert = Alert(service="kuki-traced-withdrawal", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert, trace_context=SOME_TRACE_CONTEXT)

    with observing_the_app() as spans, TestClient(app) as client:
        Scenario() \
            .given(
                incident_id
            ) \
            .when(
                lambda: client.post(f"/incidents/{incident_id}/withdraw")
            ) \
            .then(
                _it_was_withdrawn_inside_the_trace_it_kept(spans, incident_id)
            )


@pytest.mark.component
def test_a_withdrawal_refused_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    # Somebody pressed the button and nothing stopped. The page tells them;
    # the log is where whoever they ask next finds that it happened.
    some_alert = Alert(service="kuki-refused-withdrawal", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)
        incidents.transition(conn, incident_id, IncidentStatus.RESOLVED)

    with TestClient(app) as client:
        Scenario() \
            .given(
                calling(lambda: caplog.set_level(logging.INFO))
            ) \
            .when(
                lambda: client.post(f"/incidents/{incident_id}/withdraw")
            ) \
            .then(
                one_record_was_logged(caplog, "argus_web.app", logging.INFO,
                                      "withdrawal refused")
            )


def _the_incident_is(incident_id: str,
                     status: IncidentStatus) -> Assertion[httpx2.Response]:
    def assertion(_response: httpx2.Response) -> bool:
        with connect_from_env() as conn:
            incident = incidents.get(conn, incident_id)

        if incident is None:
            raise AssertionError(f"No incident found with id [{incident_id}].")

        if incident.status != status:
            raise AssertionError(
                f"Expected status [{status!r}], got [{incident.status!r}]."
            )

        return True

    return assertion


def _it_was_withdrawn_inside_the_trace_it_kept(
    spans: InMemorySpanExporter, incident_id: str
) -> Assertion[httpx2.Response]:
    def assertion(_response: httpx2.Response) -> bool:
        withdrawn = the_span_named(spans, "withdraw incident")
        parent = withdrawn.parent
        continued = (f"{parent.trace_id:032x}", f"{parent.span_id:016x}") if parent else None
        named = (withdrawn.attributes or {}).get(ARGUS_INCIDENT_ID)

        if continued != (SOME_TRACE, SOME_SPAN) or named != incident_id:
            raise AssertionError(
                f"Expected the withdrawal's span to continue the trace the incident "
                f"kept, [{SOME_TRACE}/{SOME_SPAN}], and to name [{incident_id}]; it "
                f"continued [{continued}] and named [{named}]."
            )

        return True

    return assertion
