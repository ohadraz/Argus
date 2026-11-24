"""Points, in and out of the store.

The only module here that knows what a point carries. Everything above it deals
in `Point` and `Chunk`, and everything below it is the store's port - so what is
stored and what is retrieved stay this module's vocabulary to translate, and no
vendor's shape leaks up into the indexing or down out of it.

Four questions, and they are the four a re-index asks: what does this file
already have here, what does it say, put these, and forget those. And one a
reader asks: what is near this, inside the service's own source.

The collection is made on the first write rather than declared somewhere. A
store that has never been written to is the ordinary state of a first
deployment, and an index that refused to build until somebody had run a setup
step would be an index that does not build.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from core.source_scope import the_prefixes_of
from core.vector_store import (
    Condition,
    Equals,
    Payload,
    StartsWithAnyOf,
    StoredVector,
    VectorIndex,
    VectorSearch,
)

from repository_index.chunking import Chunk
from repository_index.indexing import Point

# What a point carries beside its vector. Ours rather than the store's, and
# named because the same four strings are written on the way in and matched on
# the way out - two spellings of `first_line` would lose every line number in a
# way nothing fails over.
PATH_FIELD: Final = "path"
FIRST_LINE_FIELD: Final = "first_line"
LAST_LINE_FIELD: Final = "last_line"
TEXT_FIELD: Final = "text"


@dataclass(frozen=True)
class Found:
    """A passage the store offered, and how near it was.

    The score travels with the passage because nearness is the only thing a
    caller can judge an answer by: two passages come back ranked, and whether
    the second one is worth reading is a question about how far behind the first
    it was. What counts as near enough is the caller's to decide, and the caller
    says so in the question - the store ranks, and a threshold invented here
    would be this module holding a policy about relevance it has no way to hold.
    """

    chunk: Chunk
    score: float


def store_points(index: VectorIndex, points: list[Point], width: int) -> None:
    """Puts these points in, making the collection if it is not there yet.

    An upsert rather than an insert, which is what makes a re-index safe to
    repeat: a pass killed halfway and run again writes the same ids over the
    ones it already wrote, instead of leaving the collection holding two of
    everything.

    The path is indexed to be matched by prefix, because that is how a reader
    asks for the service's own source (`nearest`).
    """
    if not points:
        return

    index.ensure(width=width, indexed_field=PATH_FIELD, matched_by_prefix=True)
    index.upsert([
        StoredVector(
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
    ])


def ids_held_for(index: VectorIndex, path: str) -> set[str]:
    """What the store already has for this file.

    The question that makes embedding avoidable: a chunk whose id is in here is
    a chunk the store already holds, word for word, and nothing needs to be
    embedded for it again.

    A store with no collection yet holds nothing, which is an answer rather than
    a failure - it is the ordinary state before the first index, and it means
    "all of it is new".
    """
    return {held.id for held in index.held([_the_file(path)], with_payload=False)}


def chunks_held_for(index: VectorIndex, path: str) -> list[Chunk]:
    """What the store has for this file, said back as the passages it holds."""
    return [
        _a_chunk_from(held.payload)
        for held in index.held([_the_file(path)], with_payload=True)
    ]


def nearest(search: VectorSearch,
            vector: list[float],
            limit: int,
            *,
            floor: float | None = None,
            source_paths: str = "") -> list[Found]:
    """The passages nearest `vector` inside `source_paths` and no further off
    than `floor`, nearest first, at most `limit` of them.

    Ranked, because a caller that trusts the order and is handed an arbitrary
    one reads the least relevant passage first and spends its turn on it.

    Scoped and floored inside the search rather than after it. The scope is
    part of the recipe a collection is named for, so a deployment's reader
    searches only a collection built under its own scope, and the condition
    excludes nothing there. It is asked all the same, so what a caller is
    answered from never rests on which collection it was handed: one built
    under a wider scope holds passages outside it. A store answers its `limit`
    nearest, and where those outside passages are nearer, a scope applied to
    them afterwards answers with fewer passages than there are in the service,
    and sometimes with none. `source_paths` is read as
    `core.source_scope` reads it: empty scopes nothing.

    A store that has never been written to finds nothing, which is answered
    rather than raised: before the first index there is nothing to find, and
    that is a fact about the index rather than a failure of the store.
    """
    return [
        Found(chunk=_a_chunk_from(hit.payload), score=hit.score)
        for hit in search.nearest(
            vector, limit=limit, where=in_scope(source_paths), floor=floor
        )
    ]


def in_scope(source_paths: str) -> list[Condition]:
    """The condition a passage meets by being the service's own, or none where
    the deployment scoped nothing."""
    prefixes = the_prefixes_of(source_paths)

    return [StartsWithAnyOf(field=PATH_FIELD, prefixes=prefixes)] if prefixes else []


def forget(index: VectorIndex, ids: list[str]) -> None:
    """Drops these points.

    The other half of a re-index. A passage that was edited away leaves a point
    matching nothing in the file, and retrieval would go on answering with it.
    """
    index.delete(ids)


def _the_file(path: str) -> Condition:
    """The condition a point meets by being cut from this one file."""
    return Equals(field=PATH_FIELD, value=path)


def _a_chunk_from(payload: Payload) -> Chunk:
    """The passage a stored payload describes."""
    return Chunk(
        path=str(payload[PATH_FIELD]),
        first_line=int(str(payload[FIRST_LINE_FIELD])),
        last_line=int(str(payload[LAST_LINE_FIELD])),
        text=str(payload[TEXT_FIELD])
    )
