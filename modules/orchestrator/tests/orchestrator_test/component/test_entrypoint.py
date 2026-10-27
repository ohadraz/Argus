from __future__ import annotations

import logging
from typing import Any
from unittest.mock import create_autospec

import psycopg
import psycopg.sql
import pytest
from argus_core import connect_from_env, get_settings, utc_now
from argus_core.events import StatusChanged
from argus_core.models import Alert, IncidentStatus
from argus_core.schema import reset_schema
from argus_core.telemetry import (
    ARGUS_INCIDENT_ID,
    ARGUS_INCIDENT_OUTCOME,
    ARGUS_INCIDENT_WALK_DURATION,
    ARGUS_INCIDENT_WALKS,
)
from argus_incidents.repository import events, incidents
from argus_testkit import one_record_was_logged
from argus_testkit.assertions import Assertion, all_of
from argus_testkit.scenario import Scenario, calling
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph.state import CompiledStateGraph
from opentelemetry import trace
from orchestrator import entrypoint
from psycopg.rows import dict_row

from orchestrator_test.framework.observing import Observed, attributes_of, observing

# Where the schema job puts every table, LangGraph's among them.
THE_SCHEMA = "public"

# Where LangGraph's own setup is run to be compared against it, and dropped
# after.
A_SCRATCH_SCHEMA = "langgraph_setup"


@pytest.mark.component
def test_a_walk_announces_the_investigation_before_the_graph_runs(
    a_clean_database: None
) -> None:
    # The incident stops being one nobody is on at the moment a worker takes
    # it, not at the moment the alert arrived. Asserted against the published
    # account as well as the status, because the gap between the incident's own
    # created_at and that line is what says how long it waited for a worker.
    dont_care_alert = Alert(service="kuki-service", alert_name="HighErrorRate")
    a_graph = create_autospec(CompiledStateGraph, instance=True)

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, dont_care_alert, at=utc_now())
        conn.commit()  # the walk reads it back on a connection of its own

        Scenario() \
            .given(
                incident_id
            ) \
            .when(
                lambda: entrypoint.run_incident(
                    incident_id, connect_from_env, graph_of=lambda: a_graph
                )
            ) \
            .then(all_of(
                _the_incident_is_investigating(conn, incident_id),
                _the_account_records_the_investigation_starting(conn, incident_id)
            ))


@pytest.mark.component
def test_a_walk_withdrawn_before_it_started_announces_no_investigation(
    a_clean_database: None
) -> None:
    # Withdrawn between the worker asking and the walk starting. The row stays
    # withdrawn, and the account must not say otherwise: a line announcing an
    # investigation of an incident nobody wants is one a reader would act on.
    dont_care_alert = Alert(service="muki-service", alert_name="HighErrorRate")
    a_graph = create_autospec(CompiledStateGraph, instance=True)

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, dont_care_alert, at=utc_now())
        incidents.withdraw(conn, incident_id, at=utc_now())  # commits, so the walk reads it back

        Scenario() \
            .given(
                incident_id
            ) \
            .when(
                lambda: entrypoint.run_incident(
                    incident_id, connect_from_env, graph_of=lambda: a_graph
                )
            ) \
            .then(
                _the_account_never_says_it_was_taken_up(conn, incident_id)
            )


@pytest.mark.component
def test_a_walk_invokes_the_graph_on_the_incidents_own_thread(a_clean_database: None) -> None:
    # This is what makes the resume above a resume rather than a restart: the
    # thread is the incident, so the checkpointer answers with whatever that
    # incident already reached. A walk that invoked the graph on a fresh thread
    # would replay a whole investigation and call it recovery.
    dont_care_alert = Alert(service="buki-service", alert_name="HighErrorRate")
    a_graph = create_autospec(CompiledStateGraph, instance=True)

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, dont_care_alert, at=utc_now())
        conn.commit()  # the walk reads it back on a connection of its own

        Scenario() \
            .given(
                incident_id
            ) \
            .when(
                lambda: entrypoint.run_incident(
                    incident_id, connect_from_env, graph_of=lambda: a_graph
                )
            ) \
            .then(all_of(
                _the_graph_was_invoked(a_graph),
                _the_thread_it_was_invoked_on_was(a_graph, incident_id),
                _the_state_it_started_from_is_the_incidents(a_graph, incident_id),
            ))


