from __future__ import annotations

from datetime import datetime
from functools import partial
from typing import Any

import psycopg
import pytest
from argus_core import connect_from_env
from argus_core.models import Alert, Incident, IncidentStatus
from argus_incidents.repository import incidents
from argus_testkit import Assertion, Scenario, all_of, calling

from argus_incidents_test.framework import no_column_is_empty
from argus_incidents_test.framework.builders import an_incident_created_for


@pytest.mark.integration
def test_create_writes_the_incident_acknowledged() -> None:
    # `acknowledged`, not `investigating`: this runs where the alert is
    # received, and the walk it queues belongs to a worker that has not taken
    # it yet. The line saying the alert arrived is published by the intake
    # beside this, and asserted there.
    some_service = "kuki-service"
    some_alert_name = "HighErrorRate"
    some_alert = Alert(service=some_service, alert_name=some_alert_name)

    with connect_from_env() as conn:
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

    with connect_from_env() as conn:
        the_incident_is = partial(_the_incident_is, conn)

        Scenario() \
            .given(
                incident_id := an_incident_created_for(conn, some_alert)
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
    with connect_from_env() as conn:
        # Created first, so it is also the *older* of the two - which is what
        # makes this a claim about "has not finished" rather than about "newest".
        still_running = incidents.create(
            conn, Alert(service="running", alert_name="HighErrorRate")
        )
        already_finished = incidents.create(
            conn, Alert(service="finished", alert_name="HighErrorRate")
        )
        incidents.transition(conn, already_finished, IncidentStatus.RESOLVED)

        Scenario() \
            .given(
                still_running
            ) \
            .when(
                lambda: incidents.get_current(conn)
            ) \
            .then(
                _the_current_incident_was(still_running)
            )


@pytest.mark.integration
def test_get_current_falls_back_to_the_newest_when_nothing_is_running() -> None:
    # A resolved incident vanishing the moment it resolves would take it off the
    # screen exactly when everyone is looking at it.
    with connect_from_env() as conn:
        _no_incidents_at_all(conn)

        the_only_one_there_has_been = incidents.create(
            conn, Alert(service="io-shop", alert_name="HighErrorRate")
        )
        incidents.transition(conn, the_only_one_there_has_been, IncidentStatus.RESOLVED)

        Scenario() \
            .given(
                the_only_one_there_has_been
            ) \
            .when(
                lambda: incidents.get_current(conn)
            ) \
            .then(
                _the_current_incident_was(the_only_one_there_has_been)
            )


@pytest.mark.integration
def test_get_current_is_none_when_there_has_never_been_an_incident() -> None:
    # The state Argus is in most of the time, and the one the front page has to
    # say out loud rather than render as an empty frame.
    with connect_from_env() as conn:
        Scenario() \
            .given(
                calling(lambda: _no_incidents_at_all(conn))
            ) \
            .when(
                lambda: incidents.get_current(conn)
            ) \
            .then(
                _nothing_came_back()
            )


@pytest.mark.integration
def test_an_incident_that_resolved_records_when_it_ended() -> None:
    # How long an incident lasted is a figure the postmortem reports, so it is
    # recorded when it happens rather than inferred later from whichever row
    # was written last - an inference that changes silently the moment
    # anything is logged late.
    some_alert = Alert(service="kuki-service", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        the_incident_records_an_end = partial(_the_incident_records_an_end, conn)

        Scenario() \
            .given(
                incident_id := an_incident_created_for(conn, some_alert)
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

    with connect_from_env() as conn:
        the_incident_records_an_end = partial(_the_incident_records_an_end, conn)

        Scenario() \
            .given(
                incident_id := an_incident_created_for(conn, some_alert)
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

    with connect_from_env() as conn:
        the_incident_records_no_end = partial(_the_incident_records_no_end, conn)

        Scenario() \
            .given(
                incident_id := an_incident_created_for(conn, some_alert)
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


@pytest.mark.integration
def test_incidents_come_back_newest_first() -> None:
    # The history view opens on what just happened. Oldest-first would put the
    # incident somebody is looking for at the bottom of the page.
    an_older_alert = Alert(service="older-service", alert_name="HighErrorRate")
    a_newer_alert = Alert(service="newer-service", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        the_incidents_come_back = partial(_the_incidents_come_back, conn)

        older = an_incident_created_for(conn, an_older_alert)
        # `now()` is transaction time, so two incidents created in one
        # transaction share a timestamp and the ordering has nothing left to
        # break the tie - which is not how an incident is ever created.
        conn.commit()
        newer = an_incident_created_for(conn, a_newer_alert)

        Scenario() \
            .given(
                older, newer
            ) \
            .when(
                lambda: incidents.get_recent(conn)
            ) \
            .then(
                the_incidents_come_back(newest=newer, before=older)
            )


@pytest.mark.integration
def test_a_running_incident_can_be_withdrawn() -> None:
    # Withdrawal is the one status set from outside the walk. Everything else
    # an incident becomes is derived from work the walk did and written by the
    # walk itself; this is written by whoever pressed the button.
    some_alert = Alert(service="kuki-service", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        the_incident_is = partial(_the_incident_is, conn)
        the_incident_records_an_end = partial(_the_incident_records_an_end, conn)

        Scenario() \
            .given(
                incident_id := an_incident_created_for(conn, some_alert)
            ) \
            .when(
                lambda: incidents.withdraw(conn, incident_id)
            ) \
            .then(all_of(
                the_incident_is(IncidentStatus.WITHDRAWN, incident_id=incident_id),
                the_incident_records_an_end(incident_id)
            ))


@pytest.mark.integration
def test_withdrawing_says_that_it_took_effect() -> None:
    # The answer is what the endpoint reports back and what the walk's own
    # unwind is conditioned on, so a withdrawal that silently did nothing must
    # not read the same as one that stopped an incident.
    some_alert = Alert(service="buki-service", alert_name="HighErrorRate")

    with connect_from_env() as conn:

        Scenario() \
            .given(
                incident_id := an_incident_created_for(conn, some_alert)
            ) \
            .when(
                lambda: incidents.withdraw(conn, incident_id)
            ) \
            .then(
                _it_reported(True)
            )


@pytest.mark.integration
def test_an_incident_that_already_ended_is_not_withdrawn() -> None:
    # A resolved incident was resolved by a mitigation that is holding the
    # service up. Withdrawing it would put the failure back.
    some_alert = Alert(service="muki-service", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        a_resolved_incident_for = partial(_a_resolved_incident_for, conn)
        the_incident_is = partial(_the_incident_is, conn)

        Scenario() \
            .given(
                incident_id := a_resolved_incident_for(some_alert)
            ) \
            .when(
                lambda: incidents.withdraw(conn, incident_id)
            ) \
            .then(all_of(
                _it_reported(False),
                the_incident_is(IncidentStatus.RESOLVED, incident_id=incident_id)
            ))


@pytest.mark.integration
def test_withdrawing_twice_changes_nothing_the_second_time() -> None:
    # The page can be double-clicked and a teardown can withdraw what a case
    # already withdrew. Neither should write a second row, and neither should
    # move the end time the first one stamped.
    some_alert = Alert(service="tuki-service", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        a_withdrawn_incident_for = partial(_a_withdrawn_incident_for, conn)
        the_incident_is = partial(_the_incident_is, conn)
        the_incident_still_ended_at = partial(_the_incident_still_ended_at, conn)

        incident_id = a_withdrawn_incident_for(some_alert)

        Scenario() \
            .given(
                first_ended_at := _when_it_ended(conn, incident_id)
            ) \
            .when(
                lambda: incidents.withdraw(conn, incident_id)
            ) \
            .then(all_of(
                _it_reported(False),
                the_incident_is(IncidentStatus.WITHDRAWN, incident_id=incident_id),
                the_incident_still_ended_at(incident_id, first_ended_at)
            ))


def _no_incidents_at_all(conn: psycopg.Connection) -> None:
    """An empty table, which is the one state "the newest incident" cannot be
    set up into by adding a row."""
    with conn.cursor() as cursor:
        cursor.execute("TRUNCATE incident CASCADE")
    conn.commit()


@pytest.mark.integration
def test_get_returns_none_for_unknown_incident() -> None:
    with connect_from_env() as conn:
        Scenario() \
            .given(
                an_id_no_incident_was_ever_given := "00000000-0000-0000-0000-000000000000"
            ) \
            .when(
                lambda: incidents.get(conn, an_id_no_incident_was_ever_given)
            ) \
            .then(
                _nothing_came_back()
            )


@pytest.mark.integration
def test_an_incident_that_ended_leaves_no_column_of_its_row_empty() -> None:
    # Two writes, because no single one fills this row: the insert opens the
    # incident and the transition that ends it stamps when. Together they are
    # the complete life of an incident, and what comes of it is what every
    # reader of the table sees.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)

        Scenario() \
            .when(
                lambda: incidents.transition(conn, incident_id, IncidentStatus.RESOLVED)
            ) \
            .then(
                no_column_is_empty(conn, "incident", "id", incident_id)
            )


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


def _the_current_incident_was(expected: str) -> Assertion[Incident | None]:
    """Which incident a live view would open on.

    The absence is reported separately from the wrong choice, because the two
    are different failures: nothing current at all is a front page with no
    incident on it, where the wrong one is a front page confidently showing
    somebody the incident they did not come for.
    """
    def assertion(current: Incident | None) -> bool:
        if current is None:
            raise AssertionError(f"Expected incident [{expected}] to be current, got none.")

        if current.id != expected:
            raise AssertionError(
                f"Expected incident [{expected}] to be current, got [{current.id}]."
            )

        return True

    return assertion


def _nothing_came_back() -> Assertion[Incident | None]:
    """That the repository answered with an absence rather than a row.

    `None` rather than a falsy stand-in: every caller of these two reads asks
    `is None`, and an empty object would sail past that and be rendered as an
    incident with no fields.
    """
    def assertion(found: Incident | None) -> bool:
        if found is not None:
            raise AssertionError(f"Expected nothing to come back, got [{found}].")

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


def _the_incidents_come_back(conn: psycopg.Connection,
                             newest: str,
                             before: str) -> Assertion[Any]:
    """That one incident is listed before another, wherever the rest are.

    Relative rather than positional: `get_recent` answers with every incident
    there has ever been, so pinning the positions would be an assertion about
    whatever the tests before it left behind.
    """
    def assertion(_result: Any) -> bool:
        listed = [incident.id for incident in incidents.get_recent(conn)]

        for incident_id in (newest, before):
            if incident_id not in listed:
                raise AssertionError(f"Expected [{incident_id}] to come back at all.")

        if listed.index(newest) > listed.index(before):
            raise AssertionError(
                f"Expected [{newest}] before [{before}], the order was {listed}."
            )

        return True

    return assertion


def _a_resolved_incident_for(conn: psycopg.Connection, alert: Alert) -> str:
    incident_id = incidents.create(conn, alert)
    incidents.transition(
        conn,
        incident_id,
        IncidentStatus.RESOLVED,
    )

    return incident_id


def _a_withdrawn_incident_for(conn: psycopg.Connection, alert: Alert) -> str:
    incident_id = incidents.create(conn, alert)
    incidents.withdraw(conn, incident_id)

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
