"""What a process does when it finds a database nobody has prepared.

Argus applies its schema from a job of its own and from nowhere else. A process
that served requests and created tables on the way up made two undeclared
promises: that it would be started before anything else that writes, and that
whatever it found already there was what this repo describes. Neither was true,
and the second is how a column added to the DDL reaches nothing.

So a process asks, and refuses. It refuses with the command rather than with the
fact, because the audience for this failure is somebody's first run against a
fresh database, and "no such table: incident" sends them reading the schema
instead of running the job.

Whether the tables are there is a question for the database; whether an answer
of "no" is fatal is not. The asking is injected so that the second is stated
without needing the first. The asking itself is put to a real database once,
for what only a database can show: that the answer is read the same whatever
rows the connection it is asked on hands out.

And applying, the way a database somebody minds losing has it done: the chain
run from wherever the database is, with nothing dropped on the way.
"""

from __future__ import annotations

from unittest.mock import create_autospec

import psycopg
import pytest
from argus_testkit import (
    Assertion,
    Scenario,
    all_of,
    an_error_was_raised,
    attempting,
    calling,
    the_answer_was,
)
from core import DatabaseSettings, get_settings
from postgres import (
    SchemaNotApplied,
    SchemaPresent,
    apply_schema,
    connect,
    connect_from_env,
    require_schema,
    reset_schema,
)
from postgres.schema import schema_is_present
from psycopg.rows import dict_row

A_PREPARED_DATABASE = True
A_DATABASE_WITH_NO_SCHEMA = False

THE_JOB = "nox -s schema"

# A row the database holds before the schema is applied to it again: a reader's
# place in the event log, the table with the fewest columns a row must fill.
SOME_READER = "a reader whose place outlives the schema being applied"
SOME_PLACE = 42


@pytest.mark.unit
def test_a_prepared_database_is_accepted() -> None:
    Scenario() \
        .given(
            dont_care_connection := _a_connection()
        ) \
        .when(attempting(lambda: require_schema(
            dont_care_connection, present=_answering(A_PREPARED_DATABASE)
        ))) \
        .then(_nothing_was_raised())


@pytest.mark.unit
def test_a_database_with_no_schema_is_refused() -> None:
    # Rather than proceeding to fail on the first query. A process that starts
    # and then dies on whatever route is hit first reports its cause once
    # somebody is already using it, and reports it as a broken page.
    Scenario() \
        .given(
            dont_care_connection := _a_connection()
        ) \
        .when(attempting(lambda: require_schema(
            dont_care_connection, present=_answering(A_DATABASE_WITH_NO_SCHEMA)
        ))) \
        .then(all_of(
            an_error_was_raised(SchemaNotApplied),
            _the_refusal_names(THE_JOB)
        ))


@pytest.mark.unit
def test_the_database_asked_about_is_the_one_the_process_holds() -> None:
    # The check is worth nothing if it can answer about a different database
    # than the one the process is about to serve from.
    asked_about: list[psycopg.Connection] = []
    Scenario() \
        .given(
            the_connection := _a_connection()
        ) \
        .when(lambda: require_schema(
            the_connection, present=_recording(asked_about, A_PREPARED_DATABASE)
        )) \
        .then(lambda _: _it_was_asked_about(asked_about, the_connection))


@pytest.mark.integration
def test_the_schema_is_found_on_a_connection_handing_out_rows_by_name(postgres: None) -> None:
    # The worker's checkpointer pool hands out rows by column name, and a pool
    # asks after the schema on one of its own connections. An answer read by
    # position would fail there on a database that has every table.
    Scenario() \
        .when(
            lambda: _asked_on_a_connection_handing_out_rows_by_name()
        ) \
        .then(
            the_answer_was(True)
        )


