"""Where a connection to Argus's own database comes from, and the transaction a
caller holds on one.

A worker's pool hands out connections to whatever inside a walk asks - a node, a
repository, the checkpointer, a thread LangGraph started - and none of them knows
which run it is writing for. The pool does: it fences every connection as it is
handed out with the run the process holds at that moment, so a connection that
held one run's fence and went back to the pool never carries it into the next.

A pool is not opened on a database nobody prepared. Every process that holds
one opens it on the way up, so this is where the schema is checked once for all
of them - and a process with no pool asks on a connection of its own.

A unit of work is one connection and one transaction on it, committed once at
its end by whoever opened it - or not at all, where anything inside it failed.

A moment is one connection and one read-only transaction on it, in which every
read sees the database as it was at the first: what is committed elsewhere
meanwhile is not seen, and nothing is written. The connection leaves it as it
came, reading at the database's own isolation and free to write.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import nullcontext
from typing import Any, NamedTuple

import psycopg
import pytest
from argus_testkit import (
    Assertion,
    Scenario,
    all_of,
    an_error_was_raised,
    attempting,
    calling,
    eventually,
    the_same_error_reached_the_caller,
)
from core import DatabaseSettings, Fence, Holding, get_settings
from core.stored import ALERT, SHIPPED
from postgres import (
    Connections,
    SchemaNotApplied,
    at_one_moment,
    connect,
    connect_from_env,
    open_pool,
    require_schema_at,
    reset_schema,
    unit_of_work,
)
from psycopg.pq import TransactionStatus
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

# What a worker's connections are called. Stated rather than imported, for the
# reason `test_fencing` gives.
THE_WORKER = "argus-worker"

# The service the incident a run is held for is about: any will do.
DONT_CARE_SERVICE = "some-service"

# Refused because a worker wrote without saying which run it writes for.
NO_RUN_HELD = "AR002"

# The isolation Postgres reads at unless a transaction says otherwise, as
# `SHOW transaction_isolation` spells it.
THE_DATABASES_OWN_ISOLATION = "read committed"

# `SHOW transaction_read_only`'s answer for a transaction free to write.
FREE_TO_WRITE = "off"


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


@pytest.mark.integration
def test_a_pool_is_not_opened_on_a_database_with_no_schema(
    a_database_with_no_schema: None
) -> None:
    # Rather than opened, and the process left to fail on whatever it asks
    # first - which reports the cause to whoever happened to be using it.
    Scenario() \
        .when(
            attempting(lambda: open_pool(DatabaseSettings.of(get_settings())))
        ) \
        .then(
            an_error_was_raised(SchemaNotApplied)
        )


@pytest.mark.integration
def test_a_pool_not_opened_leaves_no_connection_behind(a_database_with_no_schema: None) -> None:
    # Closed on the way out of the refusal: nobody owns a pool that was never
    # handed back, and one left open would go on holding its connections.
    # A fenced pool's, because its connections carry a name to look for.
    Scenario() \
        .when(
            attempting(lambda: open_pool(DatabaseSettings.of(get_settings()), holding=Holding()))
        ) \
        .then(all_of(
            an_error_was_raised(SchemaNotApplied),
            eventually(_no_connection_is_named(THE_WORKER))
        ))


@pytest.mark.integration
def test_a_pool_whose_connections_hand_out_rows_by_name_is_opened(
    a_clean_database: None
) -> None:
    # The checkpointer's connections hand out rows by column name, and the
    # schema is asked after on one of the pool's own.
    Scenario() \
        .when(
            attempting(lambda: _opened_and_closed(connection={"row_factory": dict_row}))
        ) \
        .then(
            _nothing_was_raised()
        )


@pytest.mark.integration
def test_a_database_with_no_schema_is_refused_on_a_connection_of_its_own(
    a_database_with_no_schema: None
) -> None:
    # For a process that holds no pool, and would otherwise learn of the
    # missing schema at its first write.
    Scenario() \
        .when(
            attempting(lambda: require_schema_at(DatabaseSettings.of(get_settings())))
        ) \
        .then(
            an_error_was_raised(SchemaNotApplied)
        )


@pytest.mark.integration
def test_a_prepared_database_is_accepted_on_a_connection_of_its_own(postgres: None) -> None:
    # The other way round, and not a formality: a check that refused everything
    # would pass the test above and stop the tier.
    Scenario() \
        .when(
            attempting(lambda: require_schema_at(DatabaseSettings.of(get_settings())))
        ) \
        .then(
            _nothing_was_raised()
        )


@pytest.mark.integration
def test_what_a_unit_of_work_wrote_is_seen_by_every_connection_once_it_ends(
    a_clean_database: None
) -> None:
    # One commit, at the end, by whoever opened the unit - which is what lets
    # everything written inside it leave committing alone.
    some_reader = "some-reader"

    def a_cursor_kept_in_one() -> None:
        with unit_of_work(connect_from_env) as conn:
            _a_cursor_kept_by(conn, some_reader)

    Scenario() \
        .when(
            a_cursor_kept_in_one
        ) \
        .then(
            _the_readers_seen_from_another_connection_are([some_reader])
        )


@pytest.mark.integration
def test_a_unit_of_work_that_failed_leaves_nothing_it_wrote(a_clean_database: None) -> None:
    # Whole or not at all: a failure part-way through rolls back every row
    # written before it, and still reaches whoever opened the unit.
    dont_care_reader = "dont-care-reader"
    some_failure = RuntimeError("dont care")

    def a_cursor_kept_and_then_a_failure() -> None:
        with unit_of_work(connect_from_env) as conn:
            _a_cursor_kept_by(conn, dont_care_reader)
            raise some_failure

    Scenario() \
        .when(
            attempting(a_cursor_kept_and_then_a_failure)
        ) \
        .then(all_of(
            the_same_error_reached_the_caller(some_failure),
            _the_readers_seen_from_another_connection_are([])
        ))


@pytest.mark.integration
def test_a_unit_of_work_refuses_a_commit_made_inside_it(a_clean_database: None) -> None:
    # The unit commits once, at its end. Something inside it committing on its
    # own would make part of the unit permanent whatever became of the rest.
    dont_care_reader = "dont-care-reader"

    def a_cursor_kept_and_committed_inside_one() -> None:
        with unit_of_work(connect_from_env) as conn:
            _a_cursor_kept_by(conn, dont_care_reader)
            conn.commit()

    Scenario() \
        .when(
            attempting(a_cursor_kept_and_committed_inside_one)
        ) \
        .then(all_of(
            an_error_was_raised(psycopg.ProgrammingError),
            _the_readers_seen_from_another_connection_are([])
        ))


@pytest.mark.integration
@pytest.mark.parametrize("autocommit", [False, True])
def test_a_read_at_one_moment_does_not_see_what_was_committed_after_its_first(
    autocommit: bool, a_clean_database: None
) -> None:
    # Both kinds of connection: the checkpointer's pool commits as it goes, and
    # a moment said outside a transaction there would be ignored.
    some_reader = "some-reader"

    Scenario() \
        .given(
            connections := _connections(autocommit=autocommit)
        ) \
        .when(
            lambda: _read_twice_with_a_cursor_committed_between(connections, some_reader)
        ) \
        .then(all_of(
            _the_readers_read_were([[], []]),
            _the_readers_seen_from_another_connection_are([some_reader])
        ))


@pytest.mark.integration
def test_a_write_at_one_moment_is_refused(a_clean_database: None) -> None:
    # Refused rather than made under a snapshot that cannot see what it races.
    dont_care_reader = "dont-care-reader"

    def a_cursor_kept_at_one_moment() -> None:
        with at_one_moment(connect_from_env) as conn:
            _a_cursor_kept_by(conn, dont_care_reader)

    Scenario() \
        .when(
            attempting(a_cursor_kept_at_one_moment)
        ) \
        .then(all_of(
            an_error_was_raised(psycopg.errors.ReadOnlySqlTransaction),
            _the_readers_seen_from_another_connection_are([])
        ))


@pytest.mark.integration
def test_a_connection_leaves_a_moment_as_it_came(a_clean_database: None) -> None:
    # A pooled connection goes back to the pool and on to its next borrower,
    # who did not ask to read at a moment and may want to write.
    some_reader = "some-reader"

    with connect_from_env() as held:
        Scenario() \
            .given(
                calling(lambda: _read_once_at_one_moment(lambda: nullcontext(held)))
            ) \
            .when(
                lambda: _what_the_next_transaction_is(held, some_reader)
            ) \
            .then(all_of(
                _the_next_transaction_is(_NextTransaction(
                    status_before=TransactionStatus.IDLE,
                    isolation=THE_DATABASES_OWN_ISOLATION,
                    read_only=FREE_TO_WRITE
                )),
                _the_readers_seen_from_another_connection_are([some_reader])
            ))


@pytest.fixture
def a_database_with_no_schema(postgres: None) -> Iterator[None]:
    """A database as the job has never seen it, put back afterwards.

    Dropped rather than emptied: this is about the tables existing, not about
    what is in them. The suite's other tests share this database and expect its
    schema, so the restoration is not a courtesy.
    """
    with connect_from_env() as conn, conn.cursor() as cursor:
        cursor.execute("DROP SCHEMA public CASCADE")
        cursor.execute("CREATE SCHEMA public")
        conn.commit()

    try:
        yield
    finally:
        with connect_from_env() as conn:
            reset_schema(conn)


def _opened_and_closed(connection: dict[str, Any]) -> None:
    """A pool opened on the suite's database, its connections made as
    `connection` says, and closed again."""
    with open_pool(DatabaseSettings.of(get_settings()), connection=connection):
        pass


def _no_connection_is_named(application: str) -> Assertion[Any]:
    """That the database holds no connection named `application`."""
    def assertion(_: Any) -> bool:
        with connect_from_env() as conn, conn.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM pg_stat_activity WHERE application_name = %s",
                           (application,))
            row = cursor.fetchone()

        held = row[0] if row is not None else 0

        if held:
            raise AssertionError(
                f"Expected no connection named [{application}] left open, and the database "
                f"holds {held}."
            )

        return True

    return assertion


def _nothing_was_raised() -> Assertion[Exception | None]:
    def assertion(error: Exception | None) -> bool:
        if error is not None:
            raise AssertionError(
                f"Expected the database to be accepted, but [{type(error).__name__}] was raised: "
                f"[{error}]."
            )

        return True

    return assertion


def _a_run_held_at(epoch: int) -> Fence:
    """An incident with a run a worker holds, written here rather than claimed,
    for the reason `test_fencing` gives."""
    with connect_from_env() as conn, conn.cursor() as cursor:
        cursor.execute("INSERT INTO incident (alert_payload, shape, alert_service, status, "
                       "created_at) VALUES ('{}', %s, %s, 'investigating', now()) "
                       "RETURNING id", (SHIPPED.current(ALERT), DONT_CARE_SERVICE))
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


def _a_cursor_kept_by(conn: psycopg.Connection, reader: str) -> None:
    """A row in a table nothing else in these tests writes, as `_a_write_on`'s
    is - and left uncommitted, which is the unit of work's to do."""
    conn.execute("INSERT INTO event_cursor (reader, seq) VALUES (%s, 0)", (reader,))


