from __future__ import annotations

from datetime import timedelta
from typing import Any
from unittest.mock import create_autospec

import psycopg
import pytest
from argus_core.models.alert import Alert
from argus_core.models.incident_status import IncidentStatus
from argus_testkit import Assertion, Scenario, all_of
from langgraph.graph.state import CompiledStateGraph
from orchestrator import entrypoint, worker
from orchestrator.repository import incidents, runs, timeline

DATABASE_URL = "postgresql://argus:argus@localhost:5432/argus"

A_GENEROUS_LEASE = timedelta(minutes=5)

# A lease already over by the time it is written: the state a worker that was
# killed mid-walk leaves behind, arranged rather than waited for.
A_LEASE_ALREADY_OVER = timedelta(seconds=-1)


@pytest.mark.integration
def test_a_walk_announces_the_investigation_before_the_graph_runs() -> None:
    # The incident stops being one nobody is on at the moment a worker takes
    # it, not at the moment the alert arrived. Asserted against the timeline as
    # well as the status, because the duration between the two rows is what
    # says how long the incident waited for a worker.
    dont_care_alert = Alert(service="kuki-service", alert_name="HighErrorRate")
    a_graph = create_autospec(CompiledStateGraph, instance=True)

    with psycopg.connect(DATABASE_URL) as conn:
        incident_id = incidents.create(conn, dont_care_alert)

        Scenario() \
            .given(
                incident_id
            ) \
            .when(
                lambda: entrypoint.run_incident(
                    incident_id, graph_of=lambda: a_graph
                )
            ) \
            .then(all_of(
                _the_incident_is_investigating(conn, incident_id),
                _the_timeline_records_the_investigation_starting(conn, incident_id),
            ))


@pytest.mark.integration
def test_a_run_abandoned_mid_walk_is_taken_up_for_the_same_incident() -> None:
    # The failure this exists to prevent is not "the run is lost" but "the run
    # is done twice": an incident picked up as a new one would investigate a
    # fault already investigated and mitigate one already mitigated. So what is
    # asserted is that the second worker walks the *same* incident, and that
    # nothing new was created for it to walk.
    dont_care_alert = Alert(service="kuki-service", alert_name="HighErrorRate")
    the_worker_that_stopped = "worker-that-was-killed-mid-walk"
    the_worker_that_came_after = "worker-that-started-next"
    walked: list[str] = []

    def walk_recording_what_it_was_given(incident_id: str) -> None:
        walked.append(incident_id)

    with psycopg.connect(DATABASE_URL) as conn:
        incident_id = incidents.create(conn, dont_care_alert)
        runs.enqueue(conn, incident_id)

        Scenario() \
            .given(
                runs.claim(conn, the_worker_that_stopped, A_LEASE_ALREADY_OVER)
            ) \
            .when(
                worker.take_one_run(
                    conn,
                    the_worker_that_came_after,
                    A_GENEROUS_LEASE,
                    walk=walk_recording_what_it_was_given,
                )
            ) \
            .then(all_of(
                _the_incident_walked_was(walked, incident_id),
                _only_one_incident_exists(conn),
                _only_one_run_exists(conn),
            ))


@pytest.mark.integration
def test_a_walk_invokes_the_graph_on_the_incidents_own_thread() -> None:
    # This is what makes the resume above a resume rather than a restart: the
    # thread is the incident, so the checkpointer answers with whatever that
    # incident already reached. A walk that invoked the graph on a fresh thread
    # would replay a whole investigation and call it recovery.
    dont_care_alert = Alert(service="buki-service", alert_name="HighErrorRate")
    a_graph = create_autospec(CompiledStateGraph, instance=True)

    with psycopg.connect(DATABASE_URL) as conn:
        incident_id = incidents.create(conn, dont_care_alert)

        Scenario() \
            .given(
                incident_id
            ) \
            .when(
                lambda: entrypoint.run_incident(
                    incident_id, graph_of=lambda: a_graph
                )
            ) \
            .then(all_of(
                _the_graph_was_invoked(a_graph),
                _the_thread_it_was_invoked_on_was(a_graph, incident_id),
                _the_state_it_started_from_is_the_incidents(a_graph, incident_id),
            ))


