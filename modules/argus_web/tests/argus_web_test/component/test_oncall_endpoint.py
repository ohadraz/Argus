"""The door the on-call platform knocks on, from the outside.

What a person's resolution in the platform does to the incident record, and what
each other outcome is answered with. The answers are for the platform, which
acts on them: a success is never sent again, a failure is sent again for two
days, and a refusal is dropped - so an outage of the platform's own API is a
failure here, and a forgery is a refusal.

The platform is stood in through the app's own dependency seam: it is somebody
else's API, and what it says is decided in the adapter's suite. The incident
record is real, because whether the person's word reaches the incident is the
question.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from http import HTTPStatus as HttpStatus
from typing import Any
from unittest.mock import create_autospec
from uuid import uuid4

import httpx2
import pytest
from argus_core import connect_from_env
from argus_core.events import StatusChanged
from argus_core.models import (
    NOTIFICATION_KEY,
    Alert,
    IncidentStatus,
    Reference,
    Report,
    ReportChannel,
)
from argus_core.telemetry import ARGUS_INCIDENT_ID
from argus_incidents.repository import events, incidents, references
from argus_testkit import Assertion, Scenario, all_of, calling, one_record_was_logged
from argus_web.app import app, oncall_platform_of
from fastapi.testclient import TestClient
from oncall_source import OnCallUnavailable
from oncall_source.platform import (
    Delivery,
    DeliveryUnverified,
    Irrelevant,
    OnCallPlatform,
    ResolvedByAPerson,
)
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from argus_web_test.framework.assertions import the_response_was
from argus_web_test.framework.observing import observing_the_app, the_span_named

ONCALL_WEBHOOK = "/webhooks/oncall"

DONT_CARE_BODY = b"{}"

# The context an incident kept from the span its alert was received in.
SOME_TRACE = "4bf92f3577b34da6a3ce929d0e0e4736"
SOME_SPAN = "00f067aa0ba902b7"
SOME_TRACE_CONTEXT = {"traceparent": f"00-{SOME_TRACE}-{SOME_SPAN}-01"}


@pytest.mark.component
def test_a_persons_resolution_in_the_platform_resolves_the_incident() -> None:
    some_person = "some person"
    some_note = "rolled the flag back by hand"
    some_key = _a_key()
    incident_id = _an_incident_known_by(some_key)

    with _the_platform_saying(ResolvedByAPerson(platform_incident=_a_platform_incident(),
                                                by=some_person),
                              keys=[some_key], note=some_note), TestClient(app) as client:
        Scenario() \
            .when(lambda: client.post(ONCALL_WEBHOOK, content=DONT_CARE_BODY)) \
            .then(all_of(
                the_response_was(HttpStatus.ACCEPTED),
                _the_incident_is(incident_id, IncidentStatus.RESOLVED),
                _the_account_says_it_was_reported_as(
                    incident_id,
                    Report(by=some_person, channel=ReportChannel.PAGERDUTY, note=some_note)
                )
            ))


@pytest.mark.component
def test_a_resolution_from_the_platform_continues_the_incidents_trace() -> None:
    # As one from the page does: a person reporting it over is part of the
    # incident's story, wherever they said it.
    some_key = _a_key()
    incident_id = _an_incident_known_by(some_key, trace_context=SOME_TRACE_CONTEXT)

    with _the_platform_saying(ResolvedByAPerson(platform_incident=_a_platform_incident(),
                                                by="dont care"),
                              keys=[some_key]), \
            observing_the_app() as spans, TestClient(app) as client:
        Scenario() \
            .when(lambda: client.post(ONCALL_WEBHOOK, content=DONT_CARE_BODY)) \
            .then(_it_was_resolved_inside_the_trace_it_kept(spans, incident_id))


@pytest.mark.component
def test_a_delivery_about_anything_else_is_accepted() -> None:
    # Received intact, and nothing to do. Answered as received, because a
    # platform told "error" about news Argus does not need disables the hook.
    with _the_platform_saying(Irrelevant(event="incident.annotated"), keys=[]), \
            TestClient(app) as client:
        Scenario() \
            .when(lambda: client.post(ONCALL_WEBHOOK, content=DONT_CARE_BODY)) \
            .then(the_response_was(HttpStatus.ACCEPTED))


@pytest.mark.component
def test_a_forged_delivery_is_refused() -> None:
    # A refusal, not a failure: the platform drops it rather than send a
    # forgery again for two days.
    with _the_platform_refusing(DeliveryUnverified("forged")), TestClient(app) as client:
        Scenario() \
            .when(lambda: client.post(ONCALL_WEBHOOK, content=DONT_CARE_BODY)) \
            .then(the_response_was(HttpStatus.UNAUTHORIZED))


@pytest.mark.component
def test_a_forged_delivery_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    # The likeliest way to meet a refusal is a deployment holding the wrong
    # secret, and a refusal nobody can see is one nobody can fix.
    with _the_platform_refusing(DeliveryUnverified("forged")), TestClient(app) as client:
        Scenario() \
            .given(calling(lambda: caplog.set_level(logging.WARNING))) \
            .when(lambda: client.post(ONCALL_WEBHOOK, content=DONT_CARE_BODY)) \
            .then(one_record_was_logged(caplog, "argus_web.app", logging.WARNING,
                                        "on-call delivery refused"))


@pytest.mark.component
def test_a_platform_that_cannot_be_read_is_answered_as_unavailable() -> None:
    # A failure, so the platform sends the person's word again once its API is
    # back, rather than Argus never hearing it.
    with _the_platform_saying(ResolvedByAPerson(platform_incident=_a_platform_incident(),
                                                by="dont care"),
                              keys=OnCallUnavailable("unreachable")), \
            TestClient(app) as client:
        Scenario() \
            .when(lambda: client.post(ONCALL_WEBHOOK, content=DONT_CARE_BODY)) \
            .then(the_response_was(HttpStatus.SERVICE_UNAVAILABLE))


@pytest.mark.component
def test_without_an_on_call_platform_there_is_no_door() -> None:
    # The platform is optional, and a deployment without one behaves as though
    # the feature did not exist.
    with _no_platform(), TestClient(app) as client:
        Scenario() \
            .when(lambda: client.post(ONCALL_WEBHOOK, content=DONT_CARE_BODY)) \
            .then(the_response_was(HttpStatus.NOT_FOUND))


def _a_key() -> str:
    """A key no other case has used. This suite keeps its rows between cases,
    and a key shared with an earlier one would find that case's incident."""
    return f"key-{uuid4()}"


