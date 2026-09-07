from __future__ import annotations

from datetime import datetime
from functools import partial

import psycopg
import pytest
from argus_core.db import connect
from argus_core.models.actor import Actor
from argus_core.models.alert import Alert
from argus_core.models.incident_status import IncidentStatus
from argus_incidents.repository import incidents, timeline
from argus_testkit import Assertion, Scenario, all_of

"""Taking an incident back from Argus.

Withdrawal is the one status set from outside the walk. Everything else an
incident becomes is derived from work the walk did and written by the walk
itself; this is written by whoever pressed the button, and the walk finds out
by reading it back.

Refused for an incident that has already ended, and refused rather than ignored:
an incident that resolved was resolved by a mitigation that is holding the
service up, and "withdrawing" it would undo the fix.
"""


@pytest.mark.integration
def test_a_running_incident_can_be_withdrawn() -> None:
    some_alert = Alert(service="kuki-service", alert_name="HighErrorRate")
    # Who withdrew is the caller's to say - a person on the incident page, a
    # test tearing down what it started - so the repository takes it and does
    # not decide it.
    some_actor = Actor.HUMAN

    with connect() as conn:
        an_incident_created_for = partial(_an_incident_created_for, conn)
        the_incident_is = partial(_the_incident_is, conn)
        the_timeline_shows = partial(_the_timeline_shows, conn)
        the_last_timeline_event_was = partial(_the_last_timeline_event_was, conn)
        the_incident_records_an_end = partial(_the_incident_records_an_end, conn)

        Scenario() \
            .given(
                incident_id := an_incident_created_for(some_alert)
            ) \
            .when(
                lambda: incidents.withdraw(conn, incident_id, actor=some_actor)
            ) \
            .then(all_of(
                the_incident_is(incident_id, IncidentStatus.WITHDRAWN),
                the_timeline_shows(
                    incident_id, IncidentStatus.ACKNOWLEDGED, IncidentStatus.WITHDRAWN),
                the_last_timeline_event_was(incident_id, some_actor),
                the_incident_records_an_end(incident_id)
            ))


@pytest.mark.integration
def test_withdrawing_says_that_it_took_effect() -> None:
    # The answer is what the endpoint reports back and what the walk's own
    # unwind is conditioned on, so a withdrawal that silently did nothing must
    # not read the same as one that stopped an incident.
    some_alert = Alert(service="buki-service", alert_name="HighErrorRate")
    dont_care_actor = Actor.ORCHESTRATOR

    with connect() as conn:
        an_incident_created_for = partial(_an_incident_created_for, conn)

        Scenario() \
            .given(
                incident_id := an_incident_created_for(some_alert)
            ) \
            .when(
                incidents.withdraw(conn, incident_id, actor=dont_care_actor)
            ) \
            .then(
                _it_reported(True)
            )


@pytest.mark.integration
def test_an_incident_that_already_ended_is_not_withdrawn() -> None:
    # A resolved incident was resolved by a mitigation that is holding the
    # service up. Withdrawing it would put the failure back.
    some_alert = Alert(service="muki-service", alert_name="HighErrorRate")
    dont_care_actor = Actor.POSTMORTEM

    with connect() as conn:
        a_resolved_incident_for = partial(_a_resolved_incident_for, conn)
        the_incident_is = partial(_the_incident_is, conn)
        the_timeline_shows = partial(_the_timeline_shows, conn)

        Scenario() \
            .given(
                incident_id := a_resolved_incident_for(some_alert)
            ) \
            .when(
                incidents.withdraw(conn, incident_id, actor=dont_care_actor)
            ) \
            .then(all_of(
                _it_reported(False),
                the_incident_is(incident_id, IncidentStatus.RESOLVED),
                the_timeline_shows(
                    incident_id, IncidentStatus.ACKNOWLEDGED, IncidentStatus.RESOLVED)
            ))


@pytest.mark.integration
def test_withdrawing_twice_changes_nothing_the_second_time() -> None:
    # The page can be double-clicked and a teardown can withdraw what a case
    # already withdrew. Neither should write a second row, and neither should
    # move the end time the first one stamped.
    some_alert = Alert(service="tuki-service", alert_name="HighErrorRate")
    dont_care_actor = Actor.MITIGATION

    with connect() as conn:
        a_withdrawn_incident_for = partial(_a_withdrawn_incident_for, conn)
        the_incident_is = partial(_the_incident_is, conn)
        the_timeline_shows = partial(_the_timeline_shows, conn)
        the_incident_still_ended_at = partial(_the_incident_still_ended_at, conn)

        incident_id = a_withdrawn_incident_for(some_alert, dont_care_actor)

        Scenario() \
            .given(
                first_ended_at := _when_it_ended(conn, incident_id)
            ) \
            .when(
                incidents.withdraw(conn, incident_id, actor=dont_care_actor)
            ) \
            .then(all_of(
                _it_reported(False),
                the_incident_is(incident_id, IncidentStatus.WITHDRAWN),
                the_timeline_shows(
                    incident_id, IncidentStatus.ACKNOWLEDGED, IncidentStatus.WITHDRAWN),
                the_incident_still_ended_at(incident_id, first_ended_at)
            ))


