"""Points, in and out of a real store.

The half of the index that cannot be asserted against a double. Whether a
payload survives the round trip, whether a filter selects only the path it
names, whether the same id written twice is one row or two - a stand-in answers
all three the way whoever wrote it expected, which is the one answer worth
nothing.

So this suite is thin on cleverness and thick on round trips: every test writes
through the functions production writes through, and reads back through the ones
it reads through, against the store it talks to.

The collection is made on the first write rather than declared somewhere. A
store that has never been written to is the ordinary state of a first
deployment, and an index that refused to build until somebody had run a setup
step would be an index that does not build.
"""

from __future__ import annotations

from uuid import NAMESPACE_URL, uuid5

import pytest
from argus_testkit import Assertion, Scenario, all_of
from code_index.chunking import Chunk
from code_index.indexing import Point
from code_index.store import Found, chunks_held_for, forget, ids_held_for, nearest, store_points
from qdrant_client import QdrantClient

SOME_COLLECTION = "code_index_component_test"

SOME_PATH = "src/shop/summary.py"
ANOTHER_PATH = "src/shop/accounts.py"

SOME_TEXT = "def summary() -> None: ..."
ANOTHER_TEXT = "def total() -> None: ..."

# Nothing here is about similarity - these tests are about storage - so the
# vectors are short and the width is declared once. A store is entitled to
# refuse a vector that disagrees with the collection it is going into, which is
# itself worth having pinned.
SOME_WIDTH = 4


@pytest.mark.component
def test_a_point_written_can_be_found_again_by_its_path(
    store: QdrantClient
) -> None:
    some_point = _a_point(SOME_PATH, SOME_TEXT)

    Scenario() \
        .given(_stored(store, [some_point])) \
        .when(lambda: ids_held_for(store, SOME_COLLECTION, SOME_PATH)) \
        .then(_exactly_these_ids({some_point.id}))


@pytest.mark.component
def test_the_ids_held_for_one_path_leave_out_another_paths(
    store: QdrantClient
) -> None:
    # The filter, which is what this store was chosen for. A re-index asks what
    # it holds for the file it is re-indexing, and an answer that swept in the
    # neighbours would have it delete points belonging to a file nobody touched.
    some_point = _a_point(SOME_PATH, SOME_TEXT)
    another_point = _a_point(ANOTHER_PATH, ANOTHER_TEXT)

    Scenario() \
        .given(_stored(store, [some_point, another_point])) \
        .when(lambda: ids_held_for(store, SOME_COLLECTION, SOME_PATH)) \
        .then(_exactly_these_ids({some_point.id}))


@pytest.mark.component
def test_a_path_the_store_has_never_seen_holds_nothing(
    store: QdrantClient
) -> None:
    # Answered, not raised. A file new to the index is the ordinary case on
    # every push, and it means "embed all of it" rather than "the store broke".
    Scenario() \
        .given(_stored(store, [_a_point(SOME_PATH, SOME_TEXT)])) \
        .when(lambda: ids_held_for(store, SOME_COLLECTION, ANOTHER_PATH)) \
        .then(_exactly_these_ids(set()))


@pytest.mark.component
def test_a_collection_that_does_not_exist_is_made_on_the_first_write(
    store: QdrantClient
) -> None:
    # The first deployment: nothing has run a setup step, and the index must
    # still build. Nothing is stored in the `given` - that is the point.
    some_point = _a_point(SOME_PATH, SOME_TEXT)

    Scenario() \
        .when(lambda: _stored_then_held(store, [some_point], SOME_PATH)) \
        .then(_exactly_these_ids({some_point.id}))


@pytest.mark.component
def test_writing_the_same_id_twice_leaves_one_point(
    store: QdrantClient
) -> None:
    # What makes a re-index safe to repeat. A pass killed halfway and run again
    # must not leave the collection holding two of everything it had written.
    some_point = _a_point(SOME_PATH, SOME_TEXT)

    Scenario() \
        .given(_stored(store, [some_point])) \
        .when(lambda: _stored_then_held(store, [some_point], SOME_PATH)) \
        .then(_exactly_these_ids({some_point.id}))


