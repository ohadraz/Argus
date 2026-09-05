from __future__ import annotations

from functools import partial
from typing import Any

import psycopg
import pytest
from argus_core.models.actor import Actor
from argus_core.models.alert import Alert
from argus_core.models.incident_status import IncidentStatus
from argus_testkit import Assertion, Scenario, all_of
from orchestrator.repository import incidents, timeline

DATABASE_URL = "postgresql://argus:argus@localhost:5432/argus"


@pytest.mark.integration
def test_create_writes_incident_and_initial_timeline_event() -> None:
    some_service = "kuki-service"
    some_alert_name = "HighErrorRate"
    some_alert = Alert(service=some_service, alert_name=some_alert_name)

    with psycopg.connect(DATABASE_URL) as conn:
        the_incident_is = partial(_the_incident_is, conn)
        the_timeline_shows = partial(_the_timeline_shows, conn)
        the_last_timeline_event_was = partial(_the_last_timeline_event_was, conn)


        Scenario() \
            .when(
                incident_id := incidents.create(conn, some_alert)
            ) \
            .then(all_of(
                the_incident_is(incident_id, "acknowledged"),
                the_timeline_shows(incident_id, "acknowledged"),
                the_last_timeline_event_was(incident_id, "orchestrator"),
            ))


@pytest.mark.integration
def test_transition_updates_status_and_appends_timeline_event() -> None:
    some_service = "buki-service"
    some_alert_name = "HighErrorRate"
    some_alert = Alert(service=some_service, alert_name=some_alert_name)
    some_confidence = 0.9

    with psycopg.connect(DATABASE_URL) as conn:
        an_incident_created_for = partial(_an_incident_created_for, conn)
        the_incident_is = partial(_the_incident_is, conn)
        the_timeline_shows = partial(_the_timeline_shows, conn)
        the_last_timeline_event_was = partial(_the_last_timeline_event_was, conn)

        Scenario() \
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
                    confidence=some_confidence,
                )
            ) \
            .then(all_of(
                the_incident_is(incident_id, "mitigating"),
                the_timeline_shows(incident_id, "acknowledged", "mitigating"),
                the_last_timeline_event_was(
                    incident_id, "investigator", confidence=some_confidence),
            ))


@pytest.mark.integration
def test_get_current_prefers_an_incident_that_has_not_finished() -> None:
    # Not simply the newest. An incident that resolved after this one opened has
    # nothing left to watch; the one still running is what a reader came for.
    with psycopg.connect(DATABASE_URL) as conn:
        still_running = incidents.create(conn, Alert(service="running", alert_name="HighErrorRate"))
        already_finished = incidents.create(
            conn, Alert(service="finished", alert_name="HighErrorRate")
        )
        incidents.transition(
            conn,
            already_finished,
            IncidentStatus.RESOLVED,
            actor=Actor.MITIGATION,
            action="dont care",
        )

        current = incidents.get_current(conn)

    assert current is not None and current.id == still_running


@pytest.mark.integration
def test_get_current_falls_back_to_the_newest_when_nothing_is_running() -> None:
    # A resolved incident vanishing the moment it resolves would take it off the
    # screen exactly when everyone is looking at it.
    with psycopg.connect(DATABASE_URL) as conn:
        _no_incidents_at_all(conn)
        incident_id = incidents.create(conn, Alert(service="io-shop", alert_name="HighErrorRate"))
        incidents.transition(
            conn,
            incident_id,
            IncidentStatus.RESOLVED,
            actor=Actor.MITIGATION,
            action="dont care",
        )

        current = incidents.get_current(conn)

    assert current is not None and current.id == incident_id


@pytest.mark.integration
def test_get_current_is_none_when_there_has_never_been_an_incident() -> None:
    # The state Argus is in most of the time, and the one the front page has to
    # say out loud rather than render as an empty frame.
    with psycopg.connect(DATABASE_URL) as conn:
        _no_incidents_at_all(conn)

        assert incidents.get_current(conn) is None