def _an_incident_created_for(conn: psycopg.Connection, alert: Alert) -> str:
    return incidents.create(conn, alert)


def _a_resolved_incident_for(conn: psycopg.Connection, alert: Alert) -> str:
    incident_id = incidents.create(conn, alert)
    incidents.transition(
        conn,
        incident_id,
        IncidentStatus.RESOLVED,
        actor=Actor.MITIGATION,
        action="dont care",
    )

    return incident_id


def _a_withdrawn_incident_for(conn: psycopg.Connection,
                              alert: Alert,
                              actor: Actor) -> str:
    incident_id = incidents.create(conn, alert)
    incidents.withdraw(conn, incident_id, actor=actor)

    return incident_id


def _it_reported(expected: bool) -> Assertion[bool]:
    def assertion(withdrawn: bool) -> bool:
        if withdrawn != expected:
            raise AssertionError(
                f"Expected the withdrawal to report that it "
                f"{"took effect" if expected else "changed nothing"}, "
                f"got [{withdrawn!r}]."
            )

        return True

    return assertion


def _the_incident_is(conn: psycopg.Connection,
                     incident_id: str,
                     status: IncidentStatus) -> Assertion[bool]:
    def assertion(_result: bool) -> bool:
        incident = incidents.get(conn, incident_id)

        if incident is None:
            raise AssertionError(f"No incident found with id [{incident_id}].")

        if incident.status != status:
            raise AssertionError(
                f"Expected status [{status!r}], got [{incident.status!r}]."
            )

        return True

    return assertion


def _the_timeline_shows(conn: psycopg.Connection,
                        incident_id: str,
                        *statuses: IncidentStatus) -> Assertion[bool]:
    """The whole sequence a timeline recorded, in order.

    The whole of it rather than a slice: a refused withdrawal that wrote a row
    anyway would still leave the incident's status correct, and only the
    sequence shows the row that should not be there.
    """
    def assertion(_result: bool) -> bool:
        recorded = [event.to_status
                    for event in timeline.get_timeline_events(conn, incident_id)]

        if recorded != list(statuses):
            raise AssertionError(
                f"Expected the timeline to record {list(statuses)}, got {recorded}."
            )

        return True

    return assertion


def _the_last_timeline_event_was(conn: psycopg.Connection,
                                 incident_id: str,
                                 actor: Actor) -> Assertion[bool]:
    def assertion(_result: bool) -> bool:
        last = timeline.get_timeline_events(conn, incident_id)[-1]

        if last.actor != actor:
            raise AssertionError(f"Expected actor [{actor!r}], got [{last.actor!r}].")

        return True

    return assertion


def _the_incident_records_an_end(conn: psycopg.Connection,
                                 incident_id: str) -> Assertion[bool]:
    def assertion(_result: bool) -> bool:
        incident = incidents.get(conn, incident_id)

        if incident is None:
            raise AssertionError(f"No incident found with id [{incident_id}].")

        if incident.ended_at is None:
            raise AssertionError(
                f"Expected incident [{incident_id}] to record when it ended, got none."
            )

        return True

    return assertion


def _when_it_ended(conn: psycopg.Connection, incident_id: str) -> datetime:
    incident = incidents.get(conn, incident_id)

    assert incident is not None and incident.ended_at is not None

    return incident.ended_at


def _the_incident_still_ended_at(conn: psycopg.Connection,
                                 incident_id: str,
                                 moment: datetime) -> Assertion[bool]:
    """The end an incident already had is not restamped by a second withdrawal.

    How long an incident lasted is a figure Argus reports, and a withdrawal
    that re-stamped it would stretch that figure by however long it took
    somebody to press the button twice.
    """
    def assertion(_withdrawn: bool) -> bool:
        incident = incidents.get(conn, incident_id)

        if incident is None:
            raise AssertionError(f"No incident found with id [{incident_id}].")

        if incident.ended_at != moment:
            raise AssertionError(
                f"Expected incident [{incident_id}] to still record its end at "
                f"[{moment}], got [{incident.ended_at}]."
            )

        return True

    return assertion
