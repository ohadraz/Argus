"""Turning a repository's files into the points that go into the store.

The step between cutting and storing. Files in, points out: each point one
chunk, the vector that chunk embedded to, and an id derived from what it says.

A file is embedded in one call rather than a chunk at a time. Not for the round
trips - the embedder runs in this process and there are none - but because batch
inference is several times faster than the same texts one at a time. Per file
rather than per repository, so what is held at once is one file's chunks and its
vectors, whatever size the repository grows to.

An id is a hash of the path and the chunk's text, so the same passage has the
same id wherever it sits in the file. That is what lets a re-index ask the store
what it already holds and embed only what actually changed: a function pushed
down the file because something above it grew has not changed, and an id keyed
on position could not tell that from an edit. The path is in the hash too -
two files declaring an identical helper are two places a fix might belong.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from uuid import UUID

# Named here as well as in the kernel, because this is where the index's own
# callers have always reached for it and the seam did not move when its
# definition did - it was lifted once a second corpus wanted the same model.
from argus_core.embedding import Embedder
from argus_core.source_scope import belongs_to_the_service

from code_index.chunking import Chunk, chunks_of

__all__ = [
    "Candidate",
    "Embedder",
    "Point",
    "candidates_for",
    "points_of"
]


@dataclass(frozen=True)
class Point:
    """One chunk, as the store holds it.

    Wraps the chunk rather than restating its fields: what is stored is exactly
    what was cut, plus what it embedded to and what it is called.
    """

    id: str
    vector: list[float]
    chunk: Chunk


@dataclass(frozen=True)
class Candidate:
    """A chunk and what it will be called, before anything has been embedded.

    The whole reason the two steps are separate. An id is a fact about the
    text, so it can be known without a model - which is what lets the store be
    asked what it already holds while embedding is still avoidable.
    """

    id: str
    chunk: Chunk


def candidates_for(files: Mapping[str, str],
                   source_paths: str,
                   *,
                   max_lines: int,
                   overlap: int) -> list[Candidate]:
    """Every in-scope file's chunks, named and not yet embedded.

    Scope is applied here rather than after embedding. A file that is not the
    service costs nothing, where one embedded and then discarded costs exactly
    as much as one kept and is harder to notice.

    The bounds are passed through rather than read here, and they matter beyond
    the cutting: a chunk's id is derived from what it says, so re-cutting the
    same file by different bounds is a different set of passages entirely. A
    pass that used one pair and a later one that used another would leave the
    store holding both.
    """
    return [
        Candidate(id=_an_id_for(chunk), chunk=chunk)
        for path, source in files.items()
        if belongs_to_the_service(path, source_paths)
        for chunk in chunks_of(path, source, max_lines=max_lines, overlap=overlap)
    ]


def points_of(candidates: list[Candidate],
              embed: Embedder,
              held_ids: frozenset[str] = frozenset()) -> list[Point]:
    """Embeds passages already cut and named, and names them as points.

    Separate from the cutting because a pass holds the two apart: it asks the
    store what it already has before anything is embedded, which it can only do
    once the passages are named - and handing them back as files to be cut a
    second time would chunk text that is already a chunk.
    """
    wanted = [
        candidate for candidate in candidates if candidate.id not in held_ids
    ]

    return [
        point
        for path in _the_paths_among(wanted)
        for point in _embedded(
            [candidate for candidate in wanted if candidate.chunk.path == path],
            embed
        )
    ]


def _the_paths_among(candidates: list[Candidate]) -> list[str]:
    """The files these chunks came from, each named once, in the order met."""
    return list(dict.fromkeys(candidate.chunk.path for candidate in candidates))


def _embedded(candidates: list[Candidate], embed: Embedder) -> list[Point]:
    """One file's chunks, in one call to the embedder.

    The pairing of texts to vectors is the whole of what can go wrong here, and
    nothing but this `zip` guarantees it: a chunk wearing its neighbour's vector
    is retrieved for the wrong query and looks perfectly well from outside.
    `strict` rather than trusting the embedder to answer one for one - a short
    batch would otherwise drop the last chunks in silence.
    """
    if not candidates:
        return []

    vectors = embed([candidate.chunk.text for candidate in candidates])

    return [
        Point(id=candidate.id, vector=vector, chunk=candidate.chunk)
        for candidate, vector in zip(candidates, vectors, strict=True)
    ]


def _an_id_for(chunk: Chunk) -> str:
    """What this passage is called, wherever in the file it has ended up.

    A UUID rather than the bare digest, because that is what the store accepts
    as a point id - and one built from the hash rather than at random, so the
    name is a fact about the passage and not about the moment it was indexed.
    """
    digest = sha256(f"{chunk.path}\0{chunk.text}".encode()).digest()

    return str(UUID(bytes=digest[:16]))