class _NextTransaction(NamedTuple):
    """What a connection was like after a moment: whether a transaction was
    still open on it, and how the next one it opened reads."""
    status_before: TransactionStatus
    isolation: str
    read_only: str


def _connections(*, autocommit: bool) -> Connections:
    """Connections to the suite's database, committing as they go or not."""
    settings = DatabaseSettings.of(get_settings())

    return lambda: connect(settings, connection={"autocommit": autocommit})


def _the_readers_on(conn: psycopg.Connection) -> list[str]:
    with conn.cursor() as cursor:
        cursor.execute("SELECT reader FROM event_cursor ORDER BY reader")
        return [reader for (reader,) in cursor.fetchall()]


def _read_twice_with_a_cursor_committed_between(connections: Connections,
                                                reader: str) -> list[list[str]]:
    """Who keeps a cursor, read twice at one moment - with `reader`'s cursor
    committed on another connection between the two reads."""
    with at_one_moment(connections) as conn:
        first = _the_readers_on(conn)

        with connect_from_env() as another:
            _a_cursor_kept_by(another, reader)
            another.commit()

        return [first, _the_readers_on(conn)]


def _read_once_at_one_moment(connections: Connections) -> None:
    with at_one_moment(connections) as conn:
        _the_readers_on(conn)


