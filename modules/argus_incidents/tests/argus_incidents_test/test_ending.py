"""The one question a walk asks about itself: has a person ended this incident,
and how.

Two people's endings and two answers, because the walk does opposite things
with them. A withdrawal sends it out at once and has its changes put back; a
resolution sends it on to remember and write the incident up, and puts nothing
back. A plain "no longer wanted" would have to be one of those, and either is
the wrong one half the time.
"""

from __future__ import annotations

import pytest
from argus_core import connect_from_env
from argus_core.models import Alert, IncidentStatus
from argus_incidents.ending import (
    EndedByAPerson,
    ended_by_a_person_via,
    wanted_until_a_person_ends_it,
)
from argus_incidents.repository import incidents
from argus_testkit import Assertion, Scenario

DONT_CARE_INCIDENT_ID = "buki-123"


@pytest.mark.component
def test_an_incident_argus_is_working_on_was_ended_by_nobody(a_clean_database: None) -> None:
    some_alert = Alert(service="kuki-service", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)
        incidents.transition(conn, incident_id, IncidentStatus.MITIGATING)
        conn.commit()

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: ended_by_a_person_via(connect_from_env)(incident_id)
        ) \
        .then(
            _it_answers(None)
        )


@pytest.mark.component
def test_an_incident_argus_ended_itself_was_ended_by_nobody(a_clean_database: None) -> None:
    # Argus's own endings are not a person's. A mitigated incident read as
    # ended by somebody would have the walk skip the Code-Fix it goes on to.
    some_alert = Alert(service="buki-service", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)
        incidents.transition(conn, incident_id, IncidentStatus.MITIGATED)
        conn.commit()

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: ended_by_a_person_via(connect_from_env)(incident_id)
        ) \
        .then(
            _it_answers(None)
        )


@pytest.mark.component
def test_an_incident_somebody_withdrew_was_ended_by_a_withdrawal(a_clean_database: None) -> None:
    some_alert = Alert(service="muki-service", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)
        incidents.withdraw(conn, incident_id)

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: ended_by_a_person_via(connect_from_env)(incident_id)
        ) \
        .then(
            _it_answers(IncidentStatus.WITHDRAWN)
        )


@pytest.mark.component
def test_an_incident_somebody_resolved_was_ended_by_a_resolution(a_clean_database: None) -> None:
    some_alert = Alert(service="tuki-service", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)
        incidents.resolve(conn, incident_id)

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: ended_by_a_person_via(connect_from_env)(incident_id)
        ) \
        .then(
            _it_answers(IncidentStatus.RESOLVED)
        )


@pytest.mark.component
def test_an_incident_with_no_row_at_all_reads_as_withdrawn(a_clean_database: None) -> None:
    # Reading a missing incident as "carry on" is how a walk goes on writing
    # rows for something that no longer exists - which is the state a suite
    # leaves behind when it empties the database between cases. Withdrawn
    # rather than resolved, because a walk stopped by a withdrawal writes
    # nothing more, and one stopped by a resolution goes on to write a
    # postmortem for an incident that is not there.
    some_incident_id_nobody_created = "5ff3b8e4-6d2a-4b1e-9a77-0c9a1d2e3f40"

    Scenario() \
        .given(
            some_incident_id_nobody_created
        ) \
        .when(
            lambda: ended_by_a_person_via(connect_from_env)(some_incident_id_nobody_created)
        ) \
        .then(
            _it_answers(IncidentStatus.WITHDRAWN)
        )


@pytest.mark.unit
def test_an_incident_nobody_ended_is_still_wanted() -> None:
    # The yes-or-no the agents and the nodes ask between their steps. They
    # stop for either ending alike, so they need only whether there is one.
    Scenario() \
        .given(
            nobody_ended_it := _an_ending_of(None)
        ) \
        .when(
            lambda: wanted_until_a_person_ends_it(nobody_ended_it)(DONT_CARE_INCIDENT_ID)
        ) \
        .then(
            _it_is_wanted(True)
        )


@pytest.mark.unit
@pytest.mark.parametrize("ending", [IncidentStatus.WITHDRAWN, IncidentStatus.RESOLVED])
def test_an_incident_a_person_ended_is_no_longer_wanted(ending: IncidentStatus) -> None:
    # A resolution is as much a reason to stop the next step as a withdrawal
    # is. What happens after the stop differs, and is decided where the ending
    # itself is read.
    Scenario() \
        .given(
            a_person_ended_it := _an_ending_of(ending)
        ) \
        .when(
            lambda: wanted_until_a_person_ends_it(a_person_ended_it)(DONT_CARE_INCIDENT_ID)
        ) \
        .then(
            _it_is_wanted(False)
        )


@pytest.mark.unit
def test_the_question_asks_about_the_incident_it_was_asked_about() -> None:
    asked: list[str] = []

    Scenario() \
        .given(
            recording := _an_ending_recording_who_it_asks_about(asked)
        ) \
        .when(
            lambda: wanted_until_a_person_ends_it(recording)("some-incident")
        ) \
        .then(
            _it_asked_about(asked, "some-incident")
        )


def _an_ending_of(ending: IncidentStatus | None) -> EndedByAPerson:
    def ended_by_a_person(dont_care_incident_id: str, /) -> IncidentStatus | None:
        return ending

    return ended_by_a_person


def _an_ending_recording_who_it_asks_about(asked: list[str]) -> EndedByAPerson:
    def ended_by_a_person(incident_id: str, /) -> IncidentStatus | None:
        asked.append(incident_id)
        return None

    return ended_by_a_person


def _it_is_wanted(expected: bool) -> Assertion[bool]:
    def assertion(wanted: bool) -> bool:
        if wanted is not expected:
            raise AssertionError(
                f"Expected the incident {"still" if expected else "no longer"} wanted, "
                f"got [{wanted!r}]."
            )

        return True

    return assertion


def _it_asked_about(asked: list[str], incident_id: str) -> Assertion[bool]:
    def assertion(dont_care_wanted: bool) -> bool:
        if asked != [incident_id]:
            raise AssertionError(
                f"Expected one question about [{incident_id}], got {asked}."
            )

        return True

    return assertion


def _it_answers(expected: IncidentStatus | None) -> Assertion[IncidentStatus | None]:
    def assertion(ending: IncidentStatus | None) -> bool:
        if ending is not expected:
            raise AssertionError(
                f"Expected the incident to read as ended by [{expected}], got [{ending!r}]."
            )

        return True

    return assertion
