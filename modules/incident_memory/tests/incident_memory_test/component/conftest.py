"""The store this module's component tests run against, and its state between them.

A real Qdrant rather than a double, because what these tests are about is the
half that cannot be faked: whether a payload survives a round trip, whether a
filter selects only the service it names, whether the same incident written
twice is one record or two. A stand-in answers all three the way whoever wrote
it expected, which is the one answer that proves nothing.

No database here, unlike the index's own conftest. Long-term memory keeps
nothing in Postgres: there is no watermark to compare, because a memory is not
derived from anything that could move on without it.

Readiness is polled here rather than left to Compose. The Qdrant image is
distroless, so there is no shell inside it to run a healthcheck with, and
`up --wait` therefore returns when the container is running - a little before it
will answer. Polling `/readyz` from outside is what closes that gap.
"""

from __future__ import annotations

import os
import subprocess
import time
from collections.abc import Iterator

import httpx
import pytest
from qdrant_client import QdrantClient

# How long a cold container may take to answer. Generous, because the first
# start on a machine that has never pulled the image is the slow one, and a
# suite that fails there fails for a reason that has nothing to do with the code.
LONGEST_WAIT_SECONDS = 60.0
BETWEEN_POLLS_SECONDS = 0.5


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
    """The store, up for the whole suite and stopped after it."""
    subprocess.run(["docker", "compose", "up", "-d", "--wait", "qdrant"], check=True)

    try:
        _wait_until_it_answers(_the_stores_url())
        yield _the_stores_url()
    finally:
        subprocess.run(["docker", "compose", "stop", "qdrant"], check=True)


def _wait_until_it_answers(url: str) -> None:
    """Polls `/readyz` until the store will serve, or gives up saying so."""
    gave_up_at = time.monotonic() + LONGEST_WAIT_SECONDS

    while time.monotonic() < gave_up_at:
        try:
            if httpx.get(f"{url}/readyz", timeout=2.0).status_code == httpx.codes.OK:
                return
        except httpx.HTTPError:
            pass

        time.sleep(BETWEEN_POLLS_SECONDS)

    raise RuntimeError(
        f"the store at [{url}] did not become ready within "
        f"[{LONGEST_WAIT_SECONDS}] seconds"
    )


@pytest.fixture
def store(qdrant: str) -> Iterator[QdrantClient]:
    """A client onto a store holding nothing.

    Emptied on the way *in* rather than out, and by dropping every collection
    rather than the one a test expects to find: a run that was killed left its
    points behind, and a test that began by trusting its predecessor to have
    tidied up is a test that passes alone and fails in a suite.
    """
    client = QdrantClient(url=qdrant)

    try:
        for collection in client.get_collections().collections:
            client.delete_collection(collection.name)

        yield client
    finally:
        client.close()