@pytest.mark.component
def test_a_walk_is_one_span_the_graph_runs_inside(a_clean_database: None) -> None:
    # The root of the walk's trace. Every step's span hangs from it, and so
    # every model call and tool call the walk made - which is what lets a
    # reader start from an incident and see the whole of what Argus did.
    dont_care_alert = Alert(service="kuki-service", alert_name="HighErrorRate")
    a_graph = create_autospec(CompiledStateGraph, instance=True)
    a_walk = _a_walk_ending_at(IncidentStatus.MITIGATED)
    a_graph.invoke.side_effect = a_walk
    observed = observing()

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, dont_care_alert, at=utc_now())
        conn.commit()  # the walk reads it back on a connection of its own

        Scenario() \
            .given(
                incident_id
            ) \
            .when(
                lambda: entrypoint.run_incident(
                    incident_id, connect_from_env, graph_of=lambda: a_graph,
                    tracer=observed.tracer, meter=observed.meter
                )
            ) \
            .then(all_of(
                _the_walk_span_names(observed, incident_id),
                _the_graph_ran_inside_the_walk_span(observed, a_walk)
            ))


@pytest.mark.component
def test_a_walk_is_counted_and_timed_by_how_the_incident_ended(
    a_clean_database: None
) -> None:
    # On an injected clock, so the duration is exact rather than however long
    # a mocked graph took to return.
    dont_care_alert = Alert(service="buki-service", alert_name="HighErrorRate")
    a_graph = create_autospec(CompiledStateGraph, instance=True)
    a_graph.invoke.side_effect = _a_walk_ending_at(IncidentStatus.ESCALATED)
    some_seconds_walked = 42.5
    observed = observing()

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, dont_care_alert, at=utc_now())
        conn.commit()  # the walk reads it back on a connection of its own

        Scenario() \
            .given(
                incident_id
            ) \
            .when(
                lambda: entrypoint.run_incident(
                    incident_id, connect_from_env, graph_of=lambda: a_graph,
                    tracer=observed.tracer, meter=observed.meter,
                    clock=_a_clock_reading(0.0, some_seconds_walked)
                )
            ) \
            .then(all_of(
                _one_walk_counted(observed, ended="escalated"),
                _one_walk_timed(observed, ended="escalated", seconds=some_seconds_walked)
            ))


@pytest.mark.component
def test_a_walk_is_logged_as_it_starts_and_as_it_ends(
    a_clean_database: None, caplog: pytest.LogCaptureFixture
) -> None:
    # How the incident ended and how long it took, on the line that says so -
    # the two things asked of every walk afterwards.
    dont_care_alert = Alert(service="kuki-service", alert_name="HighErrorRate")
    a_graph = create_autospec(CompiledStateGraph, instance=True)
    a_graph.invoke.side_effect = _a_walk_ending_at(IncidentStatus.ESCALATED)
    some_seconds_walked = 42.5

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, dont_care_alert, at=utc_now())
        conn.commit()  # the walk reads it back on a connection of its own

        Scenario() \
            .given(
                calling(lambda: caplog.set_level(logging.INFO)),
                incident_id
            ) \
            .when(
                lambda: entrypoint.run_incident(
                    incident_id, connect_from_env, graph_of=lambda: a_graph,
                    clock=_a_clock_reading(0.0, some_seconds_walked)
                )
            ) \
            .then(all_of(
                one_record_was_logged(caplog, "orchestrator.entrypoint", logging.INFO,
                                      "walk started"),
                one_record_was_logged(caplog, "orchestrator.entrypoint", logging.INFO,
                                      "walk ended",
                                      values={"outcome": "escalated",
                                              "duration_s": some_seconds_walked})
            ))


