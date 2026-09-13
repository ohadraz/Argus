from __future__ import annotations

import subprocess
from collections.abc import Iterator

import pytest
from argus_core.db import connect
from argus_core.schema import reset_schema
from psycopg import sql

"""The database this module's tests run against, and its state between them.

Offered rather than imposed. Most of this module's tests never touch a database
- a message is formatted and posted, and the double it is posted to is brought
up by the `component` suite's own conftest - so an autouse fixture here would
make every one of them wait for a container. The relay is the exception: it
follows the event log, and a log needs somewhere to be.

The same shape as `argus_incidents`' and the orchestrator's own conftests,
deliberately: each needs one database for a whole run and an empty one for each
test, and several answers to that question would be several ways for a suite to
be dirty. Not shared code, though. `argus_testkit` is where shared test support
lives and it stays free of `argus_core` - depending back on the module it
supports would close a cycle - and the alternative, a helper in `argus_core`
itself, would put docker in a production package.
"""


@pytest.fixture(scope="session")
def postgres() -> Iterator[None]:
    """The database, up for the whole suite and stopped after it.

    Started from an empty schema rather than an adopted one: the container may
    be a previous run's, and a run that was killed left its rows behind.
    """
    subprocess.run(["docker", "compose", "up", "-d", "--wait", "postgres"], check=True)
    try:
        with connect() as conn:
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

    with connect() as conn, conn.cursor() as cursor:
        cursor.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        tables = [name for (name,) in cursor.fetchall()]

        if tables:
            cursor.execute(
                sql.SQL("TRUNCATE {} RESTART IDENTITY CASCADE").format(
                    sql.SQL(", ").join(sql.Identifier(table) for table in tables)
                )
            )

        conn.commit()
