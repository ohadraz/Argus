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
of "no" is fatal is not. The asking is injected so that this file - the suite of
a module that has no container - can state the second without needing the first.
"""

from __future__ import annotations

from unittest.mock import create_autospec

import psycopg
import pytest
from argus_core.schema import SchemaNotApplied, SchemaPresent, require_schema
from argus_testkit import Assertion, Scenario, all_of, an_error_was_raised, attempting

A_PREPARED_DATABASE = True
A_DATABASE_WITH_NO_SCHEMA = False

THE_JOB = "nox -s schema"


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
