from __future__ import annotations

from functools import partial
from typing import Any

import psycopg
import pytest
from argus_core.db import connect
from argus_core.models.alert import Alert
from argus_core.models.incident_status import IncidentStatus
from argus_incidents.repository import incidents
from argus_testkit import Assertion, Scenario


@pytest.mark.integration
def test_create_writes_the_incident_acknowledged() -> None:
    # `acknowledged`, not `investigating`: this runs where the alert is
    # received, and the walk it queues belongs to a worker that has not taken
    # it yet. The line saying the alert arrived is published by the intake
    # beside this, and asserted there.
    some_service = "kuki-service"
    some_alert_name = "HighErrorRate"
    some_alert = Alert(service=some_service, alert_name=some_alert_name)

    with connect() as conn:
        the_incident_is = partial(_the_incident_is, conn)

        Scenario() \
            .when(
                lambda: incidents.create(conn, some_alert)
            ) \
            .then(
                the_incident_is("acknowledged")
            )


@pytest.mark.integration
def test_transition_updates_the_status() -> None:
    # The whole of what this writes. What moved the incident, why, and how sure
    # it was are published as the `StatusChanged` beside it, on the same
    # connection - asserted where that is published rather than here, because
    # here there is nothing left to hold them.
    some_service = "buki-service"
    some_alert_name = "HighErrorRate"
    some_alert = Alert(service=some_service, alert_name=some_alert_name)

    with connect() as conn:
        an_incident_created_for = partial(_an_incident_created_for, conn)
        the_incident_is = partial(_the_incident_is, conn)

        Scenario() \
            .given(
                incident_id := an_incident_created_for(some_alert)
            ) \
            .when(
                lambda: incidents.transition(
                    conn, incident_id, IncidentStatus.MITIGATING
                )
            ) \
            .then(
                the_incident_is("mitigating", incident_id=incident_id)
            )


@pytest.mark.integration
def test_get_current_prefers_an_incident_that_has_not_finished() -> None:
    # Not simply the newest. An incident that resolved after this one opened has
    # nothing left to watch; the one still running is what a reader came for.
    with connect() as conn:
        still_running = incidents.create(conn, Alert(service="running", alert_name="HighErrorRate"))
        already_finished = incidents.create(
            conn, Alert(service="finished", alert_name="HighErrorRate")
        )
        incidents.transition(
            conn,
            already_finished,
            IncidentStatus.RESOLVED,
        )

        current = incidents.get_current(conn)

    assert current is not None and current.id == still_running


@pytest.mark.integration
def test_get_current_falls_back_to_the_newest_when_nothing_is_running() -> None:
    # A resolved incident vanishing the moment it resolves would take it off the
    # screen exactly when everyone is looking at it.
    with connect() as conn:
        _no_incidents_at_all(conn)
        incident_id = incidents.create(conn, Alert(service="io-shop", alert_name="HighErrorRate"))
        incidents.transition(
            conn,
            incident_id,
            IncidentStatus.RESOLVED,
        )

        current = incidents.get_current(conn)

    assert current is not None and current.id == incident_id


@pytest.mark.integration
def test_get_current_is_none_when_there_has_never_been_an_incident() -> None:
    # The state Argus is in most of the time, and the one the front page has to
    # say out loud rather than render as an empty frame.
    with connect() as conn:
        _no_incidents_at_all(conn)

        assert incidents.get_current(conn) is None


@pytest.mark.integration
def test_an_incident_that_resolved_records_when_it_ended() -> None:
    # How long an incident lasted is a figure the postmortem reports, so it is
    # recorded when it happens rather than inferred later from whichever row
    # was written last - an inference that changes silently the moment
    # anything is logged late.
    some_alert = Alert(service="kuki-service", alert_name="HighErrorRate")

    with connect() as conn:
        an_incident_created_for = partial(_an_incident_created_for, conn)
        the_incident_records_an_end = partial(_the_incident_records_an_end, conn)

        Scenario() \
            .given(
                incident_id := an_incident_created_for(some_alert)
            ) \
            .when(
                lambda: incidents.transition(
                    conn,
                    incident_id,
                    IncidentStatus.RESOLVED,
                )
            ) \
            .then(
                the_incident_records_an_end(incident_id)
            )