def _the_incident_is_investigating(conn: psycopg.Connection,
                                   incident_id: str) -> Assertion[Any]:
    def assertion(_result: Any) -> bool:
        incident = incidents.get(conn, incident_id)

        if incident is None:
            raise AssertionError(f"No incident found with id [{incident_id}].")

        if incident.status != IncidentStatus.INVESTIGATING:
            raise AssertionError(
                f"Expected a claimed run to leave its incident "
                f"[{IncidentStatus.INVESTIGATING}], got [{incident.status}]."
            )

        return True

    return assertion


def _the_timeline_records_the_investigation_starting(conn: psycopg.Connection, 
                                                     incident_id: str) -> Assertion[Any]:
    def assertion(_result: Any) -> bool:
        recorded = [event.to_status
                    for event in timeline.get_timeline_events(conn, incident_id)]

        if recorded != [IncidentStatus.ACKNOWLEDGED, IncidentStatus.INVESTIGATING]:
            raise AssertionError(
                f"Expected the timeline to record the wait and then the start "
                f"[{IncidentStatus.ACKNOWLEDGED}, {IncidentStatus.INVESTIGATING}], "
                f"got {recorded}."
            )

        return True

    return assertion


def _the_incident_walked_was(walked: list[str], incident_id: str) -> Assertion[Any]:
    def assertion(_took_work: Any) -> bool:
        if walked != [incident_id]:
            raise AssertionError(
                f"Expected the abandoned run to be taken up for incident "
                f"[{incident_id}] exactly once, got {walked}."
            )

        return True

    return assertion


def _only_one_incident_exists(conn: psycopg.Connection) -> Assertion[Any]:
    def assertion(_took_work: Any) -> bool:
        with conn.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM incident")
            row = cursor.fetchone()

        if row is None or row[0] != 1:
            raise AssertionError(
                f"Expected the resumed incident to be the only one, got "
                f"{row[0] if row else 'no'} incidents."
            )

        return True

    return assertion


def _only_one_run_exists(conn: psycopg.Connection) -> Assertion[Any]:
    def assertion(_took_work: Any) -> bool:
        with conn.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM incident_run")
            row = cursor.fetchone()

        if row is None or row[0] != 1:
            raise AssertionError(
                f"Expected the abandoned run to be taken up rather than "
                f"replaced, got {row[0] if row else 'no'} runs."
            )

        return True

    return assertion


def _the_graph_was_invoked(a_graph: Any) -> Assertion[Any]:
    def assertion(_result: Any) -> bool:
        if not a_graph.invoke.called:
            raise AssertionError("Expected the walk to invoke the graph, it did not.")

        return True

    return assertion


def _the_thread_it_was_invoked_on_was(a_graph: Any, incident_id: str) -> Assertion[Any]:
    def assertion(_result: Any) -> bool:
        thread_id = a_graph.invoke.call_args.kwargs["config"]["configurable"]["thread_id"]

        if thread_id != incident_id:
            raise AssertionError(
                f"Expected the graph to be invoked on the incident's own thread "
                f"[{incident_id}], got [{thread_id}]."
            )

        return True

    return assertion


def _the_state_it_started_from_is_the_incidents(a_graph: Any,
                                                incident_id: str) -> Assertion[Any]:
    def assertion(_result: Any) -> bool:
        state = a_graph.invoke.call_args.args[0]

        if state.incident_id != incident_id:
            raise AssertionError(
                f"Expected the walk to start from incident [{incident_id}]'s own "
                f"state, got [{state.incident_id}]."
            )

        return True

    return assertion
