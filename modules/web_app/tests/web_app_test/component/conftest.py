"""Postgres, and nothing else.

A component test runs `web_app` entire - its routes, its reads, its
serialization - and stubs only what it genuinely cannot be: the database. There
is no in-memory Postgres for this workspace's Python, and a SQLite stand-in
would need a second dialect of the schema, which is precisely the thing a
component test is supposed to be checking against. So the real server comes up,
from the same `docker-compose.yml` the stack runs on, with the same DDL - the
suite's `postgres`, which every case here asks for through the emptying below.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from postgres import connect_from_env
from psycopg import sql


@pytest.fixture(autouse=True)
def a_clean_database(postgres: None) -> Iterator[None]:
    """Empties every table after each test, so no test inherits another's rows.

    Every test here writes the incidents its page is read from, and a row one
    test leaves behind is one the next test's write can collide with - an
    action left open on a subject refuses the next test's claim on it. So every
    test is emptied after, rather than each one remembering to ask.

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
