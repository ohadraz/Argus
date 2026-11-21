"""Filling a Qdrant collection - `VectorIndex`, answered by the vendor.

The writing side, built by the processes that fill a corpus and walk no run: the
deliverer, which carries filed records into long-term memory, and the index's
catch-up loop. No walk imports this module - the walk's contract forbids it - so
a write made for a run since taken back is not a write a walk can make.

The collection is made on the first write rather than declared somewhere. A store
that has never been written to is the ordinary state of a first deployment, and a
corpus that refused to fill until somebody had run a setup step would be a corpus
nobody has.
"""

from __future__ import annotations

from collections.abc import Generator, Sequence
from contextlib import contextmanager
from typing import Final

from core.vector_store import Condition, Held, Hit, StoredVector
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    KeywordIndexParams,
    KeywordIndexType,
    PayloadIndexInfo,
    PayloadSchemaType,
    PointIdsList,
    PointStruct,
    Record,
    VectorParams,
)

from vector_store_qdrant.searching import (
    ClientFor,
    QdrantSearch,
    a_client_at,
    as_filter,
    failures_translated,
)

# Cosine, for every corpus. The embedders in use answer normalised vectors, so
# cosine and dot product agree - and where they disagree, cosine is the one that
# does not quietly reward a long document for being long.
VECTOR_DISTANCE: Final = Distance.COSINE

# How many points are read back at once. A page rather than all of them: what a
# caller asks for under one condition is unbounded from here, and a limit chosen
# to look generous is one that silently truncates the day somebody writes more.
MOST_POINTS_PER_PAGE: Final = 256


class QdrantIndex:
    """`VectorIndex` over one collection of one Qdrant, through a client the
    caller opened and will close.

    Its search is the reading side's own rather than a second translation of
    one, so a corpus searched by its builder and by a walk is searched the same
    way.
    """

    def __init__(self, client: QdrantClient, collection: str) -> None:
        self._writing_to = client
        self._collection = collection
        self._search = QdrantSearch(client, collection)

    def nearest(self,
                vector: Sequence[float],
                /,
                *,
                limit: int,
                where: Sequence[Condition] = (),
                floor: float | None = None) -> list[Hit]:
        """See `VectorSearch.nearest`."""
        return self._search.nearest(vector, limit=limit, where=where, floor=floor)

    def ensure(self, *, width: int, indexed_field: str, matched_by_prefix: bool = False) -> None:
        """Makes the collection if it is not there, with an index on one field.

        The payload index is not an optimisation to add later. Every search
        narrows by a field, and filtering during the search rather than after it
        is the whole reason a store like this was chosen: without the index
        Qdrant has nothing to traverse the filter with and falls back to scanning.

        `width` is read off the vectors the caller is about to store rather than
        configured, because it is a fact about the model that produced them.

        A collection already there keeps its points, and has its field indexed
        again where the index it has cannot answer what is now asked of it - a
        field indexed before it was matched by prefix. Rebuilt in place rather
        than left for somebody to drop the collection: a prefix asked of a plain
        keyword index is still answered, by a scan, so nothing would ever say
        the collection needed it.
        """
        with failures_translated():
            if not self._writing_to.collection_exists(self._collection):
                self._writing_to.create_collection(
                    collection_name=self._collection,
                    vectors_config=VectorParams(size=width, distance=VECTOR_DISTANCE)
                )

            indexed = self._writing_to.get_collection(self._collection).payload_schema.get(
                indexed_field
            )

            if indexed is not None and (not matched_by_prefix or _matches_by_prefix(indexed)):
                return

            if indexed is not None:
                self._writing_to.delete_payload_index(
                    collection_name=self._collection,
                    field_name=indexed_field
                )

            self._writing_to.create_payload_index(
                collection_name=self._collection,
                field_name=indexed_field,
                field_schema=(
                    KeywordIndexParams(type=KeywordIndexType.KEYWORD, prefix=True)
                    if matched_by_prefix
                    else PayloadSchemaType.KEYWORD
                )
            )

    def upsert(self, vectors: Sequence[StoredVector], /) -> None:
        """See `VectorIndex.upsert`. Nothing to keep asks nothing of the store."""
        if not vectors:
            return

        with failures_translated():
            self._writing_to.upsert(
                collection_name=self._collection,
                points=[
                    PointStruct(id=one.id, vector=list(one.vector), payload=dict(one.payload))
                    for one in vectors
                ]
            )

    def delete(self, ids: Sequence[str], /) -> None:
        """See `VectorIndex.delete`. Nothing to forget asks nothing of the store."""
        if not ids:
            return

        with failures_translated():
            self._writing_to.delete(
                collection_name=self._collection,
                points_selector=PointIdsList(points=list(ids))
            )

    def held(self, where: Sequence[Condition], /, *, with_payload: bool) -> list[Held]:
        """See `VectorIndex.held`. Read a page at a time, and nothing from a
        collection nobody has written to yet."""
        with failures_translated():
            if not self._writing_to.collection_exists(self._collection):
                return []

            found: list[Record] = []
            offset = None

            while True:
                page, offset = self._writing_to.scroll(
                    collection_name=self._collection,
                    scroll_filter=as_filter(where),
                    limit=MOST_POINTS_PER_PAGE,
                    offset=offset,
                    with_payload=with_payload,
                    with_vectors=False
                )
                found.extend(page)

                if offset is None:
                    return [Held(id=str(one.id), payload=dict(one.payload or {})) for one in found]


def _matches_by_prefix(indexed: PayloadIndexInfo) -> bool:
    """Whether a field's index serves a prefix, as the store describes it."""
    return isinstance(indexed.params, KeywordIndexParams) and bool(indexed.params.prefix)


@contextmanager
def the_index_at(url: str,
                 collection: str,
                 client_for: ClientFor = a_client_at) -> Generator[QdrantIndex]:
    """One client onto the store, filling `collection`, for as long as the block
    runs."""
    client = client_for(url)

    try:
        yield QdrantIndex(client, collection)
    finally:
        client.close()
