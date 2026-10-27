"""Keeping a walk whose run was taken back from writing as though it still held it.

A worker paused past its lease wakes holding a run somebody else took back, and
nothing in the worker can know that before it writes. The database can: every
claim moves the run's epoch on, a connection says which run and epoch it writes
for, and every table but the run's own refuses a write whose run has moved on.
So these are about what the database does with a connection, and they ask a
live one.
"""

from __future__ import annotations

from typing import Any

import psycopg
import pytest
from argus_core import Fence, Holding, RunLost, connect_from_env, fence, get_settings, was_lost
from argus_testkit import Assertion, Scenario, all_of, attempting, calling

# What a worker's connections are called, and so what the database refuses a
# write from when it names no run. Stated here rather than imported: it is the
# one word the worker and the schema agree on, and a test sharing the constant
# would pass through a change that broke the agreement.
THE_WORKER = "argus-worker"

# Refused because the run the write was made for is somebody else's now.
RUN_LOST = "AR001"

# Refused because a worker wrote without saying which run it writes for.
NO_RUN_HELD = "AR002"

# How long a write waits on another's lock before it is refused instead. Only
# ever spent where the fence locked too much, so a passing test never waits it.
A_MOMENT_TO_WAIT_FOR_A_LOCK = "500ms"

# The two tables a write is never refused on: the queue that says who holds
# what, which a worker that lost its run has to be able to read and lose a
# renewal on, and Alembic's own record of the chain.
NEVER_FENCED = {"incident_run", "alembic_version"}


@pytest.mark.integration
def test_a_write_for_the_run_as_it_is_held_now_is_made(a_clean_database: None) -> None:
    with _a_connection_named(THE_WORKER) as conn:
        Scenario() \
            .given(
                held := _a_run_held_at(epoch=3),
                calling(lambda: fence(conn, held))
            ) \
            .when(attempting(lambda: _a_write_on(conn))) \
            .then(
                _nothing_was_refused()
            )


@pytest.mark.integration
def test_a_write_for_a_claim_since_taken_back_is_refused_as_a_lost_run(
    a_clean_database: None
) -> None:
    # The paused worker wakes holding epoch 3, and the run has moved on to 4.
    with _a_connection_named(THE_WORKER) as conn:
        Scenario() \
            .given(
                held := _a_run_held_at(epoch=3),
                calling(lambda: fence(conn, held)),
                calling(lambda: _the_run_taken_back(held))
            ) \
            .when(attempting(lambda: _a_write_on(conn))) \
            .then(all_of(
                _refused_as(RUN_LOST),
                _told_as_a_lost_run()
            ))


@pytest.mark.integration
def test_a_write_for_a_run_already_settled_is_refused_as_a_lost_run(
    a_clean_database: None
) -> None:
    # Settled under this very claim: a run that finished is nobody's, and a write
    # made for it after the fact would land on an incident nothing is walking.
    with _a_connection_named(THE_WORKER) as conn:
        Scenario() \
            .given(
                held := _a_run_held_at(epoch=3),
                calling(lambda: fence(conn, held)),
                calling(lambda: _the_run_settled(held))
            ) \
            .when(attempting(lambda: _a_write_on(conn))) \
            .then(all_of(
                _refused_as(RUN_LOST),
                _told_as_a_lost_run()
            ))


@pytest.mark.integration
@pytest.mark.parametrize("cleared", [False, True], ids=["never-fenced", "fence-cleared"])
def test_a_workers_write_that_names_no_run_is_refused(
    cleared: bool, a_clean_database: None
) -> None:
    # A connection a worker forgot to fence, and one whose fence was taken down
    # after its run: either is a walk writing for no run at all, which is a bug
    # in the worker rather than a run somebody else took - so it is not told as
    # one.
    with _a_connection_named(THE_WORKER) as conn:
        Scenario() \
            .given(
                held := _a_run_held_at(epoch=3),
                calling(lambda: _fenced_then_cleared(conn, held) if cleared else None)
            ) \
            .when(attempting(lambda: _a_write_on(conn))) \
            .then(all_of(
                _refused_as(NO_RUN_HELD),
                _not_told_as_a_lost_run()
            ))


