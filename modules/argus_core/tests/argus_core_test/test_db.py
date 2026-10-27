"""Where a connection to Argus's own database comes from, for a process that
walks runs.

A worker's pool hands out connections to whatever inside a walk asks - a node, a
repository, the checkpointer, a thread LangGraph started - and none of them knows
which run it is writing for. The pool does: it fences every connection as it is
handed out with the run the process holds at that moment, so a connection that
held one run's fence and went back to the pool never carries it into the next.
"""

from __future__ import annotations

from typing import Any

import psycopg
import pytest
from argus_core import (
    DatabaseSettings,
    Fence,
    Holding,
    connect_from_env,
    get_settings,
    open_pool,
)
from argus_testkit import Assertion, Scenario, calling
from psycopg_pool import ConnectionPool

# What a worker's connections are called. Stated rather than imported, for the
# reason `test_fencing` gives.
THE_WORKER = "argus-worker"

# Refused because a worker wrote without saying which run it writes for.
NO_RUN_HELD = "AR002"


@pytest.mark.integration
@pytest.mark.parametrize("handed_out_by", ["connection", "getconn"])
def test_a_connection_is_fenced_with_the_run_held_as_it_is_handed_out(
    handed_out_by: str, a_clean_database: None
) -> None:
    # The run is taken back between the two, so a connection still carrying the
    # first claim's fence is refused the second write. Both ways out of the
    # pool: a checkpointer is free to take one with `getconn`.
    holding = Holding()

    with open_pool(DatabaseSettings.of(get_settings()), holding=holding) as pool:
        Scenario() \
            .given(
                the_first_claim := _a_run_held_at(epoch=3)
            ) \
            .when(
                lambda: _written_for_each_claim_in_turn(pool, holding, handed_out_by,
                                                        the_first_claim)
            ) \
            .then(
                _each_write_was_made()
            )


@pytest.mark.integration
def test_a_connection_handed_out_while_no_run_is_held_is_refused_a_write(
    a_clean_database: None
) -> None:
    # The run before it settled and its fence came down, and nothing walks now:
    # whatever writes through this connection writes for no run, and is told so.
    holding = Holding()

    with open_pool(DatabaseSettings.of(get_settings()), holding=holding) as pool:
        Scenario() \
            .given(
                some_run := _a_run_held_at(epoch=3),
                calling(lambda: _written_for(pool, holding, "connection", some_run))
            ) \
            .when(
                lambda: _attempted_outside_any_run(pool)
            ) \
            .then(
                _refused_as(NO_RUN_HELD)
            )


@pytest.mark.integration
def test_a_pool_that_fences_its_connections_names_them_as_a_workers(
    a_clean_database: None
) -> None:
    # The name is what the database refuses an unfenced write by, so a pool
    # that fences and did not name its connections would let through the very
    # write the fence is for.
    with open_pool(DatabaseSettings.of(get_settings()), holding=Holding()) as pool:
        Scenario() \
            .when(
                lambda: _the_application_named_by(pool)
            ) \
            .then(
                _the_application_is(THE_WORKER)
            )


@pytest.mark.integration
def test_a_pool_opened_for_a_caller_with_wants_of_its_own_meets_them(
    a_clean_database: None
) -> None:
    # The checkpointer writes without transactions of its own, and asks for
    # connections that commit as they go.
    with open_pool(DatabaseSettings.of(get_settings()),
                   holding=Holding(),
                   connection={"autocommit": True}) as pool:
        Scenario() \
            .when(
                lambda: _committing_as_it_goes(pool)
            ) \
            .then(
                _the_answer_is(True)
            )


def _a_run_held_at(epoch: int) -> Fence:
    """An incident with a run a worker holds, written here rather than claimed,
    for the reason `test_fencing` gives."""
    with connect_from_env() as conn, conn.cursor() as cursor:
        cursor.execute("INSERT INTO incident (alert_payload, status, created_at) "
                       "VALUES ('{}', 'investigating', now()) RETURNING id")
        incident = cursor.fetchone()
        assert incident is not None
        cursor.execute("INSERT INTO incident_run (incident_id, state, claimed_by, leased_until, "
                       "epoch) VALUES (%s, 'running', 'some-worker', now() + interval '5 minutes', "
                       "%s) RETURNING id", (incident[0], epoch))
        run = cursor.fetchone()
        assert run is not None
        conn.commit()

    return Fence(run_id=str(run[0]), epoch=epoch)


def _written_for_each_claim_in_turn(pool: ConnectionPool,
                                    holding: Holding,
                                    handed_out_by: str,
                                    first: Fence) -> list[Exception | None]:
    """A write for `first`, then the run taken back, then a write for the claim
    that took it - what the database answered each."""
    made_first = _written_for(pool, holding, handed_out_by, first)

    with connect_from_env() as conn:
        conn.execute("UPDATE incident_run SET epoch = epoch + 1 WHERE id = %s", (first.run_id,))

    taken_back = Fence(run_id=first.run_id, epoch=first.epoch + 1)

    return [made_first, _written_for(pool, holding, handed_out_by, taken_back)]


def _written_for(pool: ConnectionPool,
                 holding: Holding,
                 handed_out_by: str,
                 held: Fence) -> Exception | None:
    """A write for `held`, on a connection handed out while it is the run held -
    and only the database's answer to say whose it was."""
    with holding.of(held):
        try:
            if handed_out_by == "connection":
                with pool.connection() as conn:
                    _a_write_on(conn)
            else:
                conn = pool.getconn()
                try:
                    _a_write_on(conn)
                finally:
                    pool.putconn(conn)
        except psycopg.Error as error:
            return error

    return None


def _attempted_outside_any_run(pool: ConnectionPool) -> Exception | None:
    try:
        with pool.connection() as conn:
            _a_write_on(conn)
    except psycopg.Error as error:
        return error

    return None


def _a_write_on(conn: psycopg.Connection) -> None:
    """A row in a table nothing else in these tests writes, so that the fence is
    the only thing that can refuse it - and one per write, so none collides."""
    conn.execute("INSERT INTO event_cursor (reader, seq) VALUES (gen_random_uuid()::text, 0)")
    conn.commit()


def _the_application_named_by(pool: ConnectionPool) -> str:
    with pool.connection() as conn:
        return conn.info.parameter_status("application_name") or ""


def _committing_as_it_goes(pool: ConnectionPool) -> bool:
    with pool.connection() as conn:
        return conn.autocommit


def _each_write_was_made() -> Assertion[Any]:
    def assertion(refusals: Any) -> bool:
        if any(refusal is not None for refusal in refusals):
            raise AssertionError(
                f"Expected each write made for the run held as its connection was "
                f"handed out, and the database answered {refusals}."
            )

        return True

    return assertion


def _refused_as(sqlstate: str) -> Assertion[Exception | None]:
    def assertion(error: Exception | None) -> bool:
        found = error.sqlstate if isinstance(error, psycopg.Error) else None

        if found != sqlstate:
            raise AssertionError(
                f"Expected the write refused by the database as [{sqlstate}], got "
                f"[{found}] from [{type(error).__name__}: {error}]."
            )

        return True

    return assertion


def _the_application_is(expected: str) -> Assertion[Any]:
    def assertion(named: Any) -> bool:
        if named != expected:
            raise AssertionError(
                f"Expected the pool's connections named [{expected}], got [{named}]."
            )

        return True

    return assertion


def _the_answer_is(expected: bool) -> Assertion[Any]:
    def assertion(answer: Any) -> bool:
        if answer is not expected:
            raise AssertionError(f"Expected [{expected}], got [{answer}].")

        return True

    return assertion