@pytest.mark.component
def test_a_point_that_was_forgotten_is_no_longer_held(
    store: QdrantClient
) -> None:
    # The delete side of a re-index: a passage edited away leaves a point
    # matching nothing in the file, and retrieval would go on answering with it.
    some_point = _a_point(SOME_PATH, SOME_TEXT)
    another_point = _a_point(SOME_PATH, ANOTHER_TEXT)

    Scenario() \
        .given(_stored(store, [some_point, another_point])) \
        .when(lambda: _forgotten_then_held(store, [some_point.id], SOME_PATH)) \
        .then(_exactly_these_ids({another_point.id}))


@pytest.mark.component
def test_a_point_is_read_back_exactly_as_it_was_written(
    store: QdrantClient
) -> None:
    # The payload, not only the id. A chunk whose line span came back wrong
    # sends a reader to the wrong part of the right file, which is worse than
    # not answering at all.
    some_first_line = 12
    some_last_line = 19
    some_point = _a_point(
        SOME_PATH, SOME_TEXT, first_line=some_first_line, last_line=some_last_line
    )

    Scenario() \
        .given(_stored(store, [some_point])) \
        .when(lambda: _the_only_chunk_held_for(store, SOME_PATH)) \
        .then(
            all_of(
                _the_chunk_names(SOME_PATH),
                _the_chunk_spans(some_first_line, some_last_line),
                _the_chunk_reads(SOME_TEXT)
            )
        )


@pytest.mark.component
def test_the_passage_nearest_a_query_comes_back_first(
    store: QdrantClient
) -> None:
    # What retrieval is for. The vectors here are hand-made rather than
    # embedded: what is under test is that the store ranks by nearness and
    # hands back the passage, not that a model has good taste.
    near = _a_point(SOME_PATH, SOME_TEXT, vector=[1.0, 0.0, 0.0, 0.0])
    far = _a_point(ANOTHER_PATH, ANOTHER_TEXT, vector=[0.0, 1.0, 0.0, 0.0])

    Scenario() \
        .given(_stored(store, [near, far])) \
        .when(lambda: nearest(store, SOME_COLLECTION, [1.0, 0.0, 0.0, 0.0], limit=2)) \
        .then(
            all_of(
                _the_nearest_passage_reads(SOME_TEXT),
                _they_are_ordered_by_nearness()
            )
        )


@pytest.mark.component
def test_no_more_passages_come_back_than_were_asked_for(
    store: QdrantClient
) -> None:
    # The bound is the caller's. A model handed forty passages spends its
    # context on thirty-seven it will not read.
    Scenario() \
        .given(
            _stored(store, [
                _a_point(SOME_PATH, SOME_TEXT, vector=[1.0, 0.0, 0.0, 0.0]),
                _a_point(ANOTHER_PATH, ANOTHER_TEXT, vector=[0.9, 0.1, 0.0, 0.0])
            ])
        ) \
        .when(lambda: nearest(store, SOME_COLLECTION, [1.0, 0.0, 0.0, 0.0], limit=1)) \
        .then(_at_most_this_many_came_back(1))


@pytest.mark.component
def test_a_store_that_has_never_been_written_to_finds_nothing(
    store: QdrantClient
) -> None:
    # Answered rather than raised. Before the first index there is nothing to
    # find, which is a fact about the index and not a failure of the store.
    Scenario() \
        .when(lambda: nearest(store, SOME_COLLECTION, [1.0, 0.0, 0.0, 0.0], limit=5)) \
        .then(_nothing_came_back())


def _a_point(path: str,
             text: str,
             first_line: int = 1,
             last_line: int = 2,
             vector: list[float] | None = None) -> Point:
    """A point with an id of its own.

    Named here rather than through `candidates_for`, because what is under test
    is the store: a point whose id came from the indexing module would make
    these tests fail when *that* module changed, about something they do not
    cover.
    """
    return Point(
        id=str(uuid5(NAMESPACE_URL, f"{path}:{text}")),
        vector=vector or [0.1] * SOME_WIDTH,
        chunk=Chunk(
            path=path, first_line=first_line, last_line=last_line, text=text
        )
    )