@pytest.mark.integration
def test_a_write_from_anything_but_a_worker_names_no_run_and_is_made(
    a_clean_database: None
) -> None:
    # The web process, the relay, the index and the schema job walk no run, and
    # write all the same.
    with _a_connection_named("argus-web") as conn:
        Scenario() \
            .given(
                _a_run_held_at(epoch=3)
            ) \
            .when(attempting(lambda: _a_write_on(conn))) \
            .then(
                _nothing_was_refused()
            )


@pytest.mark.integration
def test_a_fence_is_in_place_before_anything_is_written_under_it(
    a_clean_database: None
) -> None:
    # Committed as it is put up. A fence left in an open transaction would be
    # taken down again by the first rollback, and the write after it made for
    # no run.
    with _a_connection_named(THE_WORKER) as conn:
        Scenario() \
            .given(
                held := _a_run_held_at(epoch=3)
            ) \
            .when(
                lambda: fence(conn, held)
            ) \
            .then(all_of(
                _no_transaction_is_left_open(conn),
                _it_survives_a_rollback(conn)
            ))


@pytest.mark.integration
def test_two_writes_for_the_same_claim_are_made_side_by_side(a_clean_database: None) -> None:
    # A write holds the run only against its being taken back, never against
    # the walk's own other writes: a node's write and the checkpoint saved
    # beside it are two connections for one claim, and neither waits on the
    # other.
    with (
        _a_connection_named(THE_WORKER) as first,
        _a_connection_named(THE_WORKER) as second
    ):
        Scenario() \
            .given(
                held := _a_run_held_at(epoch=3),
                calling(lambda: _both_fenced(first, second, held))
            ) \
            .when(
                lambda: _while_another_write_for_it_is_open(first, second)
            ) \
            .then(
                _nothing_was_refused()
            )


@pytest.mark.integration
@pytest.mark.parametrize("told", ["as-the-cause", "while-handling-it"])
def test_a_lost_runs_refused_write_is_recognised_inside_whatever_raised_it(
    told: str, a_clean_database: None
) -> None:
    Scenario() \
        .given(
            error := _a_lost_runs_refusal_told(told)
        ) \
        .when(
            lambda: was_lost(error)
        ) \
        .then(
            _the_answer_is(True)
        )


@pytest.mark.integration
def test_every_table_a_walk_can_write_is_fenced(postgres: None) -> None:
    # The table added next is fenced by nobody remembering to: one that is not
    # fails here, rather than taking a stale walk's writes in silence.
    with connect_from_env() as conn:
        Scenario() \
            .when(
                lambda: _the_tables_without_a_fence(conn)
            ) \
            .then(
                _only_these_are_unfenced(NEVER_FENCED)
            )


@pytest.mark.unit
@pytest.mark.parametrize("told", ["directly", "as-the-cause", "while-handling-it"])
def test_a_lost_run_is_recognised_however_it_reached_the_caller(told: str) -> None:
    # A store refusing a write raises inside whatever was writing, and that is
    # often caught and raised again as something of its own.
    Scenario() \
        .given(
            error := _a_lost_run_told(told)
        ) \
        .when(
            lambda: was_lost(error)
        ) \
        .then(
            _the_answer_is(True)
        )


@pytest.mark.unit
def test_a_failure_that_says_nothing_of_the_run_is_not_a_lost_run() -> None:
    Scenario() \
        .given(
            error := RuntimeError("some failure nobody planned for")
        ) \
        .when(
            lambda: was_lost(error)
        ) \
        .then(
            _the_answer_is(False)
        )