@pytest.mark.integration
def test_applying_the_schema_keeps_what_the_database_holds(a_clean_database: None) -> None:
    # What a deployment that keeps its data runs, against a database already at
    # the chain's head: there is nothing to apply, and nothing is taken away.
    #
    # Put at the head here rather than assumed to be: emptying the tables after
    # a test empties Alembic's record of the chain with them, and a database
    # whose record says nothing has run is one the chain is applied to again.
    Scenario() \
        .given(
            calling(_a_database_at_the_chains_head),
            calling(lambda: _a_place_kept_for(SOME_READER, SOME_PLACE))
        ) \
        .when(
            lambda: _the_schema_applied()
        ) \
        .then(
            _the_place_kept_for(SOME_READER, is_still=SOME_PLACE)
        )


@pytest.mark.integration
def test_applying_the_schema_to_an_empty_database_gives_it_every_table(
    a_clean_database: None
) -> None:
    # What a deployment's first start runs. Asked after the way every service
    # asks before it serves, so a job that applied nothing would leave a
    # database every service refuses.
    Scenario() \
        .given(
            calling(_a_database_with_no_schema)
        ) \
        .when(
            lambda: _the_schema_applied()
        ) \
        .then(
            lambda _: _the_schema_is_there()
        )


def _a_database_with_no_schema() -> None:
    with connect_from_env() as conn:
        conn.execute("DROP SCHEMA public CASCADE")
        conn.execute("CREATE SCHEMA public")
        conn.commit()


def _the_schema_is_there() -> bool:
    with connect_from_env() as conn:
        if not schema_is_present(conn):
            raise AssertionError(
                "Expected the schema to be there once it was applied to an empty "
                "database, and the database has none."
            )

    return True


def _a_database_at_the_chains_head() -> None:
    with connect_from_env() as conn:
        reset_schema(conn)


def _a_place_kept_for(reader: str, place: int) -> None:
    with connect_from_env() as conn:
        conn.execute("INSERT INTO event_cursor (reader, seq) VALUES (%s, %s)", (reader, place))
        conn.commit()


def _the_schema_applied() -> None:
    with connect_from_env() as conn:
        apply_schema(conn)


def _the_place_kept_for(reader: str, is_still: int) -> Assertion[object]:
    def assertion(_result: object) -> bool:
        with connect_from_env() as conn:
            row = conn.execute("SELECT seq FROM event_cursor WHERE reader = %s",
                               (reader,)).fetchone()

        if row is None or row[0] != is_still:
            raise AssertionError(
                f"Expected the place [{reader}] keeps in the log to still be [{is_still}] "
                f"once the schema was applied again, and the database held "
                f"[{row[0] if row is not None else 'no such row'}]."
            )

        return True

    return assertion


def _asked_on_a_connection_handing_out_rows_by_name() -> bool:
    with connect(DatabaseSettings.of(get_settings()),
                 connection={"row_factory": dict_row}) as conn:
        return schema_is_present(conn)


def _a_connection() -> psycopg.Connection:
    """A connection that is passed along and never used by this module."""
    connection: psycopg.Connection = create_autospec(psycopg.Connection, instance=True)

    return connection


def _answering(present: bool) -> SchemaPresent:
    """The database's answer, stated rather than asked for."""
    return lambda _: present


def _recording(asked_about: list[psycopg.Connection], present: bool) -> SchemaPresent:
    """The same answer, and a note of what it was asked about."""
    def answer(connection: psycopg.Connection) -> bool:
        asked_about.append(connection)

        return present

    return answer


def _nothing_was_raised() -> Assertion[Exception | None]:
    def assertion(error: Exception | None) -> bool:
        if error is not None:
            raise AssertionError(
                f"Expected the schema to be accepted, but [{type(error).__name__}] "
                f"was raised: [{error}]."
            )

        return True

    return assertion


def _the_refusal_names(command: str) -> Assertion[Exception | None]:
    def assertion(error: Exception | None) -> bool:
        if error is None or command not in str(error):
            raise AssertionError(
                f"Expected the refusal to name [{command}], "
                f"but it said: [{error}]."
            )

        return True

    return assertion


def _it_was_asked_about(asked_about: list[psycopg.Connection],
                        expected: psycopg.Connection) -> bool:
    if asked_about != [expected]:
        raise AssertionError(
            f"Expected the check to be asked about the one connection it was "
            f"given, but it was asked about {asked_about}."
        )

    return True
