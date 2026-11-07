"""The one question a walk asks about itself: has a person ended this incident,
and how.

Two people's endings and two answers, because the walk does opposite things
with them. A withdrawal sends it out at once and has its changes put back; a
resolution sends it on to remember and write the incident up, and puts nothing
back. A plain "no longer wanted" would have to be one of those, and either is
the wrong one half the time.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from argus_core import Fence, Holding, RunLost, connect_from_env, utc_now
from argus_core.models import Alert, IncidentStatus
from argus_incidents.ending import (
    EndedByAPerson,
    StillHeld,
    ended_by_a_person_via,
    still_held_via,
    wanted_until_a_person_ends_it,
)
from argus_incidents.repository import incidents, runs
from argus_testkit import Assertion, Scenario, an_error_was_raised, attempting, calling

DONT_CARE_INCIDENT_ID = "buki-123"

# The first claim's lease is over before it begins, which is what lets the
# second claim take the run back; the second's outlasts the test.
A_LEASE_ALREADY_OVER = timedelta(seconds=-1)
A_GENEROUS_LEASE = timedelta(minutes=5)


@pytest.mark.component
def test_an_incident_argus_is_working_on_was_ended_by_nobody(a_clean_database: None) -> None:
    some_alert = Alert(service="kuki-service", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert, at=utc_now())
        incidents.transition(conn, incident_id, IncidentStatus.MITIGATING, at=utc_now())
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
        incident_id = incidents.create(conn, some_alert, at=utc_now())
        incidents.transition(conn, incident_id, IncidentStatus.MITIGATED, at=utc_now())
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
        incident_id = incidents.create(conn, some_alert, at=utc_now())
        incidents.withdraw(conn, incident_id, at=utc_now())

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
        incident_id = incidents.create(conn, some_alert, at=utc_now())
        incidents.resolve(conn, incident_id, at=utc_now())

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
            lambda: wanted_until_a_person_ends_it(nobody_ended_it, _held(True))(
                DONT_CARE_INCIDENT_ID
            )
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
            lambda: wanted_until_a_person_ends_it(a_person_ended_it, _held(True))(
                DONT_CARE_INCIDENT_ID
            )
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
            lambda: wanted_until_a_person_ends_it(recording, _held(True))("some-incident")
        ) \
        .then(
            _it_asked_about(asked, "some-incident")
        )


@pytest.mark.unit
def test_an_incident_whose_run_was_taken_back_is_not_answered_but_told_lost() -> None:
    # Asked between model turns, so a walk that lost its run stops at its next
    # turn rather than paying for every turn left in its budget - and the
    # incident is not the question any more: the run is somebody else's.
    Scenario() \
        .given(
            nobody_ended_it := _an_ending_of(None),
            taken_back := _held(False)
        ) \
        .when(attempting(
            lambda: wanted_until_a_person_ends_it(nobody_ended_it, taken_back)(
                DONT_CARE_INCIDENT_ID
            )
        )) \
        .then(
            an_error_was_raised(RunLost)
        )


@pytest.mark.component
@pytest.mark.parametrize("taken_back", [False, True], ids=["still-its-claim", "taken-back"])
def test_a_run_is_still_held_while_its_claim_is_the_one_the_run_is_at(
    taken_back: bool, a_clean_database: None
) -> None:
    holding = Holding()

    Scenario() \
        .given(
            held := _a_claimed_run(),
            calling(lambda: _the_run_taken_back(held) if taken_back else None)
        ) \
        .when(
            lambda: _asked_while_holding(holding, held, still_held_via(connect_from_env, holding))
        ) \
        .then(
            _it_is_held(not taken_back)
        )


@pytest.mark.unit
def test_a_process_holding_no_run_has_none_to_lose() -> None:
    # A suite, or anything else asking with no run in hand: nothing is held,
    # so nothing was taken back, and the database is never asked.
    Scenario() \
        .given(
            holding := Holding()
        ) \
        .when(
            lambda: still_held_via(_no_connections_at_all, holding)()
        ) \
        .then(
            _it_is_held(True)
        )


def _held(still: bool) -> StillHeld:
    def still_held() -> bool:
        return still

    return still_held


def _a_claimed_run() -> Fence:
    """An incident whose run a worker has claimed, as the claim it holds."""
    some_alert = Alert(service="kuki-service", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert, at=utc_now())
        runs.enqueue(conn, incident_id)
        claimed = runs.claim(conn, "worker-that-was-paused", A_LEASE_ALREADY_OVER)
        assert claimed is not None

    return Fence(run_id=claimed.id, epoch=claimed.epoch)


def _the_run_taken_back(held: Fence) -> None:
    """Its lease already over, so the next worker to look takes it."""
    with connect_from_env() as conn:
        claimed = runs.claim(conn, "worker-that-came-after", A_GENEROUS_LEASE)
        assert claimed is not None and claimed.id == held.run_id


def _asked_while_holding(holding: Holding, held: Fence, still_held: StillHeld) -> bool:
    with holding.of(held):
        return still_held()


def _no_connections_at_all() -> Any:
    raise AssertionError("Expected nothing asked of the database, and it was.")


def _it_is_held(expected: bool) -> Assertion[bool]:
    def assertion(held: bool) -> bool:
        if held is not expected:
            raise AssertionError(
                f"Expected the run {"still" if expected else "no longer"} held by this "
                f"claim, got [{held!r}]."
            )

        return True

    return assertion


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
