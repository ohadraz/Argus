"""Asking the store what it holds like this incident - the walk's side of it.

The walk reads memory and never writes it. What it files is a row the fence can
refuse (`filing`), and the store is filled from the rows by a process of its own
(`delivering`) - so everything here is a read, and a read made for a run that
was since taken back changes nothing anybody else holds. That is why this is
the one module of the store's that a walk may reach, and the layering guard
holds every other way to the store shut.

Two halves. `recalled` is the search itself, in the store's vocabulary: a vector
in, records out. `recalling_from` binds the model and the store into the
question the walk actually asks, which is text: the same model has to embed the
question as embedded the records, and binding it here, once, is what stops two
callers arranging that separately.

The client is opened here too, for the process that holds one: the walk's
worker opens it when it starts and closes it when it stops, beside its pool.
"""

from __future__ import annotations

from collections.abc import Callable, Generator
from contextlib import contextmanager
from typing import Final

from argus_core.embedding import Embedder
from qdrant_client import QdrantClient
from qdrant_client.models import FieldCondition, Filter, MatchValue

from incident_memory.records import RememberedIncident

# What a record carries beside its vector. `service` is its own field because
# every search narrows by it and a filter needs something to match on; the
# record travels whole beside it, because what a recall is for is the list of
# what was tried, and an id the caller then had to look up elsewhere would make
# memory a second database. Named here, where they are read, and written by
# `keeping` in the same words.
SERVICE_FIELD: Final = "service"
RECORD_FIELD: Final = "record"

# The store a process holds, by the name the walk knows it by. The client itself,
# named here so that a process typing what it holds reaches the store through
# the one module of it the walk may know.
type MemoryStore = QdrantClient

type Recaller = Callable[[str, str], list[RememberedIncident]]


@contextmanager
def the_store_at(url: str) -> Generator[MemoryStore]:
    """One client onto the store, for as long as the block runs.

    Not a `with` around the client itself: `QdrantClient` closes but is not a
    context manager, which is the same bargain `code_index`'s catch-up makes.
    """
    store = QdrantClient(url=url)

    try:
        yield store
    finally:
        store.close()


def recalled(client: QdrantClient,
             collection: str,
             vector: list[float],
             *,
             service: str,
             limit: int,
             floor: float) -> list[RememberedIncident]:
    """The incidents most like this one, nearest first, at most `limit` of them.

    Narrowed to one service before anything is compared. Whether two incidents
    happened to the same service is an exact question, and a description that
    merely mentions a service name is not an answer to it.

    `floor` is the caller's policy, applied here so that nothing above ever sees
    a record it was meant to ignore. A nearest-neighbour search always answers:
    without a floor, a corpus holding one unrelated incident hands it back as the
    nearest thing it has, and an ordering would demote a candidate on it.

    A store with no collection yet finds nothing, which is an answer rather than
    a failure - it is the ordinary state before the first incident ends.
    """
    if not client.collection_exists(collection):
        return []

    found = client.query_points(
        collection_name=collection,
        query=vector,
        query_filter=Filter(
            must=[FieldCondition(key=SERVICE_FIELD, match=MatchValue(value=service))]
        ),
        limit=limit,
        score_threshold=floor,
        with_payload=True
    )

    return [
        RememberedIncident.model_validate((point.payload or {})[RECORD_FIELD])
        for point in found.points
    ]


def recalling_from(client: QdrantClient,
                   collection: str,
                   embed: Embedder,
                   *,
                   limit: int,
                   floor: float) -> Recaller:
    """Recalling records: embed the question with the same model, then search.

    The same model, necessarily. Two vectors from two models are two coordinate
    systems, and the distance between them is a number that means nothing - which
    is why the model is bound here, once, rather than named at each end.

    `limit` and `floor` are bound here too. They are a deployment's policy and
    they do not vary per call, so a caller passing them each time would be a
    caller with an opinion about relevance it has no way to hold.
    """

    def recall(described_as: str, service: str) -> list[RememberedIncident]:
        return recalled(
            client,
            collection,
            embed([described_as])[0],
            service=service,
            limit=limit,
            floor=floor
        )

    return recall
