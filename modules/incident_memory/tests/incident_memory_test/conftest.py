"""The store and the database this module's integration and component cases
run against, and their state between them. Nothing here is used unless asked
for, so the unit cases beside them start nothing.

A real Qdrant rather than a double, because what these tests are about is the
half that cannot be faked: whether a payload survives a round trip, whether a
filter selects only the service it names, whether the same incident written
twice is one record or two. A stand-in answers all three the way whoever wrote
it expected, which is the one answer that proves nothing.

A real Postgres beside it, because a record is filed there before anything can
search it: the walk's one write is a row the fence can refuse, and the store is
filled from the rows afterwards. Whether a refused write reaches the store, and
whether a record refiled mid-delivery is delivered again, are questions only
the two together can answer.

The same shape as the index's conftest - one store and one database for the
whole run, an empty one of each for each test - and for the same reason: several
answers to "what is this suite's state" are several ways for a suite to be
dirty.

Readiness is polled here rather than left to Compose. The Qdrant image is
distroless, so there is no shell inside it to run a healthcheck with, and
`up --wait` therefore returns when the container is running - a little before it
will answer. Polling `/readyz` from outside is what closes that gap.

Both fixtures are refused in the e2e stack's compose project, and each stops
only the service it brought up. There, the store's emptying and the schema's
reset would wipe what a running stack's worker is using, and a bare stop would
take the whole stack down.
"""

from __future__ import annotations

import os
import subprocess
import time
from collections.abc import Iterator
from typing import Final

import httpx2
import psycopg
import pytest
from argus_testkit import refuse_the_e2e_stacks_project
from postgres import connect_from_env, reset_schema
from psycopg import sql
from qdrant_client import QdrantClient
from vector_store_qdrant.indexing import QdrantIndex

# How long a cold container may take to answer. Generous, because the first
# start on a machine that has never pulled the image is the slow one, and a
# suite that fails there fails for a reason that has nothing to do with the code.
LONGEST_WAIT_SECONDS = 60.0
BETWEEN_POLLS_SECONDS = 0.5

# The compose services this suite brings up, and what it stops.
_QDRANT: Final = "qdrant"
_POSTGRES: Final = "postgres"
# What postgres depends on in docker-compose.yml, so `up` starts it with
# postgres and the stop names it too - or it outlives the suite.
_ITS_CLOCK: Final = "sim-clock"

# The session that gives this suite a compose project of its own.
_THIS_SUITES_SESSION: Final = "test_module(module='incident_memory')"

# The one collection these cases keep records in. Bound into the store each case
# is handed, as a process binds its own where it builds the adapter.
THE_COLLECTION: Final = "incidents"


def _the_stores_url() -> str:
    """Where the store is, as the compose file published it.

    Read from the environment rather than through `Settings`, because this is
    the suite's own business: a component test reading production configuration
    fails differently depending on what a developer happens to have in `.env`.
    """
    port = os.environ.get("ARGUS_QDRANT_PORT", "6333")

    return os.environ.get("ARGUS_QDRANT_URL", f"http://localhost:{port}")


@pytest.fixture(scope="session")
def qdrant() -> Iterator[str]:
    """The store, up for the whole suite and stopped after it.

    Started empty rather than adopted, for the reason the schema is reset: the
    container may be a previous run's, and a run that was killed left its points
    behind.
    """
    refuse_the_e2e_stacks_project(_THIS_SUITES_SESSION)
    subprocess.run(["docker", "compose", "up", "-d", "--wait", _QDRANT], check=True)

    try:
        _wait_until_it_answers(_the_stores_url())
        _drop_every_collection(_the_stores_url())
        yield _the_stores_url()
    finally:
        subprocess.run(["docker", "compose", "stop", _QDRANT], check=True)


@pytest.fixture(scope="session")
def postgres() -> Iterator[None]:
    """The database, up for the whole suite and stopped after it.

    Started from an empty schema rather than an adopted one: the container may
    be a previous run's, and a run that was killed left its rows behind.
    """
    refuse_the_e2e_stacks_project(_THIS_SUITES_SESSION)
    subprocess.run(["docker", "compose", "up", "-d", "--wait", _POSTGRES], check=True)

    try:
        with connect_from_env() as conn:
            reset_schema(conn)

        yield
    finally:
        subprocess.run(["docker", "compose", "stop", _POSTGRES, _ITS_CLOCK], check=True)


@pytest.fixture
def a_clean_database(postgres: None) -> Iterator[None]:
    """Empties every table after each test that asks for the database.

    After rather than before, so a test that failed leaves nothing for the next
    one to trip over - and so its rows are still there to look at while the
    failure is being read.

    Asked for rather than applied to every test, as the index's is: most of
    these cases are about the store alone, or about no store at all, and
    bringing a database up for them would make a suite about vectors wait on
    Postgres.

    What to empty is asked of the database rather than listed here. A list would
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


@pytest.fixture
def records(a_clean_database: None) -> Iterator[psycopg.Connection]:
    """A connection to the database a record is filed in."""
    with connect_from_env() as conn:
        yield conn


def _wait_until_it_answers(url: str) -> None:
    """Polls `/readyz` until the store will serve, or gives up saying so."""
    gave_up_at = time.monotonic() + LONGEST_WAIT_SECONDS

    while time.monotonic() < gave_up_at:
        try:
            if httpx2.get(f"{url}/readyz", timeout=2.0).status_code == httpx2.codes.OK:
                return
        except httpx2.HTTPError:
            pass

        time.sleep(BETWEEN_POLLS_SECONDS)

    raise RuntimeError(
        f"the store at [{url}] did not become ready within "
        f"[{LONGEST_WAIT_SECONDS}] seconds"
    )


def _drop_every_collection(url: str) -> None:
    """Empties the store, by dropping every collection rather than the ones a
    test is expected to have made - so a collection nobody expected goes too."""
    client = QdrantClient(url=url)

    try:
        for collection in client.get_collections().collections:
            client.delete_collection(collection.name)
    finally:
        client.close()


@pytest.fixture
def client(qdrant: str) -> Iterator[QdrantClient]:
    """A client onto a store holding nothing, emptied again after the test.

    After rather than before, as the database is: a test leaves the store as it
    found it - the last test of the suite included - and what a failed test
    wrote is still there to read while the failure is. The suite's own start
    empties it once, for whatever a killed run left.

    Asked for directly only by a case about what the store made of a write -
    the index on a field - which is the vendor's account and no port's.
    """
    client = QdrantClient(url=qdrant)

    try:
        yield client
    finally:
        client.close()
        _drop_every_collection(qdrant)


@pytest.fixture
def store(client: QdrantClient) -> QdrantIndex:
    """The store as the deliverer holds it: the adapter, over `THE_COLLECTION`."""
    return QdrantIndex(client, THE_COLLECTION)