@pytest.mark.unit
def test_a_run_is_held_only_for_as_long_as_it_is_walked() -> None:
    some_fence = Fence(run_id="6f1c1d2e-0000-4000-8000-000000000001", epoch=3)
    holding = Holding()
    seen: list[Fence | None] = []

    def walked_until_it_fails() -> None:
        with holding.of(some_fence):
            seen.append(holding.current())

            raise RuntimeError("dont care")

    Scenario() \
        .given(
            calling(lambda: seen.append(holding.current()))
        ) \
        .when(attempting(walked_until_it_fails)) \
        .then(
            lambda _: _held_in_turn(seen + [holding.current()], [None, some_fence, None])
        )


def _a_connection_named(application: str) -> psycopg.Connection:
    return psycopg.connect(get_settings().database_url, application_name=application)


def _a_run_held_at(epoch: int) -> Fence:
    """An incident with a run a worker holds, its epoch at `epoch` - written
    here rather than claimed, because the queue belongs to a module the kernel
    cannot see."""
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


def _the_run_taken_back(held: Fence) -> None:
    with connect_from_env() as conn:
        conn.execute("UPDATE incident_run SET epoch = epoch + 1, claimed_by = 'another-worker' "
                     "WHERE id = %s", (held.run_id,))


def _the_run_settled(held: Fence) -> None:
    with connect_from_env() as conn:
        conn.execute("UPDATE incident_run SET state = 'done', claimed_by = NULL, "
                     "leased_until = NULL WHERE id = %s", (held.run_id,))


def _fenced_then_cleared(conn: psycopg.Connection, held: Fence) -> None:
    fence(conn, held)
    fence(conn, None)


def _a_write_on(conn: psycopg.Connection) -> None:
    """A write to a table the incident does not own, so that the fence is the
    only thing that can refuse it."""
    _a_rate_written_on(conn, "EUR")
    conn.commit()


def _a_rate_written_on(conn: psycopg.Connection, currency: str) -> None:
    """The same write, its transaction left open - one row per currency, so two
    of them never wait on each other's row."""
    conn.execute("INSERT INTO exchange_rate (base, currency, published_on, per_unit) "
                 "VALUES ('USD', %s, current_date, 0.92)", (currency,))


def _while_another_write_for_it_is_open(first: psycopg.Connection,
                                        second: psycopg.Connection) -> Exception | None:
    """A write on `second` while one on `first` is still open, bounded so that
    waiting on `first` is a refusal rather than a hang."""
    _a_rate_written_on(first, "EUR")

    try:
        second.execute(f"SET lock_timeout = '{A_MOMENT_TO_WAIT_FOR_A_LOCK}'")
        return attempting(lambda: _a_rate_committed_on(second, "GBP"))()
    finally:
        first.rollback()


def _both_fenced(first: psycopg.Connection, second: psycopg.Connection, held: Fence) -> None:
    fence(first, held)
    fence(second, held)


def _a_rate_committed_on(conn: psycopg.Connection, currency: str) -> None:
    _a_rate_written_on(conn, currency)
    conn.commit()


def _a_lost_runs_refusal_told(told: str) -> Exception:
    """The database's own refusal of a write for a claim since taken back, as the
    caller meets it: the cause a wrapper names, or what the wrapper was raised
    while handling."""
    with _a_connection_named(THE_WORKER) as conn:
        held = _a_run_held_at(epoch=3)
        fence(conn, held)
        _the_run_taken_back(held)
        refused = attempting(lambda: _a_write_on(conn))()
        assert isinstance(refused, psycopg.Error)

    wrapped = RuntimeError("the node could not record its finding")

    if told == "as-the-cause":
        wrapped.__cause__ = refused
    else:
        wrapped.__context__ = refused

    return wrapped


