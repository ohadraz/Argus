from __future__ import annotations

from datetime import timedelta
from typing import Any

import psycopg
import pytest
from argus_core.models.alert import Alert
from argus_core.models.incident_status import IncidentStatus
from argus_testkit import Assertion, Scenario, all_of
from orchestrator import worker
from orchestrator.repository import incidents, runs

DATABASE_URL = "postgresql://argus:argus@localhost:5432/argus"

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

    with psycopg.connect(DATABASE_URL) as conn:
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
                )
            ) \
            .then(all_of(
                _the_worker_reports_it_took_work(),
                _the_incident_walked_was(walked, incident_id),
                _the_run_is_done(conn, incident_id),
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

    with psycopg.connect(DATABASE_URL) as conn:
        Scenario() \
            .when(
                worker.take_one_run(
                    conn,
                    dont_care_worker,
                    A_GENEROUS_LEASE,
                    walk=walk_that_must_not_be_called,
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

    with psycopg.connect(DATABASE_URL) as conn:
        incident_id = incidents.create(conn, dont_care_alert)
        runs.enqueue(conn, incident_id)

        Scenario() \
            .given(
                incident_id
            ) \
            .when(
                worker.take_one_run(
                    conn, dont_care_worker, A_GENEROUS_LEASE, walk=walk_that_fails
                )
            ) \
            .then(all_of(
                _the_run_is_failed(conn, incident_id, what_went_wrong),
                _the_incident_was_not_called_resolved(conn, incident_id),
            ))


def _the_run_is_failed(conn: psycopg.Connection,
                       incident_id: str,
                       reason: str) -> Assertion[Any]:
    def assertion(_took_work: Any) -> bool:
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
                                          incident_id: str) -> Assertion[Any]:
    def assertion(_took_work: Any) -> bool:
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


def _the_worker_reports_it_took_work() -> Assertion[Any]:
    def assertion(took_work: Any) -> bool:
        if took_work is not True:
            raise AssertionError(
                f"Expected the worker to report it took a run, got [{took_work!r}]."
            )

        return True

    return assertion


def _the_worker_reports_it_found_nothing() -> Assertion[Any]:
    def assertion(took_work: Any) -> bool:
        if took_work is not False:
            raise AssertionError(
                f"Expected the worker to report an empty queue, got [{took_work!r}]."
            )

        return True

    return assertion


def _the_incident_walked_was(walked: list[str], incident_id: str) -> Assertion[Any]:
    def assertion(_took_work: Any) -> bool:
        if walked != [incident_id]:
            raise AssertionError(
                f"Expected the worker to walk incident [{incident_id}] exactly "
                f"once, got {walked}."
            )

        return True

    return assertion


def _the_run_is_done(conn: psycopg.Connection, incident_id: str) -> Assertion[Any]:
    def assertion(_took_work: Any) -> bool:
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
