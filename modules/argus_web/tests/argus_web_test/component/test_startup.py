from __future__ import annotations

from collections.abc import Iterator

import psycopg
import pytest
from argus_core.db import connect
from argus_core.schema import SchemaNotApplied, reset_schema
from argus_testkit import Assertion, Scenario, an_error_was_raised, attempting
from argus_web.app import app
from fastapi.testclient import TestClient

"""What this application does about the database's shape: nothing but check it.

It used to apply the schema on the way up, which made the process that only
reads the process that defined every table the rest of the system writes - and
made the worker's ability to start depend on this one having started first.
Neither coupling was declared anywhere, and the second is the kind that is found
by a stack coming up in an order nobody chose.

So the schema arrives from a job of its own, and this refuses to serve without
it. Refusing rather than proceeding, because a process that starts and then
fails on whatever route is hit first reports the cause to whoever happened to
open a page, as a broken page.
"""


@pytest.mark.component
def test_the_application_refuses_a_database_with_no_schema(
        a_database_with_no_schema: None) -> None:
    Scenario() \
        .given(a_database_with_no_schema) \
        .when(attempting(_start_the_application)) \
        .then(an_error_was_raised(SchemaNotApplied))


@pytest.mark.component
def test_the_application_serves_a_database_the_job_has_prepared() -> None:
    # The other way round, and not a formality: a check that refused everything
    # would pass the test above and stop the stack.
    Scenario() \
        .when(attempting(_start_the_application)) \
        .then(_nothing_was_raised())


@pytest.fixture
def a_database_with_no_schema() -> Iterator[None]:
    """A database as the job has never seen it, put back afterwards.

    Dropped rather than emptied: this is about the tables existing, not about
    what is in them. The suite's other tests share this database and expect its
    schema, so the restoration is not a courtesy.
    """
    with connect() as conn:
        _drop_everything(conn)

    try:
        yield
    finally:
        with connect() as conn:
            reset_schema(conn)


def _start_the_application() -> None:
    """Everything the process does before it answers anything.

    `TestClient` as a context manager rather than bare, because the lifespan is
    the whole subject here and a client that never enters one never runs it.
    """
    with TestClient(app):
        pass


def _drop_everything(conn: psycopg.Connection) -> None:
    with conn.cursor() as cursor:
        cursor.execute("DROP SCHEMA public CASCADE")
        cursor.execute("CREATE SCHEMA public")
    conn.commit()


def _nothing_was_raised() -> Assertion[Exception | None]:
    def assertion(error: Exception | None) -> bool:
        if error is not None:
            raise AssertionError(
                f"Expected the application to start, but [{type(error).__name__}] "
                f"was raised: [{error}]."
            )

        return True

    return assertion
