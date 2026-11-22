"""Searching a Qdrant collection - `VectorSearch`, answered by the vendor.

The only module the worker's root may build, and the one way anything that
walks an incident reaches the vendor's client: everything here is a read, and a
read made for a run since taken back changes nothing anybody else holds. The
layering guard exempts this module's edge to `qdrant_client` and no other.

The conditions are translated into the vendor's filter and the floor into its
score threshold, so both are applied while the store ranks rather than to what it
ranked. A filter applied afterwards to the `limit` nearest returns fewer than
`limit` matches while more exist: the nearest points outside a scope crowd out the
ones inside it.

One collection per adapter. The two corpora share a server and nothing else, so
the collection is bound where the adapter is built and a caller asks its question
with nothing about where it is asked.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Generator, Iterator, Sequence
from contextlib import contextmanager
from typing import Final

from core.vector_store import (
    Condition,
    Equals,
    Hit,
    StartsWithAnyOf,
    VectorQueryRefused,
    VectorStoreUnavailable,
    VectorStoreUnreachable,
)
from qdrant_client import QdrantClient
from qdrant_client.http.exceptions import ResponseHandlingException, UnexpectedResponse
from qdrant_client.models import FieldCondition, Filter, MatchPrefix, MatchValue

# Where a status says the store failed for itself rather than refused the
# question: from here up, the same search asked again can be answered.
THE_STORE_FAILED: Final = 500

type ClientFor = Callable[[str], QdrantClient]


def a_client_at(url: str) -> QdrantClient:
    """The vendor's client onto the store at `url`."""
    return QdrantClient(url=url)


class QdrantSearch:
    """`VectorSearch` over one collection of one Qdrant, through a client the
    caller opened and will close."""

    def __init__(self, client: QdrantClient, collection: str) -> None:
        self._client = client
        self._collection = collection

    def nearest(self,
                vector: Sequence[float],
                /,
                *,
                limit: int,
                where: Sequence[Condition] = (),
                floor: float | None = None) -> list[Hit]:
        """See `VectorSearch.nearest`. A collection nobody has written to yet is
        a store holding nothing, and finds nothing."""
        with failures_translated():
            if not self._client.collection_exists(self._collection):
                return []

            found = self._client.query_points(
                collection_name=self._collection,
                query=list(vector),
                query_filter=as_filter(where),
                limit=limit,
                score_threshold=floor,
                with_payload=True
            )

        return [
            Hit(id=str(point.id), score=point.score, payload=dict(point.payload or {}))
            for point in found.points
        ]


class SearchOpenedOnFirstUse:
    """`VectorSearch` whose client is opened by the first search rather than
    when it is built.

    Building a client reaches out: its version check runs on a thread of its own
    and swallows every failure into a warning. So a server built and never asked
    to search - a test's or a deployment's - reaches nothing, and the warning
    about the store's version arrives with the first search instead of at
    startup.

    Opened under a lock, because a server may answer on a pool of threads and two
    first searches would otherwise open two clients, one of them never closed. A
    client that failed to open is not kept: the next search tries again, so a
    store that was down for the first question is not down for the life of the
    process. Never closed - it lives as long as the process that holds it.
    """

    def __init__(self, url: str, collection: str, client_for: ClientFor = a_client_at) -> None:
        self._url = url
        self._collection = collection
        self._client_for = client_for
        self._opened: list[QdrantSearch] = []
        self._opening = threading.Lock()

    def nearest(self,
                vector: Sequence[float],
                /,
                *,
                limit: int,
                where: Sequence[Condition] = (),
                floor: float | None = None) -> list[Hit]:
        """See `VectorSearch.nearest`."""
        return self._the_search().nearest(vector, limit=limit, where=where, floor=floor)

    def _the_search(self) -> QdrantSearch:
        with self._opening:
            if not self._opened:
                self._opened.append(QdrantSearch(self._client_for(self._url), self._collection))

            return self._opened[0]


@contextmanager
def the_search_at(url: str,
                  collection: str,
                  client_for: ClientFor = a_client_at) -> Generator[QdrantSearch]:
    """One client onto the store, searching `collection`, for as long as the
    block runs.

    Not a `with` around the client itself: `QdrantClient` closes but is not a
    context manager.
    """
    client = client_for(url)

    try:
        yield QdrantSearch(client, collection)
    finally:
        client.close()


def as_filter(where: Sequence[Condition]) -> Filter | None:
    """The vendor's filter meeting every one of `where`, or none for no condition.

    `StartsWithAnyOf` is one `should` block of prefix matches, so a point meets
    it by meeting any one prefix; the blocks and the exact matches are all
    `must`, so a point meets the whole by meeting each.
    """
    if not where:
        return None

    return Filter(must=[_as_condition(condition) for condition in where])


def _as_condition(condition: Condition) -> FieldCondition | Filter:
    match condition:
        case Equals(field=field, value=value):
            return FieldCondition(key=field, match=MatchValue(value=value))
        case StartsWithAnyOf(field=field, prefixes=prefixes):
            return Filter(should=[
                FieldCondition(key=field, match=MatchPrefix(prefix=prefix))
                for prefix in prefixes
            ])


@contextmanager
def failures_translated() -> Iterator[None]:
    """The vendor's failure said as the port's: unavailable where the store failed
    for itself (a 5xx), refused where it turned the question down, and
    unreachable where no answer could be had - the client wraps a connection
    that could not be made, a request that timed out and an answer it could not
    parse alike, so they are said alike. Recall asks again only after the
    first, and the read server reports any failure to search as an index it
    could not reach.
    """
    try:
        yield
    except ResponseHandlingException as failure:
        raise VectorStoreUnreachable(str(failure)) from failure
    except UnexpectedResponse as failure:
        if (failure.status_code or 0) >= THE_STORE_FAILED:
            raise VectorStoreUnavailable(str(failure)) from failure

        raise VectorQueryRefused(str(failure)) from failure
