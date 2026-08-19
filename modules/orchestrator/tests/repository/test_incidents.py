from __future__ import annotations

from functools import partial

import psycopg
import pytest
from argus_core.models.actor import Actor
from argus_core.models.alert import Alert
from argus_core.models.incident_status import IncidentStatus
from orchestrator.repository import incidents, timeline

from .framework.assertions import Assertion, all_of
from .framework.scenario import Scenario

DATABASE_URL = "postgresql://argus:argus@localhost:5432/argus"


@pytest.mark.integration
def test_create_writes_incident_and_initial_timeline_event() -> None:
    some_service = "kuki-service"
    some_alert_name = "HighErrorRate"
    some_alert = Alert(service=some_service, alert_name=some_alert_name)

    with psycopg.connect(DATABASE_URL) as conn:
        Scenario(conn) \
            .when(
                incident_id := incidents.create(conn, some_alert)
            ) \
            .then(all_of(
                _the_incident_is_investigating(incident_id),
                _exactly_one_timeline_event_was_recorded(incident_id),
            ))


@pytest.mark.integration
def test_transition_updates_status_and_appends_timeline_event() -> None:
    some_service = "buki-service"
    some_alert_name = "HighErrorRate"
    some_alert = Alert(service=some_service, alert_name=some_alert_name)

    with psycopg.connect(DATABASE_URL) as conn:
        an_incident_created_for = partial(_an_incident_created_for, conn)

        Scenario(conn) \
            .given(
                incident_id := an_incident_created_for(some_alert)
            ) \
            .when(
                lambda: incidents.transition(
                    conn,
                    incident_id,
                    IncidentStatus.MITIGATING,
                    actor=Actor.INVESTIGATOR,
                    action="hypothesis formed",
                    result="some hypothesis",
                    confidence=0.9,
                )
            ) \
            .then(all_of(
                _the_incident_is_mitigating(incident_id),
                _timeline_shows_investigating_then_mitigating(incident_id),
            ))


def _an_incident_created_for(conn: psycopg.Connection, alert: Alert) -> str:
    return incidents.create(conn, alert)


def _timeline_shows_investigating_then_mitigating(incident_id: str) -> Assertion:
    def assertion(conn: psycopg.Connection) -> bool:
        events = timeline.get_timeline_events(conn, incident_id)
        actual_statuses = [event.to_status for event in events]

        if actual_statuses != ["investigating", "mitigating"]:
            raise AssertionError(
                f"Expected status sequence ['investigating', 'mitigating'], got {actual_statuses}."
            )
        if events[-1].actor != "investigator":
            raise AssertionError(f"Expected actor ['investigator'], got [{events[-1].actor!r}].")

        if events[-1].confidence != 0.9:
            raise AssertionError(f"Expected confidence [0.9], got [{events[-1].confidence!r}].")

        return True

    return assertion


def _the_incident_is_investigating(incident_id: str) -> Assertion:
    def assertion(conn: psycopg.Connection) -> bool:
        incident = incidents.get(conn, incident_id)

        if incident is None:
            raise AssertionError(f"No incident found with id [{incident_id}].")

        if incident.status != "investigating":
            raise AssertionError(f"Expected status ['investigating'], got [{incident.status!r}].")

        return True

    return assertion


def _the_incident_is_mitigating(incident_id: str) -> Assertion:
    def assertion(conn: psycopg.Connection) -> bool:
        incident = incidents.get(conn, incident_id)

        if incident is None:
            raise AssertionError(f"No incident found with id [{incident_id}].")

        if incident.status != "mitigating":
            raise AssertionError(f"Expected status ['mitigating'], got [{incident.status!r}].")

        return True

    return assertion


def _exactly_one_timeline_event_was_recorded(incident_id: str) -> Assertion:
    def assertion(conn: psycopg.Connection) -> bool:
        events = timeline.get_timeline_events(conn, incident_id)

        if len(events) != 1:
            raise AssertionError(f"Expected exactly 1 timeline event, got {len(events)}.")
        if events[0].to_status != "investigating":
            raise AssertionError(
                f"Expected to_status ['investigating'], got [{events[0].to_status!r}]."
            )
        if events[0].actor != "orchestrator":
            raise AssertionError(f"Expected actor ['orchestrator'], got [{events[0].actor!r}].")

        return True

    return assertion


@pytest.mark.integration
def test_get_returns_none_for_unknown_incident() -> None:
    with psycopg.connect(DATABASE_URL) as conn:
        assert incidents.get(conn, "00000000-0000-0000-0000-000000000000") is None
