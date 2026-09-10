from __future__ import annotations

from typing import Any
from unittest.mock import create_autospec

import psycopg
import pytest
from argus_core.db import connect
from argus_core.models.alert import Alert
from argus_core.models.incident_status import IncidentStatus
from argus_incidents.repository import incidents, timeline
from argus_testkit.assertions import Assertion, all_of
from argus_testkit.scenario import Scenario
from langgraph.graph.state import CompiledStateGraph
from orchestrator import entrypoint


@pytest.mark.component
def test_a_walk_announces_the_investigation_before_the_graph_runs(
    a_clean_database: None
) -> None:
    # The incident stops being one nobody is on at the moment a worker takes
    # it, not at the moment the alert arrived. Asserted against the timeline as
    # well as the status, because the duration between the two rows is what
    # says how long the incident waited for a worker.
    dont_care_alert = Alert(service="kuki-service", alert_name="HighErrorRate")
    a_graph = create_autospec(CompiledStateGraph, instance=True)

    with connect() as conn:
        incident_id = incidents.create(conn, dont_care_alert)

        Scenario() \
            .given(
                incident_id
            ) \
            .when(
                lambda: entrypoint.run_incident(
                    incident_id, connect, graph_of=lambda: a_graph
                )
            ) \
            .then(all_of(
                _the_incident_is_investigating(conn, incident_id),
                _the_timeline_records_the_investigation_starting(conn, incident_id),
            ))


@pytest.mark.component
def test_a_walk_invokes_the_graph_on_the_incidents_own_thread(a_clean_database: None) -> None:
    # This is what makes the resume above a resume rather than a restart: the
    # thread is the incident, so the checkpointer answers with whatever that
    # incident already reached. A walk that invoked the graph on a fresh thread
    # would replay a whole investigation and call it recovery.
    dont_care_alert = Alert(service="buki-service", alert_name="HighErrorRate")
    a_graph = create_autospec(CompiledStateGraph, instance=True)

    with connect() as conn:
        incident_id = incidents.create(conn, dont_care_alert)

        Scenario() \
            .given(
                incident_id
            ) \
            .when(
                lambda: entrypoint.run_incident(
                    incident_id, connect, graph_of=lambda: a_graph
                )
            ) \
            .then(all_of(
                _the_graph_was_invoked(a_graph),
                _the_thread_it_was_invoked_on_was(a_graph, incident_id),
                _the_state_it_started_from_is_the_incidents(a_graph, incident_id),
            ))


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


def _the_graph_was_invoked(a_graph: Any) -> Assertion[Any]:
    def assertion(_result: Any) -> bool:
        if not a_graph.invoke.called:
            raise AssertionError("Expected the walk to invoke the graph, it did not.")

        return True

    return assertion


def _the_timeline_records_the_investigation_starting(conn: psycopg.Connection,
                                                     incident_id: str) -> Assertion[None]:
    def assertion(_result: None) -> bool:
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


def _the_incident_is_investigating(conn: psycopg.Connection,
                                   incident_id: str) -> Assertion[None]:
    def assertion(_result: None) -> bool:
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