def _stored(store: QdrantClient, points: list[Point]) -> list[Point]:
    """Writes the points, and hands them back so a `given` can name them."""
    store_points(store, SOME_COLLECTION, points, width=SOME_WIDTH)

    return points


def _stored_then_held(store: QdrantClient,
                      points: list[Point],
                      path: str) -> set[str]:
    """Writes, then reads back - the round trip as one subject to assert on."""
    _stored(store, points)

    return ids_held_for(store, SOME_COLLECTION, path)


def _forgotten_then_held(store: QdrantClient,
                         ids: list[str],
                         path: str) -> set[str]:
    forget(store, SOME_COLLECTION, ids)

    return ids_held_for(store, SOME_COLLECTION, path)


def _the_only_chunk_held_for(store: QdrantClient, path: str) -> Chunk:
    [chunk] = chunks_held_for(store, SOME_COLLECTION, path)

    return chunk


def _exactly_these_ids(expected: set[str]) -> Assertion[set[str]]:
    def exactly_these_ids(ids: set[str]) -> bool:
        if ids != expected:
            raise AssertionError(
                f"Expected exactly {sorted(expected)}, "
                f"and {sorted(ids)} came back."
            )

        return True

    return exactly_these_ids


def _the_chunk_names(path: str) -> Assertion[Chunk]:
    def the_chunk_names(chunk: Chunk) -> bool:
        if chunk.path != path:
            raise AssertionError(
                f"Expected the chunk to name [{path}], "
                f"and it named [{chunk.path}]."
            )

        return True

    return the_chunk_names


def _the_chunk_spans(first_line: int, last_line: int) -> Assertion[Chunk]:
    def the_chunk_spans(chunk: Chunk) -> bool:
        if (chunk.first_line, chunk.last_line) != (first_line, last_line):
            raise AssertionError(
                f"Expected the chunk to span [{first_line}-{last_line}], "
                f"and it spanned [{chunk.first_line}-{chunk.last_line}]."
            )

        return True

    return the_chunk_spans


def _the_chunk_reads(text: str) -> Assertion[Chunk]:
    def the_chunk_reads(chunk: Chunk) -> bool:
        if chunk.text != text:
            raise AssertionError(
                f"Expected the chunk to read [{text}], "
                f"and it read [{chunk.text}]."
            )

        return True

    return the_chunk_reads


def _the_nearest_passage_reads(text: str) -> Assertion[list[Found]]:
    def the_nearest_passage_reads(found: list[Found]) -> bool:
        if not found:
            raise AssertionError(
                f"Expected the nearest passage to read [{text}], "
                f"and nothing came back at all."
            )

        if found[0].chunk.text != text:
            raise AssertionError(
                f"Expected the nearest passage to read [{text}], and it read "
                f"[{found[0].chunk.text}]. What came back, nearest first: "
                f"{[one.chunk.text for one in found]}."
            )

        return True

    return the_nearest_passage_reads


def _at_most_this_many_came_back(expected: int) -> Assertion[list[Found]]:
    def at_most_this_many_came_back(found: list[Found]) -> bool:
        if len(found) > expected:
            raise AssertionError(
                f"Expected at most [{expected}] passages, "
                f"and [{len(found)}] came back."
            )

        return True

    return at_most_this_many_came_back


def _they_are_ordered_by_nearness() -> Assertion[list[Found]]:
    """That what came back is ranked, nearest first.

    Asked because a caller that trusts the order and is handed an arbitrary one
    reads the least relevant passage first and spends its turn on it.
    """
    def they_are_ordered_by_nearness(found: list[Found]) -> bool:
        scores = [one.score for one in found]

        if scores != sorted(scores, reverse=True):
            raise AssertionError(
                f"Expected the passages nearest first, and their scores ran "
                f"{scores}."
            )

        return True

    return they_are_ordered_by_nearness


def _nothing_came_back() -> Assertion[list[Found]]:
    def nothing_came_back(found: list[Found]) -> bool:
        if found:
            raise AssertionError(
                f"Expected nothing from a store that has never been written to, "
                f"and [{len(found)}] passages came back."
            )

        return True

    return nothing_came_back
