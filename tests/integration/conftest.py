from __future__ import annotations

import subprocess
from collections.abc import Iterator

import pytest
from argus_core.db import connect
from argus_core.schema import create_schema
from psycopg import sql

"""The database this suite runs against, and its state between tests.

Brought up here rather than by the one test file that needs it, because a
container costs seconds to start and every test in the suite shares one schema:
one start for the run, not one per file that grows a database dependency later.

Postgres is the only infrastructure this suite cannot fake. The model answers
from a committed recording and retrieval answers from memory, so this fixture
is the whole of what `integration` asks of docker - which is what lets the
session stay free and keyless.
"""


@pytest.fixture(scope="session", autouse=True)
def postgres() -> Iterator[None]:
    """The database, up for the whole suite and stopped after it.

    The schema is created rather than assumed: a fresh clone has a volume with
    nothing in it, and a suite that required someone to have run the stack once
    before would pass or fail on the history of the machine it ran on.
    """
    subprocess.run(["docker", "compose", "up", "-d", "--wait", "postgres"], check=True)
    try:
        with connect() as conn:
            create_schema(conn)
        yield
    finally:
        subprocess.run(["docker", "compose", "stop", "postgres"], check=True)


@pytest.fixture(autouse=True)
def a_clean_database(postgres: None) -> Iterator[None]:
    """Empties every table after each test.

    After rather than before, so that a test which failed leaves nothing behind
    for the next one to trip over - and so the rows are still there to look at
    while the failure is being read, since the emptying happens on the way out
    of the test that wrote them rather than on the way into the next.

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