@pytest.mark.component
def test_the_schema_holds_the_checkpointers_tables_as_its_own_setup_would_leave_them(
    postgres: None
) -> None:
    # The graph is compiled against tables the schema job made, and never sets
    # them up itself: a worker applying DDL would be a service doing the job's
    # work, and an unfenced one. So the job's copy has to be what LangGraph's
    # own setup makes - and the day an upgrade adds a step, this says so before
    # a walk finds out.
    with connect_from_env() as conn:
        Scenario() \
            .given(
                calling(lambda: reset_schema(conn))
            ) \
            .when(
                lambda: (_the_checkpoint_tables_in(conn, THE_SCHEMA),
                         _the_checkpoint_tables_as_its_own_setup_leaves_them())
            ) \
            .then(
                _the_same_tables()
            )


def _the_checkpoint_tables_as_its_own_setup_leaves_them() -> dict[str, list[Any]]:
    """LangGraph's own setup, run in a schema of its own and described, and the
    schema dropped after."""
    with psycopg.connect(get_settings().database_url, autocommit=True) as conn:
        conn.execute(f"DROP SCHEMA IF EXISTS {A_SCRATCH_SCHEMA} CASCADE")
        conn.execute(f"CREATE SCHEMA {A_SCRATCH_SCHEMA}")

        try:
            with psycopg.connect(get_settings().database_url, autocommit=True,
                                 prepare_threshold=0, row_factory=dict_row,
                                 options=f"-c search_path={A_SCRATCH_SCHEMA}") as its_own:
                PostgresSaver(its_own).setup()

            return _the_checkpoint_tables_in(conn, A_SCRATCH_SCHEMA)
        finally:
            conn.execute(f"DROP SCHEMA {A_SCRATCH_SCHEMA} CASCADE")


def _the_checkpoint_tables_in(conn: psycopg.Connection, schema: str) -> dict[str, list[Any]]:
    """Every column, key and index of the checkpointer's tables in `schema`, and
    the steps of LangGraph's setup the schema says were applied - each spelt
    without the schema's name, so two schemas can be compared."""
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT table_name, column_name, data_type, is_nullable, column_default "
            "FROM information_schema.columns "
            "WHERE table_schema = %s AND table_name LIKE 'checkpoint%%' "
            "ORDER BY table_name, column_name", (schema,)
        )
        columns = cursor.fetchall()
        cursor.execute(
            "SELECT tablename, indexname, replace(indexdef, %s, '') FROM pg_indexes "
            "WHERE schemaname = %s AND tablename LIKE 'checkpoint%%' "
            "ORDER BY tablename, indexname", (f"{schema}.", schema)
        )
        indexes = cursor.fetchall()
        cursor.execute(
            psycopg.sql.SQL("SELECT v FROM {}.checkpoint_migrations ORDER BY v").format(
                psycopg.sql.Identifier(schema)
            )
        )
        applied = cursor.fetchall()

    return {"columns": columns, "indexes": indexes, "applied": applied}


