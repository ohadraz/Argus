"""The database this module's tests run against, and its state between them.

Autouse, unlike the same fixtures in the modules that keep a database at arm's
length: every test here writes rows and reads them back, because writing rows
and reading them back is what this module does. A suite in which no test can
run without a database is one where asking per test is ceremony.

The same shape as the orchestrator's and the integration suite's own conftests,
deliberately: each needs one database for a whole run and an empty one for each
test, and several answers to that question would be several ways for a suite to
be dirty. Not shared code, though. `argus_testkit` is where shared test support
lives and it stays free of `core` - depending back on the module it
supports would close a cycle - and the alternative, a helper in `core`
itself, would put docker in a production package.
"""

from __future__ import annotations

import subprocess
from collections.abc import Iterator
from typing import Final

import pytest
from argus_testkit import refuse_the_e2e_stacks_project
from postgres import connect_from_env, reset_schema
from psycopg import sql

# The compose service this suite brings up, and what it stops.
_POSTGRES: Final = "postgres"
# What postgres depends on in docker-compose.yml, so `up` starts it with
# postgres and the stop names it too - or it outlives the suite.
_ITS_CLOCK: Final = "sim-clock"


@pytest.fixture(scope="session")
def postgres() -> Iterator[None]:
    """The database, up for the whole suite and stopped after it.

    Started from an empty schema rather than an adopted one: the container may
    be a previous run's, and a run that was killed left its rows behind.

    Refused in the e2e stack's compose project, where the reset would empty the
    database a running stack's worker is attached to. Stops only the database
    on the way out, so a project shared by mistake still keeps its other
    services.
    """
    refuse_the_e2e_stacks_project("test_module(module='incident_record')")
    subprocess.run(["docker", "compose", "up", "-d", "--wait", _POSTGRES], check=True)
    try:
        with connect_from_env() as conn:
            reset_schema(conn)
        yield
    finally:
        subprocess.run(["docker", "compose", "stop", _POSTGRES, _ITS_CLOCK], check=True)


@pytest.fixture(autouse=True)
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
