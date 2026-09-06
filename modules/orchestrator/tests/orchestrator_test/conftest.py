from __future__ import annotations

import subprocess
from collections.abc import Iterator

import pytest
from argus_core.db import connect
from argus_core.schema import create_schema
from psycopg import sql

"""The database this module's tests run against, and its state between them.

Here rather than beside the repository tests, because the repository is not the
only thing in this module that reaches a database: the entrypoints do too, and a
fixture that only one directory could see left the other hanging on a connection
to a database nobody had started.

Offered rather than imposed. Most of this module's tests are unit tests with no
database in sight, and an autouse fixture at this level would make every one of
them wait for a container to come up. A suite that needs the database asks for
it - `repository` asks for every test at once, and a case elsewhere asks for
itself.

The same shape as the integration suite's own conftest, deliberately: both need
one database for a whole run and an empty one for each test, and two answers to
that question would be two ways for a suite to be dirty. Not shared code,
though. `argus_testkit` is where shared test support lives and it stays free of
`argus_core` - depending back on the module it supports would close a cycle -
and the alternative, a helper in `argus_core` itself, would put docker in a
production package. A dozen lines stated twice is the cheaper of the three.
"""


@pytest.fixture(scope="session")
def postgres() -> Iterator[None]:
    """The database, up for the whole suite and stopped after it."""
    subprocess.run(["docker", "compose", "up", "-d", "--wait", "postgres"], check=True)
    try:
        with connect() as conn:
            create_schema(conn)
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