def _the_same_tables() -> Assertion[Any]:
    def assertion(ours_then_theirs: Any) -> bool:
        ours, theirs = ours_then_theirs
        differing = [part for part in theirs if ours[part] != theirs[part]]

        if differing:
            raise AssertionError(
                f"Expected the schema's checkpoint tables as LangGraph's own setup leaves "
                f"them; they differ in {differing}. Ours: "
                f"{ {part: ours[part] for part in differing} }; LangGraph's: "
                f"{ {part: theirs[part] for part in differing} }."
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


def _the_account_records_the_investigation_starting(conn: psycopg.Connection,
                                                    incident_id: str) -> Assertion[None]:
    """The one line this step is responsible for.

    Not the alert arriving: that is published by the intake, and this case
    creates its incident directly to get at the entrypoint on its own. What is
    under test is that taking a run up is accounted for at all - a walk that
    started silently leaves a reader looking at an incident that was
    acknowledged and then simply changed.
    """
    def assertion(_result: None) -> bool:
        moves = [event.to_status
                 for event in events.get_by_incident(conn, incident_id)
                 if isinstance(event, StatusChanged)]

        if moves != [IncidentStatus.INVESTIGATING]:
            raise AssertionError(
                f"Expected the account to record the start of the investigation "
                f"[{IncidentStatus.INVESTIGATING}], got {moves}.")

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


def _the_account_never_says_it_was_taken_up(conn: psycopg.Connection,
                                            incident_id: str) -> Assertion[None]:
    def assertion(_result: None) -> bool:
        moves = [event.to_status
                 for event in events.get_by_incident(conn, incident_id)
                 if isinstance(event, StatusChanged)]

        if IncidentStatus.INVESTIGATING in moves:
            raise AssertionError(
                f"Expected the account to announce no investigation of an incident "
                f"that was withdrawn before its walk started, got {moves}.")

        return True

    return assertion


class _AWalkEndingAt:
    """A graph's `invoke` that ends at `status`, remembering the span it ran inside.

    What LangGraph hands back for a Pydantic state is a mapping of its fields,
    so that is what this returns. An object rather than a function, because
    what it saw has to be read back once the walk is over.
    """

    def __init__(self, status: IncidentStatus) -> None:
        self._status = status
        self.ran_inside: int | None = None

    def __call__(self, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
        self.ran_inside = trace.get_current_span().get_span_context().span_id

        return {"status": self._status}


def _a_walk_ending_at(status: IncidentStatus) -> _AWalkEndingAt:
    return _AWalkEndingAt(status)


def _a_clock_reading(*seconds: float) -> Any:
    """A clock that reads each of these in turn, so a duration is exact."""
    readings = iter(seconds)

    def clock() -> float:
        return next(readings)

    return clock


def _the_walk_span_names(observed: Observed, incident_id: str) -> Assertion[Any]:
    def assertion(_result: Any) -> bool:
        span = observed.only_span()
        said = (span.name, (span.attributes or {}).get(ARGUS_INCIDENT_ID))

        if said != ("walk", incident_id):
            raise AssertionError(
                f"Expected one span named [walk] for incident [{incident_id}], "
                f"and it was (name, incident) {said}."
            )

        return True

    return assertion


def _the_graph_ran_inside_the_walk_span(observed: Observed,
                                        the_walk: _AWalkEndingAt) -> Assertion[Any]:
    def assertion(_result: Any) -> bool:
        walk = observed.only_span().get_span_context()
        ran_inside = the_walk.ran_inside

        if walk is None or ran_inside != walk.span_id:
            raise AssertionError(
                f"Expected the graph to run inside the walk's span "
                f"[{walk.span_id if walk is not None else None}], and it ran inside "
                f"[{ran_inside}]."
            )

        return True

    return assertion


def _one_walk_counted(observed: Observed, ended: str) -> Assertion[Any]:
    def assertion(_result: Any) -> bool:
        counted = [(attributes_of(point), point.value)
                   for point in observed.counter_points_of(ARGUS_INCIDENT_WALKS)]

        if counted != [({ARGUS_INCIDENT_OUTCOME: ended}, 1)]:
            raise AssertionError(
                f"Expected one walk counted as [{ended}], and the count was {counted}."
            )

        return True

    return assertion


def _one_walk_timed(observed: Observed, ended: str, seconds: float) -> Assertion[Any]:
    def assertion(_result: Any) -> bool:
        timed = [(attributes_of(point), point.count, point.sum)
                 for point in observed.histogram_points_of(ARGUS_INCIDENT_WALK_DURATION)]

        if timed != [({ARGUS_INCIDENT_OUTCOME: ended}, 1, seconds)]:
            raise AssertionError(
                f"Expected one walk timed at [{seconds}]s as [{ended}], and the "
                f"timings were {timed}."
            )

        return True

    return assertion
