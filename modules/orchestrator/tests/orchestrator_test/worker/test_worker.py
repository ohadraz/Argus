from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta

import psycopg
import pytest
from argus_core.db import connect
from argus_core.models.actor import Actor
from argus_core.models.alert import Alert
from argus_core.models.incident_status import IncidentStatus
from argus_testkit import Assertion, Scenario, all_of
from orchestrator import worker
from orchestrator.repository import incidents, runs
from orchestrator.withdrawal import wanted_via

A_GENEROUS_LEASE = timedelta(minutes=5)


@pytest.mark.integration
def test_a_queued_run_is_walked_and_settled_by_the_worker() -> None:
    # Nobody is waiting on an answer: the alert was acknowledged minutes ago
    # and its connection is long closed. What proves the walk happened is the
    # run's own state afterwards, which is the only record anything has.
    dont_care_alert = Alert(service="kuki-service", alert_name="HighErrorRate")
    dont_care_worker = "a-worker"
    walked: list[str] = []

    def walk_recording_what_it_was_given(incident_id: str) -> None:
        walked.append(incident_id)

    with connect() as conn:
        incident_id = incidents.create(conn, dont_care_alert)
        runs.enqueue(conn, incident_id)

        Scenario() \
            .given(
                incident_id
            ) \
            .when(
                worker.take_one_run(
                    conn,
                    dont_care_worker,
                    A_GENEROUS_LEASE,
                    walk=walk_recording_what_it_was_given,
                    unwind=_an_unwind_recording_what_it_was_given([]),
                    still_wanted=wanted_via(connect)
                )
            ) \
            .then(all_of(
                _the_worker_reports_it_took_work(),
                _the_incident_walked_was(walked, incident_id),
                _the_run_is_done(conn, incident_id)
            ))


@pytest.mark.integration
def test_a_worker_with_nothing_to_take_says_so_rather_than_walking() -> None:
    # The idle case, which is most of Argus's life. A worker that answered the
    # same way whether or not it found work would either sleep through a queued
    # incident or spin against an empty queue.
    dont_care_worker = "a-worker"

    def walk_that_must_not_be_called(incident_id: str) -> None:
        raise AssertionError(
            f"Expected nothing to be walked with an empty queue, got "
            f"[{incident_id}]."
        )

    with connect() as conn:
        Scenario() \
            .when(
                worker.take_one_run(
                    conn,
                    dont_care_worker,
                    A_GENEROUS_LEASE,
                    walk=walk_that_must_not_be_called,
                    unwind=_an_unwind_recording_what_it_was_given([]),
                    still_wanted=wanted_via(connect)
                )
            ) \
            .then(
                _the_worker_reports_it_found_nothing()
            )


@pytest.mark.integration
def test_a_run_whose_walk_failed_is_recorded_as_failed_with_its_reason() -> None:
    # A walk can fail for reasons that have nothing to do with the incident -
    # the model refusing, an MCP server down, a bug in a node. What must not
    # happen is that it looks like an incident still being worked: the queue is
    # the only record anything has, and a silent failure there is an incident
    # nobody knows stopped.
    dont_care_alert = Alert(service="kuki-service", alert_name="HighErrorRate")
    dont_care_worker = "a-worker"
    what_went_wrong = "the read MCP server refused the connection"

    def walk_that_fails(dont_care_incident_id: str) -> None:
        raise RuntimeError(what_went_wrong)

    with connect() as conn:
        incident_id = incidents.create(conn, dont_care_alert)
        runs.enqueue(conn, incident_id)

        Scenario() \
            .given(
                incident_id
            ) \
            .when(
                worker.take_one_run(
                    conn,
                    dont_care_worker,
                    A_GENEROUS_LEASE,
                    walk=walk_that_fails,
                    unwind=_an_unwind_recording_what_it_was_given([]),
                    still_wanted=wanted_via(connect)
                )
            ) \
            .then(all_of(
                _the_run_is_failed(conn, incident_id, what_went_wrong),
                _the_incident_was_not_called_resolved(conn, incident_id)
            ))