def _what_the_next_transaction_is(conn: psycopg.Connection, reader: str) -> _NextTransaction:
    """Whether `conn` holds a transaction, then what the next one it opens reads
    at - with a cursor kept by `reader` written in it and committed."""
    status_before = conn.info.transaction_status

    with conn.transaction(), conn.cursor() as cursor:
        cursor.execute("SHOW transaction_isolation")
        isolation = cursor.fetchone()
        cursor.execute("SHOW transaction_read_only")
        read_only = cursor.fetchone()
        _a_cursor_kept_by(conn, reader)

    return _NextTransaction(status_before=status_before,
                            isolation=isolation[0] if isolation else "",
                            read_only=read_only[0] if read_only else "")


def _the_readers_read_were(expected: list[list[str]]) -> Assertion[Any]:
    def assertion(read: Any) -> bool:
        if read != expected:
            raise AssertionError(
                f"Expected each read at one moment to see the cursors kept by {expected}, "
                f"got {read}."
            )

        return True

    return assertion


def _the_next_transaction_is(expected: _NextTransaction) -> Assertion[Any]:
    def assertion(found: Any) -> bool:
        if found != expected:
            raise AssertionError(
                f"Expected the connection to leave a moment as {expected}, got {found}."
            )

        return True

    return assertion


def _the_readers_seen_from_another_connection_are(expected: list[str]) -> Assertion[Any]:
    """Who keeps a cursor, asked on a connection of its own - so only what was
    committed can be seen."""
    def assertion(_result: Any) -> bool:
        with connect_from_env() as conn, conn.cursor() as cursor:
            cursor.execute("SELECT reader FROM event_cursor ORDER BY reader")
            seen = [reader for (reader,) in cursor.fetchall()]

        if seen != expected:
            raise AssertionError(
                f"Expected the cursors seen from another connection to be kept by "
                f"{expected}, got {seen}."
            )

        return True

    return assertion
