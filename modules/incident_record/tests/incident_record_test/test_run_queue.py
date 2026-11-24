"""The queue between taking an alert and walking it, through its role.

The role is driven inside its caller's transaction, so what it owes is the
queue's own rules said on the caller's connection: a run waiting is claimed
once, a claim settled is settled for good, and a change is held only for the
claim that still holds the run. What the claim and the lease are made of is
the repository's suite's to say; this is the role answering for them.
"""

from __future__ import annotations

from contextlib import ExitStack
from datetime import timedelta

import psycopg
import pytest
from argus_testkit import Assertion, Scenario, all_of, calling, the_answer_was
from core import Fence, utc_now
from core.models import Alert, IncidentStatus
from incident_record import Run, incident_reads_on, run_queue_on
from incident_record.repository import incidents, runs
from postgres import connect_from_env

from incident_record_test.framework.connections import autocommitting

DONT_CARE_ALERT = Alert(service="kuki-service", alert_name="HighErrorRate")
SOME_WORKER = "worker-walking-it"
SOME_OTHER_WORKER = "another-worker"
# Long enough that nothing here expires on its own.
A_GENEROUS_LEASE = timedelta(minutes=5)


@pytest.mark.component
def test_a_run_waiting_is_claimed_once() -> None:
    with connect_from_env() as conn:
        incident_id = _an_incident_waiting_to_be_walked(conn)
        queue = run_queue_on(conn)

        Scenario() \
            .when(lambda: (queue.claim(SOME_WORKER, A_GENEROUS_LEASE),
                           queue.claim(SOME_OTHER_WORKER, A_GENEROUS_LEASE))) \
            .then(_only_the_first_claimed(incident_id))


@pytest.mark.component
def test_a_run_finished_is_no_longer_its_claims_to_renew() -> None:
    with connect_from_env() as conn:
        _an_incident_waiting_to_be_walked(conn)
        held = _claimed(conn)
        queue = run_queue_on(conn)

        Scenario() \
            .given(calling(lambda: queue.finish(held))) \
            .when(lambda: queue.renew(held, A_GENEROUS_LEASE)) \
            .then(the_answer_was(False))


@pytest.mark.component
def test_a_walk_that_stopped_escalates_an_incident_still_running() -> None:
    with connect_from_env() as conn:
        incident_id = _an_incident_waiting_to_be_walked(conn)

        Scenario() \
            .when(lambda: run_queue_on(conn).escalate_unless_ended(incident_id, at=utc_now())) \
            .then(all_of(
                the_answer_was(True),
                _the_incident_is(conn, incident_id, IncidentStatus.ESCALATED)
            ))


@pytest.mark.component
def test_a_change_is_held_for_the_claim_that_still_holds_the_run() -> None:
    # The write tier's connection says each statement as it goes, as the
    # tier's does: the run is held by the session, not by a transaction.
    with (
        connect_from_env() as conn,
        autocommitting(connect_from_env()) as the_tiers_conn,
        ExitStack() as the_change
    ):
        _an_incident_waiting_to_be_walked(conn)
        held = _claimed(conn)

        Scenario() \
            .when(lambda: the_change.enter_context(
                run_queue_on(the_tiers_conn).hold_for_a_change(
                    Fence(run_id=held.id, epoch=held.epoch)))) \
            .then(the_answer_was(True))


def _an_incident_waiting_to_be_walked(conn: psycopg.Connection) -> str:
    """An incident with a run waiting, committed - what intake leaves behind."""
    incident_id = incidents.create(conn, DONT_CARE_ALERT, at=utc_now())
    runs.enqueue(conn, incident_id)
    conn.commit()

    return incident_id


def _claimed(conn: psycopg.Connection) -> Run:
    """The run waiting, claimed by a worker and committed, as a worker commits
    its claim the moment it makes it."""
    held = run_queue_on(conn).claim(SOME_WORKER, A_GENEROUS_LEASE)
    assert held is not None, "Expected a run waiting to be claimed, and none was."
    conn.commit()

    return held


def _only_the_first_claimed(incident_id: str) -> Assertion[tuple[Run | None, Run | None]]:
    def assertion(claims: tuple[Run | None, Run | None]) -> bool:
        first, second = claims
        claimed = (first.incident_id if first is not None else None,
                   second.incident_id if second is not None else None)

        if claimed != (incident_id, None):
            raise AssertionError(
                f"Expected the first claim to take the run of {incident_id} and the "
                f"second to take none, and they took {claimed}."
            )

        return True

    return assertion


def _the_incident_is(conn: psycopg.Connection,
                     incident_id: str,
                     expected: IncidentStatus) -> Assertion[object]:
    def assertion(_answer: object) -> bool:
        incident = incident_reads_on(conn).incident(incident_id)
        status = incident.status if incident is not None else None

        if status != expected:
            raise AssertionError(f"Expected the incident to be {expected}, and it is {status}.")

        return True

    return assertion