@pytest.mark.integration
def test_a_run_whose_incident_was_withdrawn_is_never_walked() -> None:
    # Withdrawn before anybody took it. Walking it would start an investigation
    # into an incident a human already has in hand - and `run_incident`'s first
    # act is to mark it `investigating`, which would take a finished incident
    # and put it back on the board.
    dont_care_alert = Alert(service="kuki-service", alert_name="HighErrorRate")
    dont_care_worker = "a-worker"
    dont_care_actor = Actor.HUMAN
    walked: list[str] = []

    def walk_recording_what_it_was_given(incident_id: str) -> None:
        walked.append(incident_id)

    with connect() as conn:
        incident_id = incidents.create(conn, dont_care_alert)
        runs.enqueue(conn, incident_id)

        Scenario() \
            .given(
                incidents.withdraw(conn, incident_id, dont_care_actor)
            ) \
            .when(
                worker.take_one_run(
                    conn,
                    dont_care_worker,
                    A_GENEROUS_LEASE,
                    walk=walk_recording_what_it_was_given,
                    still_wanted=wanted_via(connect),
                    unwind=_an_unwind_recording_what_it_was_given([])
                )
            ) \
            .then(all_of(
                _the_worker_reports_it_took_work(),
                _nothing_was_walked(walked),
                _the_run_is_done(conn, incident_id)
            ))


@pytest.mark.integration
def test_a_withdrawn_incident_has_its_changes_put_back() -> None:
    # The other half of stopping. A walk halted mid-flight has left production
    # in a state it chose for a reason that no longer applies, and the run is
    # not finished until that is put back.
    dont_care_alert = Alert(service="buki-service", alert_name="HighErrorRate")
    dont_care_worker = "a-worker"
    dont_care_actor = Actor.HUMAN
    unwound: list[str] = []

    with connect() as conn:
        incident_id = incidents.create(conn, dont_care_alert)
        runs.enqueue(conn, incident_id)

        Scenario() \
            .given(
                incidents.withdraw(conn, incident_id, dont_care_actor)
            ) \
            .when(
                worker.take_one_run(
                    conn,
                    dont_care_worker,
                    A_GENEROUS_LEASE,
                    walk=_a_walk_that_must_not_be_called(),
                    unwind=_an_unwind_recording_what_it_was_given(unwound),
                    still_wanted=wanted_via(connect)
                )
            ) \
            .then(
                _the_incident_unwound_was(unwound, incident_id)
            )


@pytest.mark.integration
def test_an_incident_withdrawn_while_it_was_walked_is_unwound_afterwards() -> None:
    # The ordinary case, and the reason the question is asked twice: the walk
    # was live when it was claimed and stopped somewhere in the middle, so
    # nothing before it started could have known.
    dont_care_alert = Alert(service="muki-service", alert_name="HighErrorRate")
    dont_care_worker = "a-worker"
    dont_care_actor = Actor.HUMAN
    unwound: list[str] = []

    with connect() as conn:
        incident_id = incidents.create(conn, dont_care_alert)
        runs.enqueue(conn, incident_id)

        def walk_that_is_withdrawn_partway(withdrawn_id: str) -> None:
            incidents.withdraw(conn, withdrawn_id, dont_care_actor)

        Scenario() \
            .given(
                incident_id
            ) \
            .when(
                worker.take_one_run(
                    conn,
                    dont_care_worker,
                    A_GENEROUS_LEASE,
                    walk=walk_that_is_withdrawn_partway,
                    unwind=_an_unwind_recording_what_it_was_given(unwound),
                    still_wanted=wanted_via(connect)
                )
            ) \
            .then(all_of(
                _the_incident_unwound_was(unwound, incident_id),
                _the_run_is_done(conn, incident_id)
            ))


