"""The control a person reports an incident over with, from the outside.

`argus_web` decides nothing here, as with the withdrawal beside it. It names the
incident, says who is asking and what they wrote, and reports what the
incident record answered - whether a resolution is accepted is a fact about the
incident, and the incident does not live in the web process.
"""

from __future__ import annotations

import logging
from http import HTTPStatus as HttpStatus

import httpx2
import pytest
from argus_core import connect_from_env
from argus_core.events import StatusChanged
from argus_core.models import Alert, IncidentStatus, Report, ReportChannel
from argus_core.telemetry import ARGUS_INCIDENT_ID
from argus_incidents.repository import events, incidents
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
def test_resolving_a_running_incident_resolves_it() -> None:
    some_alert = Alert(service="kuki-service", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)

    with TestClient(app) as client:
        Scenario() \
            .given(
                incident_id
            ) \
            .when(
                lambda: client.post(f"/incidents/{incident_id}/resolve")
            ) \
            .then(all_of(
                the_response_was(HttpStatus.OK),
                _the_incident_is(incident_id, IncidentStatus.RESOLVED)
            ))


@pytest.mark.component
def test_a_resolution_from_the_page_is_recorded_as_the_demo_users_with_their_note() -> None:
    # Argus has no users yet, so whoever pressed the button is the one person
    # the demo has. What they wrote travels with it: it is the only account of
    # why there is.
    some_alert = Alert(service="buki-service", alert_name="HighErrorRate")
    some_note = "rolled the flag back by hand"

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)

    with TestClient(app) as client:
        Scenario() \
            .given(
                incident_id
            ) \
            .when(
                lambda: client.post(f"/incidents/{incident_id}/resolve",
                                    data={"note": some_note})
            ) \
            .then(
                _the_account_says_it_was_reported_as(
                    incident_id,
                    Report(by="demo user", channel=ReportChannel.ARGUS_UI, note=some_note)
                )
            )


@pytest.mark.component
def test_a_resolution_with_a_blank_note_records_no_note() -> None:
    # The field is there whether or not anybody types in it. An empty box is a
    # person who said nothing, and recorded as an empty note it would print as
    # a dash with nothing after it.
    some_alert = Alert(service="muki-service", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)

    with TestClient(app) as client:
        Scenario() \
            .given(
                incident_id
            ) \
            .when(
                lambda: client.post(f"/incidents/{incident_id}/resolve",
                                    data={"note": "   "})
            ) \
            .then(
                _the_account_says_it_was_reported_as(
                    incident_id, Report(by="demo user", channel=ReportChannel.ARGUS_UI)
                )
            )


@pytest.mark.component
def test_a_resolution_tells_the_page_to_reload() -> None:
    # An incident Argus had already ended has a page that stopped polling, so
    # nothing would ever show the person what their press did unless the page
    # is told to fetch itself again.
    some_alert = Alert(service="tuki-service", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)
        incidents.transition(conn, incident_id, IncidentStatus.ESCALATED)

    with TestClient(app) as client:
        Scenario() \
            .given(
                incident_id
            ) \
            .when(
                lambda: client.post(f"/incidents/{incident_id}/resolve")
            ) \
            .then(
                _the_page_was_told_to_reload()
            )


@pytest.mark.component
def test_resolving_an_incident_that_cannot_be_resolved_is_refused() -> None:
    # Refused rather than ignored. A page that answered "done" to a press on a
    # withdrawn incident would have somebody believe they had closed something
    # that ended for another reason.
    some_alert = Alert(service="kuki-service", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)
        incidents.withdraw(conn, incident_id)

    with TestClient(app) as client:
        Scenario() \
            .given(
                incident_id
            ) \
            .when(
                lambda: client.post(f"/incidents/{incident_id}/resolve")
            ) \
            .then(all_of(
                the_response_was(HttpStatus.CONFLICT),
                _the_incident_is(incident_id, IncidentStatus.WITHDRAWN)
            ))


@pytest.mark.component
def test_resolving_an_incident_nobody_has_is_not_found() -> None:
    some_id_that_never_existed = "00000000-0000-0000-0000-000000000000"

    with TestClient(app) as client:
        Scenario() \
            .when(
                lambda: client.post(f"/incidents/{some_id_that_never_existed}/resolve")
            ) \
            .then(
                the_response_was(HttpStatus.NOT_FOUND)
            )


@pytest.mark.component
def test_a_resolution_continues_the_incidents_trace() -> None:
    # A person reporting the incident over is part of the incident's story, so
    # it is part of the incident's trace.
    some_alert = Alert(service="kuki-traced-resolution", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert, trace_context=SOME_TRACE_CONTEXT)

    with observing_the_app() as spans, TestClient(app) as client:
        Scenario() \
            .given(
                incident_id
            ) \
            .when(
                lambda: client.post(f"/incidents/{incident_id}/resolve")
            ) \
            .then(
                _it_was_resolved_inside_the_trace_it_kept(spans, incident_id)
            )


@pytest.mark.component
def test_a_resolution_refused_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    # Somebody pressed the button and nothing changed. The page tells them; the
    # log is where whoever they ask next finds that it happened.
    some_alert = Alert(service="kuki-refused-resolution", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)
        incidents.withdraw(conn, incident_id)

    with TestClient(app) as client:
        Scenario() \
            .given(
                calling(lambda: caplog.set_level(logging.INFO))
            ) \
            .when(
                lambda: client.post(f"/incidents/{incident_id}/resolve")
            ) \
            .then(
                one_record_was_logged(caplog, "argus_web.app", logging.INFO,
                                      "resolution refused")
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


def _the_account_says_it_was_reported_as(incident_id: str,
                                         expected: Report) -> Assertion[httpx2.Response]:
    def assertion(_response: httpx2.Response) -> bool:
        with connect_from_env() as conn:
            recorded = events.get_by_incident(conn, incident_id)

        reported = [event.reported for event in recorded
                    if isinstance(event, StatusChanged)
                    and event.to_status == IncidentStatus.RESOLVED]

        if reported != [expected]:
            raise AssertionError(
                f"Expected one resolution reported as [{expected}], got {reported}."
            )

        return True

    return assertion


def _the_page_was_told_to_reload() -> Assertion[httpx2.Response]:
    def assertion(response: httpx2.Response) -> bool:
        told = response.headers.get("HX-Refresh")

        if told != "true":
            raise AssertionError(
                f"Expected the response to tell the page to reload, it said [{told}]."
            )

        return True

    return assertion


def _it_was_resolved_inside_the_trace_it_kept(
    spans: InMemorySpanExporter, incident_id: str
) -> Assertion[httpx2.Response]:
    def assertion(_response: httpx2.Response) -> bool:
        resolved = the_span_named(spans, "resolve incident")
        parent = resolved.parent
        continued = (f"{parent.trace_id:032x}", f"{parent.span_id:016x}") if parent else None
        named = (resolved.attributes or {}).get(ARGUS_INCIDENT_ID)

        if continued != (SOME_TRACE, SOME_SPAN) or named != incident_id:
            raise AssertionError(
                f"Expected the resolution's span to continue the trace the incident "
                f"kept, [{SOME_TRACE}/{SOME_SPAN}], and to name [{incident_id}]; it "
                f"continued [{continued}] and named [{named}]."
            )

        return True

    return assertion