def _a_platform_incident() -> str:
    """A platform incident id no other case has used, for the same reason."""
    return f"P{uuid4().hex[:13].upper()}"


def _an_incident_known_by(key: str,
                          trace_context: Mapping[str, str] = incidents.NO_TRACE_CONTEXT) -> str:
    """An incident the monitor paged the platform for under `key`."""
    some_alert = Alert(service="kuki-service", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert, trace_context)
        references.add(conn, incident_id, [
            Reference(source="grafana", kind=NOTIFICATION_KEY, value=key)
        ])
        conn.commit()

    return incident_id


@contextmanager
def _the_platform_saying(delivery: Delivery,
                         keys: list[str] | Exception,
                         note: str | None = None) -> Iterator[None]:
    platform = create_autospec(OnCallPlatform, instance=True)
    platform.channel = ReportChannel.PAGERDUTY
    platform.read_delivery.return_value = delivery
    platform.resolution_note.return_value = note

    if isinstance(keys, Exception):
        platform.keys_of.side_effect = keys
    else:
        platform.keys_of.return_value = keys

    with _the_platform_being(platform):
        yield


@contextmanager
def _the_platform_refusing(refusal: Exception) -> Iterator[None]:
    platform = create_autospec(OnCallPlatform, instance=True)
    platform.read_delivery.side_effect = refusal

    with _the_platform_being(platform):
        yield


@contextmanager
def _no_platform() -> Iterator[None]:
    with _the_platform_being(None):
        yield


@contextmanager
def _the_platform_being(platform: Any) -> Iterator[None]:
    """FastAPI's own seam for standing something in, put back as the block ends."""
    app.dependency_overrides[oncall_platform_of] = lambda: platform

    try:
        yield
    finally:
        app.dependency_overrides.pop(oncall_platform_of, None)


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
