"""The store this module's integration tests run against, and its state between
them.

A real Qdrant rather than a double, because what these tests are about is the
half that cannot be faked: whether a condition is applied while the store ranks,
whether a floor is, whether a payload survives the round trip. A stand-in answers
all of them the way whoever wrote it expected, which is the one answer that
proves nothing.

The shape of the corpora's own conftests - one store for the whole run, an
empty one for each test - and refused in the e2e stack's compose project for
their reason: there, emptying the store would wipe what a running stack is using.

Readiness is polled here rather than left to Compose. The Qdrant image is
distroless, so there is no shell inside it to run a healthcheck with, and
`up --wait` therefore returns when the container is running - a little before it
will answer.
"""

from __future__ import annotations

import os
import subprocess
import time
from collections.abc import Iterator
from typing import Final

import httpx2
import pytest
from argus_testkit import refuse_the_e2e_stacks_project
from qdrant_client import QdrantClient
from vector_store_qdrant.indexing import QdrantIndex

# How long a cold container may take to answer. Generous, because the first
# start on a machine that has never pulled the image is the slow one.
LONGEST_WAIT_SECONDS = 60.0
BETWEEN_POLLS_SECONDS = 0.5

# The compose service this suite brings up, and stops.
_QDRANT: Final = "qdrant"

# The session that gives this suite a compose project of its own.
_THIS_SUITES_SESSION: Final = "test_module(module='vector_store_qdrant')"

# The one collection these cases fill and search.
THE_COLLECTION: Final = "vector_store_qdrant_test"


def _the_stores_url() -> str:
    """Where the store is, as the compose file published it - read from the
    environment rather than through `Settings`, which is production's."""
    port = os.environ.get("ARGUS_QDRANT_PORT", "6333")

    return os.environ.get("ARGUS_QDRANT_URL", f"http://localhost:{port}")


@pytest.fixture(scope="session")
def qdrant() -> Iterator[str]:
    """The store, up for the whole suite and stopped after it, started empty
    rather than adopted from whatever a killed run left."""
    refuse_the_e2e_stacks_project(_THIS_SUITES_SESSION)
    subprocess.run(["docker", "compose", "up", "-d", "--wait", _QDRANT], check=True)

    try:
        _wait_until_it_answers(_the_stores_url())
        _drop_every_collection(_the_stores_url())
        yield _the_stores_url()
    finally:
        subprocess.run(["docker", "compose", "stop", _QDRANT], check=True)


@pytest.fixture
def client(qdrant: str) -> Iterator[QdrantClient]:
    """A client onto a store holding nothing, emptied again after the test -
    after rather than before, so what a failed test wrote is still there to read
    while the failure is."""
    client = QdrantClient(url=qdrant)

    try:
        yield client
    finally:
        client.close()
        _drop_every_collection(qdrant)


@pytest.fixture
def store(client: QdrantClient) -> QdrantIndex:
    """The whole store, over `THE_COLLECTION`: what a corpus builder holds, and a
    search besides."""
    return QdrantIndex(client, THE_COLLECTION)


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
