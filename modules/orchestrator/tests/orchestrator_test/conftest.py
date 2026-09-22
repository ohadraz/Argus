"""The database this module's tests run against, and its state between them.

Here rather than in one directory, because the tests that reach a database no
longer sit together: `component` holds most of them, and the module's own
suites may need one at any time. A fixture only one directory could see left
the others hanging on a connection to a database nobody had started.

Offered rather than imposed. Most of this module's tests are unit tests with no
database in sight, and an autouse fixture at this level would make every one of
them wait for a container to come up. A test that needs the database asks for
it, one at a time.

The same shape as `argus_incidents`' and the integration suite's own conftests,
deliberately: each needs one database for a whole run and an empty one for each
test, and several answers to that question would be several ways for a suite to
be dirty. Not shared code, though. `argus_testkit` is where shared test support
lives and it stays free of `argus_core` - depending back on the module it
supports would close a cycle - and the alternative, a helper in `argus_core`
itself, would put docker in a production package.
"""

from __future__ import annotations

import subprocess
from collections.abc import Iterator
from typing import cast
from unittest.mock import MagicMock, create_autospec

import pytest
from argus_core import connect_from_env
from argus_core.schema import reset_schema
from orchestrator.walk import ports
from psycopg import sql


@pytest.fixture
def record_outcome() -> MagicMock:
    """A stand-in for the port that writes down what an action did.

    A fixture rather than a builder, and here rather than in the two files that
    ask for it, because pytest is what hands a fresh one to each test - which
    is the whole reason it is not simply called: a double shared between two
    tests carries the first one's calls into the second.
    """
    return cast(MagicMock, create_autospec(ports.RecordOutcome, instance=True))


@pytest.fixture
def transition_incident() -> MagicMock:
    """A stand-in for the port that moves an incident between statuses."""
    return cast(MagicMock, create_autospec(ports.TransitionIncident, instance=True))


@pytest.fixture(scope="session")
def postgres() -> Iterator[None]:
    """The database, up for the whole suite and stopped after it.

    Started from an empty schema rather than an adopted one: the container may
    be a previous run's, and a run that was killed left its rows behind.
    """
    subprocess.run(["docker", "compose", "up", "-d", "--wait", "postgres"], check=True)
    try:
        with connect_from_env() as conn:
            reset_schema(conn)
        yield
    finally:
        subprocess.run(["docker", "compose", "stop", "postgres"], check=True)


@pytest.fixture
def a_clean_database(postgres: None) -> Iterator[None]:
    """Empties every table after each test.

    After rather than before, so that a test which failed leaves nothing behind
    for the next one to trip over - and so the rows are still there to look at
    while the failure is being read.

    What to empty is asked of the database instead of listed here. A list would
    be a second statement of the schema, and the day a table is added the suite
    would keep passing while quietly leaking its rows into the next test.
    """
    yield

    with connect_from_env() as conn, conn.cursor() as cursor:
        cursor.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        tables = [name for (name,) in cursor.fetchall()]

        if tables:
            cursor.execute(
                sql.SQL("TRUNCATE {} RESTART IDENTITY CASCADE").format(
                    sql.SQL(", ").join(sql.Identifier(table) for table in tables)
                )
            )

        conn.commit()
