"""Postgres, and nothing else.

A component test runs `web_app` entire - its routes, its reads, its
serialization - and stubs only what it genuinely cannot be: the database. There
is no in-memory Postgres for this workspace's Python, and a SQLite stand-in
would need a second dialect of the schema, which is precisely the thing a
component test is supposed to be checking against. So the real server comes up,
from the same `docker-compose.yml` the stack runs on, with the same DDL.
"""

from __future__ import annotations

import subprocess
from collections.abc import Iterator
from typing import Final

import pytest
from argus_testkit import refuse_the_e2e_stacks_project
from core import connect_from_env
from core.schema import reset_schema
from psycopg import sql

# The compose service this suite brings up, and what it stops.
_POSTGRES: Final = "postgres"
# What postgres depends on in docker-compose.yml, so `up` starts it with
# postgres and the stop names it too - or it outlives the suite.
_ITS_CLOCK: Final = "sim-clock"


@pytest.fixture(scope="session", autouse=True)
def postgres() -> Iterator[None]:
    """The database, up for the whole suite and stopped after it.

    Started from an empty schema rather than an adopted one: the container may
    be a previous run's, and a run that was killed left its rows behind.

    Refused in the e2e stack's compose project, where the reset would empty the
    database a running stack's worker is attached to. Stops only the database
    on the way out, so a project shared by mistake still keeps its other
    services.
    """
    refuse_the_e2e_stacks_project("test_module(module='web_app')")
    subprocess.run(["docker", "compose", "up", "-d", "--wait", _POSTGRES], check=True)
    try:
        with connect_from_env() as conn:
            reset_schema(conn)
        yield
    finally:
        subprocess.run(["docker", "compose", "stop", _POSTGRES, _ITS_CLOCK], check=True)


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