def _the_tables_without_a_fence(conn: psycopg.Connection) -> set[str]:
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public' "
            "EXCEPT "
            "SELECT DISTINCT c.relname FROM pg_trigger t "
            "JOIN pg_class c ON c.oid = t.tgrelid "
            "JOIN pg_proc p ON p.oid = t.tgfoid "
            "WHERE p.proname = 'argus_fence' "
            # Before the write and once per statement, for every kind of write:
            # a fence that let a DELETE or a TRUNCATE through is one a stale walk
            # gets round. Postgres's own bits: 1 a row trigger, 2 a before one,
            # then insert, delete, update and truncate.
            "AND t.tgtype & 1 = 0 "
            "AND t.tgtype & 2 = 2 "
            "AND t.tgtype & (4 | 8 | 16 | 32) = (4 | 8 | 16 | 32)"
        )

        return {name for (name,) in cursor.fetchall()}


def _a_lost_run_told(told: str) -> Exception:
    """A lost run as the caller meets it: itself, the cause a wrapper names, or
    what the wrapper was raised while handling."""
    lost = RunLost("a newer claim holds this run")

    if told == "directly":
        return lost

    wrapped = RuntimeError("the node could not record its finding")

    if told == "as-the-cause":
        wrapped.__cause__ = lost
    else:
        wrapped.__context__ = lost

    return wrapped


def _nothing_was_refused() -> Assertion[Exception | None]:
    def assertion(error: Exception | None) -> bool:
        if error is not None:
            raise AssertionError(
                f"Expected the write to be made, and it was refused: "
                f"[{type(error).__name__}: {error}]."
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


def _told_as_a_lost_run() -> Assertion[Exception | None]:
    def assertion(error: Exception | None) -> bool:
        if error is None or not was_lost(error):
            raise AssertionError(
                f"Expected the refusal to be told as a lost run, and it was not: "
                f"[{type(error).__name__}: {error}]."
            )

        return True

    return assertion


def _not_told_as_a_lost_run() -> Assertion[Exception | None]:
    def assertion(error: Exception | None) -> bool:
        if error is not None and was_lost(error):
            raise AssertionError(
                f"Expected a write naming no run not to be told as a lost run, and it "
                f"was: [{type(error).__name__}: {error}]."
            )

        return True

    return assertion


def _no_transaction_is_left_open(conn: psycopg.Connection) -> Assertion[Any]:
    def assertion(_: Any) -> bool:
        status = conn.info.transaction_status

        if status != psycopg.pq.TransactionStatus.IDLE:
            raise AssertionError(
                f"Expected nothing left open once the fence was up, and the connection "
                f"was [{status.name}]."
            )

        return True

    return assertion


def _it_survives_a_rollback(conn: psycopg.Connection) -> Assertion[Any]:
    """A transaction opened after the fence and rolled back, then a write."""
    def assertion(_: Any) -> bool:
        conn.execute("SELECT 1")
        conn.rollback()
        error = attempting(lambda: _a_write_on(conn))()

        if error is not None:
            raise AssertionError(
                f"Expected the fence still up after a rollback, and the write was "
                f"refused: [{type(error).__name__}: {error}]."
            )

        return True

    return assertion


def _only_these_are_unfenced(expected: set[str]) -> Assertion[Any]:
    def assertion(unfenced: Any) -> bool:
        if unfenced != expected:
            raise AssertionError(
                f"Expected every table but {sorted(expected)} fenced against every "
                f"write, once per statement and before it; unfenced were "
                f"{sorted(unfenced)}."
            )

        return True

    return assertion


def _the_answer_is(expected: bool) -> Assertion[Any]:
    def assertion(answer: Any) -> bool:
        if answer is not expected:
            raise AssertionError(f"Expected [{expected}], got [{answer}].")

        return True

    return assertion


def _held_in_turn(seen: list[Fence | None], expected: list[Fence | None]) -> bool:
    if seen != expected:
        raise AssertionError(
            f"Expected nothing held before the walk, its run during it and nothing "
            f"after, {expected}; got {seen}."
        )

    return True