@pytest.mark.integration
def test_an_incident_that_resolved_records_when_it_ended() -> None:
    # How long an incident lasted is a figure the postmortem reports, so it is
    # recorded when it happens rather than inferred later from whichever row
    # was written last - an inference that changes silently the moment
    # anything is logged late.
    some_alert = Alert(service="kuki-service", alert_name="HighErrorRate")

    with psycopg.connect(DATABASE_URL) as conn:
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
                    actor=Actor.MITIGATION,
                    action="dont care",
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

    with psycopg.connect(DATABASE_URL) as conn:
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
                    actor=Actor.ORCHESTRATOR,
                    action="dont care",
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

    with psycopg.connect(DATABASE_URL) as conn:
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
                    actor=Actor.ORCHESTRATOR,
                    action="dont care",
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
    with psycopg.connect(DATABASE_URL) as conn:
        assert incidents.get(conn, "00000000-0000-0000-0000-000000000000") is None


@pytest.mark.integration
def test_record_note_appends_to_the_timeline_without_moving_the_incident() -> None:
    # An action refused at the tier gate is worth recording and moves nothing:
    # the incident was already mitigating and still is. Narration and transition
    # were one function only by accident, and this is the case that proves it -
    # a rejection written through `transition` would claim the incident entered
    # a status it had not left.
    some_alert = Alert(service="gate-service", alert_name="HighErrorRate")

    with psycopg.connect(DATABASE_URL) as conn:
        incident_id = incidents.create(conn, some_alert)
        incidents.transition(
            conn,
            incident_id,
            IncidentStatus.MITIGATING,
            actor=Actor.INVESTIGATOR,
            action="dont care",
        )

        incidents.record_note(
            conn,
            incident_id,
            actor=Actor.MITIGATION,
            action="action rejected at the tier gate",
            result="the proposed action carries no undo descriptor",
        )

        incident = incidents.get(conn, incident_id)
        events = timeline.get_timeline_events(conn, incident_id)

    assert incident is not None and incident.status == "mitigating"
    assert [event.to_status for event in events] == [
        "acknowledged",
        "mitigating",
        "mitigating",
    ]
    assert events[-1].action == "action rejected at the tier gate"
    assert events[-1].actor == "mitigation"


def _the_timeline_shows(conn: psycopg.Connection,
                        incident_id: str,
                        *statuses: str) -> Assertion[Any]:
    """The whole sequence a timeline recorded, in order.

    The whole of it rather than a slice: a timeline is read as the account of
    where an incident has been, and an assertion checking only its last entry
    would pass just as happily on an account that skipped a status entirely.
    """
    def assertion(_result: Any) -> bool:
        recorded = [event.to_status
                    for event in timeline.get_timeline_events(conn, incident_id)]

        if recorded != list(statuses):
            raise AssertionError(
                f"Expected the timeline to record {list(statuses)}, got {recorded}."
            )

        return True

    return assertion


def _the_incident_is(conn: psycopg.Connection,
                     incident_id: str,
                     status: str) -> Assertion[Any]:
    def assertion(_result: Any) -> bool:
        incident = incidents.get(conn, incident_id)

        if incident is None:
            raise AssertionError(f"No incident found with id [{incident_id}].")

        if incident.status != status:
            raise AssertionError(
                f"Expected status [{status!r}], got [{incident.status!r}]."
            )

        return True

    return assertion


def _the_last_timeline_event_was(conn: psycopg.Connection,
                                 incident_id: str,
                                 actor: str,
                                 confidence: float | None = None) -> Assertion[Any]:
    """Who moved the incident, and how sure they were.

    Separate from the sequence below because it answers a different question:
    that one says where the incident went, this says who took it there. A test
    asking only one of the two calls only one of these.
    """
    def assertion(_result: Any) -> bool:
        last = timeline.get_timeline_events(conn, incident_id)[-1]

        if last.actor != actor:
            raise AssertionError(f"Expected actor [{actor!r}], got [{last.actor!r}].")

        if confidence is not None and last.confidence != confidence:
            raise AssertionError(
                f"Expected confidence [{confidence}], got [{last.confidence!r}]."
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
