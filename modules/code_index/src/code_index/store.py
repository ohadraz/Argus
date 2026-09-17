"""Points, in and out of the store.

The only module here that knows Qdrant exists. Everything above it deals in
`Point` and `Chunk`, so what is stored and what is retrieved stay this module's
vocabulary to translate rather than a vendor's shape leaking up into the
indexing.

Four questions, and they are the four a re-index asks: what does this file
already have here, what does it say, put these, and forget those.

The collection is made on the first write rather than declared somewhere. A
store that has never been written to is the ordinary state of a first
deployment, and an index that refused to build until somebody had run a setup
step would be an index that does not build.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PayloadSchemaType,
    PointIdsList,
    PointStruct,
    Record,
    VectorParams,
)

from code_index.chunking import Chunk
from code_index.indexing import Point

# What a point carries beside its vector. Ours rather than the store's, and
# named because the same four strings are written on the way in and matched on
# the way out - two spellings of `first_line` would lose every line number in a
# way nothing fails over.
PATH_FIELD: Final = "path"
FIRST_LINE_FIELD: Final = "first_line"
LAST_LINE_FIELD: Final = "last_line"
TEXT_FIELD: Final = "text"

# Cosine, because these are sentence embeddings and what matters between two of
# them is direction rather than magnitude - a long passage and a short one about
# the same thing should not be far apart for being different lengths.
VECTOR_DISTANCE: Final = Distance.COSINE

# How many points are read back at once. A page rather than all of them: a file
# has few chunks and a repository has many, and the one that decides this call's
# size is the file.
MOST_POINTS_PER_PAGE: Final = 256


@dataclass(frozen=True)
class Found:
    """A passage the store offered, and how near it was.

    The score travels with the passage because nearness is the only thing a
    caller can judge an answer by: two passages come back ranked, and whether
    the second one is worth reading is a question about how far behind the first
    it was. What counts as near enough is the caller's to decide - the store
    ranks, and a threshold here would be this module inventing a policy about
    relevance it has no way to hold an opinion on.
    """

    chunk: Chunk
    score: float


def store_points(client: QdrantClient,
                 collection: str,
                 points: list[Point],
                 width: int) -> None:
    """Puts these points in, making the collection if it is not there yet.

    An upsert rather than an insert, which is what makes a re-index safe to
    repeat: a pass killed halfway and run again writes the same ids over the
    ones it already wrote, instead of leaving the collection holding two of
    everything.
    """
    if not points:
        return

    _a_collection_that_exists(client, collection, width)

    client.upsert(
        collection_name=collection,
        points=[
            PointStruct(
                id=point.id,
                vector=point.vector,
                payload={
                    PATH_FIELD: point.chunk.path,
                    FIRST_LINE_FIELD: point.chunk.first_line,
                    LAST_LINE_FIELD: point.chunk.last_line,
                    TEXT_FIELD: point.chunk.text
                }
            )
            for point in points
        ]
    )


def ids_held_for(client: QdrantClient, collection: str, path: str) -> set[str]:
    """What the store already has for this file.

    The question that makes embedding avoidable: a chunk whose id is in here is
    a chunk the store already holds, word for word, and nothing needs to be
    embedded for it again.

    A store with no collection yet holds nothing, which is an answer rather than
    a failure - it is the ordinary state before the first index, and it means
    "all of it is new".
    """
    return {
        str(point.id)
        for point in _points_of(client, collection, path, with_payload=False)
    }


def chunks_held_for(client: QdrantClient,
                    collection: str,
                    path: str) -> list[Chunk]:
    """What the store has for this file, said back as the passages it holds."""
    return [
        _a_chunk_from(point.payload or {})
        for point in _points_of(client, collection, path, with_payload=True)
    ]


def nearest(client: QdrantClient,
            collection: str,
            vector: list[float],
            limit: int) -> list[Found]:
    """The passages nearest `vector`, nearest first, at most `limit` of them.

    Ranked, because a caller that trusts the order and is handed an arbitrary
    one reads the least relevant passage first and spends its turn on it.

    A store that has never been written to finds nothing, which is answered
    rather than raised: before the first index there is nothing to find, and
    that is a fact about the index rather than a failure of the store.
    """
    if not client.collection_exists(collection):
        return []

    return [
        Found(chunk=_a_chunk_from(point.payload or {}), score=point.score)
        for point in client.query_points(
            collection_name=collection,
            query=vector,
            limit=limit,
            with_payload=True
        ).points
    ]


def forget(client: QdrantClient, collection: str, ids: list[str]) -> None:
    """Drops these points.

    The other half of a re-index. A passage that was edited away leaves a point
    matching nothing in the file, and retrieval would go on answering with it.
    """
    if not ids:
        return

    client.delete(
        collection_name=collection,
        points_selector=PointIdsList(points=list(ids))
    )


def _a_collection_that_exists(client: QdrantClient,
                              collection: str,
                              width: int) -> None:
    """Makes the collection, and the index on the field every query filters by.

    The payload index is not an optimisation to add later. Every query here
    filters by path, and filtering during the search rather than after it is the
    whole reason this store was chosen - without the index Qdrant has nothing to
    traverse the filter with and falls back to scanning.
    """
    if client.collection_exists(collection):
        return

    client.create_collection(
        collection_name=collection,
        vectors_config=VectorParams(size=width, distance=VECTOR_DISTANCE)
    )
    client.create_payload_index(
        collection_name=collection,
        field_name=PATH_FIELD,
        field_schema=PayloadSchemaType.KEYWORD
    )


def _points_of(client: QdrantClient,
               collection: str,
               path: str,
               with_payload: bool) -> list[Record]:
    """Every point the store holds for one file, a page at a time.

    Paged rather than taken in one call, because "every point for this file" is
    unbounded from here: a long module is many chunks, and a limit chosen to
    look generous is a limit that silently truncates the day somebody writes a
    longer one.
    """
    if not client.collection_exists(collection):
        return []

    found: list[Record] = []
    offset = None

    while True:
        page, offset = client.scroll(
            collection_name=collection,
            scroll_filter=Filter(
                must=[
                    FieldCondition(
                        key=PATH_FIELD, match=MatchValue(value=path)
                    )
                ]
            ),
            limit=MOST_POINTS_PER_PAGE,
            offset=offset,
            with_payload=with_payload,
            with_vectors=False
        )
        found.extend(page)

        if offset is None:
            return found


def _a_chunk_from(payload: dict[str, object]) -> Chunk:
    """The passage a stored payload describes."""
    return Chunk(
        path=str(payload[PATH_FIELD]),
        first_line=int(str(payload[FIRST_LINE_FIELD])),
        last_line=int(str(payload[LAST_LINE_FIELD])),
        text=str(payload[TEXT_FIELD])
    )