def _the_run_is_failed(conn: psycopg.Connection,
                       incident_id: str,
                       reason: str) -> Assertion[bool]:
    def assertion(_took_work: bool) -> bool:
        run = runs.get_run_for_incident(conn, incident_id)

        if run is None:
            raise AssertionError(f"No run found for incident [{incident_id}].")

        if run.state != runs.RunState.FAILED:
            raise AssertionError(
                f"Expected the run to be recorded as [{runs.RunState.FAILED}], "
                f"got [{run.state}]."
            )

        if run.failure_reason is None or reason not in run.failure_reason:
            raise AssertionError(
                f"Expected the recorded reason to say [{reason}], got "
                f"[{run.failure_reason}]."
            )

        return True

    return assertion


def _the_incident_was_not_called_resolved(conn: psycopg.Connection,
                                          incident_id: str) -> Assertion[bool]:
    def assertion(_took_work: bool) -> bool:
        incident = incidents.get(conn, incident_id)

        if incident is None:
            raise AssertionError(f"No incident found with id [{incident_id}].")

        if incident.status == IncidentStatus.RESOLVED:
            raise AssertionError(
                "Expected an incident whose walk failed not to be recorded as "
                "resolved."
            )

        return True

    return assertion


def _the_worker_reports_it_took_work() -> Assertion[bool]:
    def assertion(took_work: bool) -> bool:
        if took_work is not True:
            raise AssertionError(
                f"Expected the worker to report it took a run, got [{took_work!r}]."
            )

        return True

    return assertion


def _the_worker_reports_it_found_nothing() -> Assertion[bool]:
    def assertion(took_work: bool) -> bool:
        if took_work is not False:
            raise AssertionError(
                f"Expected the worker to report an empty queue, got [{took_work!r}]."
            )

        return True

    return assertion


def _the_incident_walked_was(walked: list[str], incident_id: str) -> Assertion[bool]:
    def assertion(_took_work: bool) -> bool:
        if walked != [incident_id]:
            raise AssertionError(
                f"Expected the worker to walk incident [{incident_id}] exactly "
                f"once, got {walked}."
            )

        return True

    return assertion


def _the_run_is_done(conn: psycopg.Connection, incident_id: str) -> Assertion[bool]:
    def assertion(_took_work: bool) -> bool:
        run = runs.get_run_for_incident(conn, incident_id)

        if run is None:
            raise AssertionError(f"No run found for incident [{incident_id}].")

        if run.state != runs.RunState.DONE:
            raise AssertionError(
                f"Expected the walked run to be settled as "
                f"[{runs.RunState.DONE}], got [{run.state}]."
            )

        if run.claimed_by is not None:
            raise AssertionError(
                f"Expected a settled run to be held by nobody, got "
                f"[{run.claimed_by}]."
            )

        return True

    return assertion


def _a_walk_that_must_not_be_called() -> Callable[[str], None]:
    def walk(incident_id: str) -> None:
        raise AssertionError(
            f"Expected a withdrawn incident not to be walked, got [{incident_id}]."
        )

    return walk


def _an_unwind_recording_what_it_was_given(unwound: list[str]) -> Callable[[str], None]:
    def unwind(incident_id: str) -> None:
        unwound.append(incident_id)

    return unwind


def _nothing_was_walked(walked: list[str]) -> Assertion[bool]:
    def assertion(_took_work: bool) -> bool:
        if walked:
            raise AssertionError(
                f"Expected a withdrawn incident not to be walked, got {walked}."
            )

        return True

    return assertion


def _the_incident_unwound_was(unwound: list[str],
                              incident_id: str) -> Assertion[bool]:
    def assertion(_took_work: bool) -> bool:
        if unwound != [incident_id]:
            raise AssertionError(
                f"Expected incident [{incident_id}] to be unwound exactly once, "
                f"got {unwound}."
            )

        return True

    return assertion
