from __future__ import annotations

import logging
from http import HTTPStatus as HttpStatus
from typing import Any

import pytest
from argus_core import connect_from_env
from argus_core.models import IncidentStatus
from argus_core.telemetry import ARGUS_INCIDENT_ID
from argus_incidents.repository import events, incidents, runs
from argus_testkit import Assertion, Scenario, all_of, one_record_was_logged
from argus_web.app import app
from fastapi.testclient import TestClient
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind

from argus_web_test.framework.assertions import the_response_was
from argus_web_test.framework.builders import a_grafana_payload
from argus_web_test.framework.observing import observing_the_app, the_span_named

# The state a run is in when nothing has picked it up yet. Named from the
# repository's own vocabulary rather than spelled out here, so a rename moves
# this with it.
QUEUED = runs.RunState.QUEUED

# What the span an alert is received in is called.
RECEIVE_ALERT = "receive alert"


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
                _the_account_says_only_that_the_alert_arrived()
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
                _the_graph_has_not_walked_it()
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
                _no_incident_is_open_for(some_service)
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
                _incidents_were_opened_for(some_service, count=1)
            ))


@pytest.mark.component
def test_an_alert_is_received_in_a_span_its_incident_keeps() -> None:
    # Where the incident's trace begins. The incident keeps this span's
    # context, and every walk of it continues from there - so a trace read in
    # a backend starts at the alert, not at whichever worker took the run.
    some_payload = a_grafana_payload(service="kuki-traced")

    with observing_the_app() as spans, TestClient(app) as client:
        Scenario() \
            .when(
                lambda: client.post("/webhooks/alerts", json=some_payload)
            ) \
            .then(all_of(
                _it_was_received_in_a_span_naming_its_incident(spans),
                _the_incident_keeps_the_span_it_was_received_in(spans)
            ))


@pytest.mark.component
def test_a_resolved_alert_is_received_in_a_span_naming_no_incident() -> None:
    # Received all the same - a request came in, and a trace of it is a trace
    # of what this process did - but it opened nothing, and says so.
    a_resolution = a_grafana_payload(
        service="kuki-resolved-traced", rule_uid="some-rule-that-resolved", status="resolved"
    )

    with observing_the_app() as spans, TestClient(app) as client:
        Scenario() \
            .when(
                lambda: client.post("/webhooks/alerts", json=a_resolution)
            ) \
            .then(
                _it_was_received_in_a_span_naming_no_incident(spans)
            )


@pytest.mark.component
def test_an_alert_that_cannot_be_read_is_refused_and_logged_as_a_warning(
    caplog: pytest.LogCaptureFixture
) -> None:
    # Bad input rather than a fault in Argus, so a refusal the sender is told
    # about and a warning rather than an error. Refused rather than failed, too:
    # Grafana sends a failure again and a refusal once, and a payload that could
    # not be read the first time reads no better the tenth.
    some_payload_naming_no_service = {"alerts": [{"status": "firing"}]}

    with TestClient(app) as client:
        Scenario() \
            .when(
                lambda: client.post("/webhooks/alerts", json=some_payload_naming_no_service)
            ) \
            .then(all_of(
                the_response_was(HttpStatus.UNPROCESSABLE_ENTITY),
                one_record_was_logged(caplog, "argus_web.app", logging.WARNING,
                                      "alert payload rejected", failure=KeyError)
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


def _it_was_received_in_a_span_naming_its_incident(spans: InMemorySpanExporter) -> Assertion[Any]:
    def assertion(response: Any) -> bool:
        received = the_span_named(spans, RECEIVE_ALERT)
        named = (received.attributes or {}).get(ARGUS_INCIDENT_ID)
        answered = response.json()["incident_id"]

        if received.kind != SpanKind.SERVER or named != answered:
            raise AssertionError(
                f"Expected the alert to be received in a server span naming the "
                f"incident [{answered}], and it was a [{received.kind}] span naming "
                f"[{named}]."
            )

        return True

    return assertion


def _the_incident_keeps_the_span_it_was_received_in(
    spans: InMemorySpanExporter
) -> Assertion[Any]:
    def assertion(response: Any) -> bool:
        received = the_span_named(spans, RECEIVE_ALERT).get_span_context()

        with connect_from_env() as conn:
            incident = incidents.get(conn, response.json()["incident_id"])

        traceparent = incident.trace_context.get("traceparent", "") if incident else ""
        # Version, trace, span, flags: the trace and the span are what make it
        # this span's context, and the flags are the propagator's business.
        kept = traceparent.split("-")[1:3]
        expected = [f"{received.trace_id:032x}", f"{received.span_id:016x}"] \
            if received is not None else ["a span with a context"]

        if kept != expected:
            raise AssertionError(
                f"Expected the incident to keep the context of the span its alert "
                f"was received in, [{expected}], and it kept [{kept}]."
            )

        return True

    return assertion


def _it_was_received_in_a_span_naming_no_incident(
    spans: InMemorySpanExporter
) -> Assertion[Any]:
    def assertion(_response: Any) -> bool:
        named = (the_span_named(spans, RECEIVE_ALERT).attributes or {}).get(ARGUS_INCIDENT_ID)

        if named is not None:
            raise AssertionError(
                f"Expected an alert that opened nothing to name no incident, "
                f"and its span named [{named}]."
            )

        return True

    return assertion