@pytest.mark.integration
def test_an_incident_that_escalated_records_when_it_ended() -> None:
    # Escalation is an ending too. An incident nobody could resolve still cost
    # what it cost, and a postmortem that could not say how long it ran would
    # be missing the figure for exactly the incidents that ran longest.
    some_alert = Alert(service="buki-service", alert_name="HighErrorRate")

    with connect() as conn:
        an_incident_created_for = partial(_an_incident_created_for, conn)
        the_incident_records_an_end = partial(_the_incident_records_an_end, conn)

        Scenario() \
            .given(
                incident_id := an_incident_created_for(some_alert)
            ) \
            .when(
                lambda: incidents.transition(
                    conn,
                    incident_id,
                    IncidentStatus.ESCALATED,
                )
            ) \
            .then(
                the_incident_records_an_end(incident_id)
            )


@pytest.mark.integration
def test_an_incident_still_being_worked_records_no_end() -> None:
    # `fixing` is the case worth stating: it reads like an ending and is not
    # one - Code-Fix is still looking - so an incident stamped on the way into
    # it would report a duration for something still running.
    some_alert = Alert(service="muki-service", alert_name="HighErrorRate")

    with connect() as conn:
        an_incident_created_for = partial(_an_incident_created_for, conn)
        the_incident_records_no_end = partial(_the_incident_records_no_end, conn)

        Scenario() \
            .given(
                incident_id := an_incident_created_for(some_alert)
            ) \
            .when(
                lambda: incidents.transition(
                    conn,
                    incident_id,
                    IncidentStatus.FIXING,
                )
            ) \
            .then(
                the_incident_records_no_end(incident_id)
            )


def _no_incidents_at_all(conn: psycopg.Connection) -> None:
    """An empty table, which is the one state "the newest incident" cannot be
    set up into by adding a row."""
    with conn.cursor() as cursor:
        cursor.execute("TRUNCATE incident CASCADE")
    conn.commit()


def _an_incident_created_for(conn: psycopg.Connection, alert: Alert) -> str:
    return incidents.create(conn, alert)


@pytest.mark.integration
def test_get_returns_none_for_unknown_incident() -> None:
    with connect() as conn:
        assert incidents.get(conn, "00000000-0000-0000-0000-000000000000") is None


def _the_incident_is(conn: psycopg.Connection,
                     status: str,
                     incident_id: str | None = None) -> Assertion[Any]:
    """The status the incident row carries.

    `incident_id` is optional for the reason it is above.
    """
    def assertion(result: Any) -> bool:
        the_incident = incident_id if incident_id is not None else result
        incident = incidents.get(conn, the_incident)

        if incident is None:
            raise AssertionError(f"No incident found with id [{the_incident}].")

        if incident.status != status:
            raise AssertionError(
                f"Expected status [{status!r}], got [{incident.status!r}]."
            )

        return True

    return assertion


def _the_incident_records_an_end(conn: psycopg.Connection, incident_id: str) -> Assertion[Any]:
    def assertion(_result: Any) -> bool:
        incident = incidents.get(conn, incident_id)

        if incident is None:
            raise AssertionError(f"No incident found with id [{incident_id}].")

        if incident.ended_at is None:
            raise AssertionError(
                f"Expected incident [{incident_id}] to record when it ended, got none."
            )

        if incident.ended_at < incident.created_at:
            raise AssertionError(
                f"Expected an end at or after the start [{incident.created_at}], "
                f"got [{incident.ended_at}]."
            )

        return True

    return assertion


def _the_incident_records_no_end(conn: psycopg.Connection, incident_id: str) -> Assertion[Any]:
    def assertion(_result: Any) -> bool:
        incident = incidents.get(conn, incident_id)

        if incident is None:
            raise AssertionError(f"No incident found with id [{incident_id}].")

        if incident.ended_at is not None:
            raise AssertionError(
                f"Expected incident [{incident_id}] to record no end while it is still "
                f"being worked, got [{incident.ended_at}]."
            )

        return True

    return assertion
