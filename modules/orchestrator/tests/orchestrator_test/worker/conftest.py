from __future__ import annotations

import subprocess
from collections.abc import Iterator

import pytest
from argus_core.db import connect
from argus_core.schema import create_schema
from psycopg import sql

"""Postgres, for the one suite in this module that has a queue to read.

The same shape as `repository/conftest.py` and for the same reason it is not
shared with it: `argus_testkit` stays free of `argus_core`, and a helper in
`argus_core` would put docker in a production package. The unit suites beside
this one need no database and must not start one, which is why this sits here
rather than at the root of the module's tests.
"""


@pytest.fixture(scope="session", autouse=True)
def postgres() -> Iterator[None]:
    """The database, up for the whole suite and stopped after it."""
    subprocess.run(["docker", "compose", "up", "-d", "--wait", "postgres"], check=True)
    try:
        with connect() as conn:
            create_schema(conn)
        yield
    finally:
        subprocess.run(["docker", "compose", "stop", "postgres"], check=True)


@pytest.fixture(autouse=True)
def a_clean_database(postgres: None) -> Iterator[None]:
    """Empties every table after each test, asking the database what to empty."""
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
