"""The index's half of the store: points in and out of a real one, and what a
search asks before any store answers it.

The round trips are the half that cannot be asserted against a double. Whether
a payload survives, whether a filter selects only the path it names, whether
the same id written twice is one row or two - a stand-in answers all three the
way whoever wrote it expected, which is the one answer worth nothing. So these
are thin on cleverness and thick on round trips: every case writes through the
functions production writes through, and reads back through the ones it reads
through, against a real Qdrant through the store's adapter.

The collection is made on the first write rather than declared somewhere. A
store that has never been written to is the ordinary state of a first
deployment, and an index that refused to build until somebody had run a setup
step would be an index that does not build.

What is this module's and no store's - a deployment's scope said as a condition
on the path every passage carries - is asked without one.
"""

from __future__ import annotations

from uuid import NAMESPACE_URL, uuid5

import pytest
from argus_testkit import Assertion, Scenario, all_of, the_answer_was
from core.vector_store import StartsWithAnyOf
from qdrant_client import QdrantClient
from qdrant_client.models import CollectionInfo, KeywordIndexParams, PayloadSchemaType
from repository_index.chunking import Chunk
from repository_index.indexing import Point
from repository_index.store import (
    PATH_FIELD,
    Found,
    chunks_held_for,
    forget,
    ids_held_for,
    in_scope,
    nearest,
    store_points,
)
from vector_store_qdrant.indexing import QdrantIndex

SOME_SERVICE_DIRECTORY = "src/io_shop"
SOME_TESTS_DIRECTORY = "tests/io_shop"

# The collection conftest's `store` keeps passages in, mirrored for the one case
# that asks the vendor what it made of it.
THE_STORES_COLLECTION = "repository_index_test"
SOME_PATH = "src/shop/summary.py"
ANOTHER_PATH = "src/shop/accounts.py"
SOME_PATH_OUTSIDE_THE_SERVICE = "src/elsewhere/scenarios.py"
SOME_TEXT = "def summary() -> None: ..."
ANOTHER_TEXT = "def total() -> None: ..."
# Nothing here is about similarity - these tests are about storage - so the
# vectors are short and the width is declared once. A store is entitled to
# refuse a vector that disagrees with the collection it is going into, which is
# itself worth having pinned.
SOME_WIDTH = 4


@pytest.mark.integration
def test_a_point_written_can_be_found_again_by_its_path(
    store: QdrantIndex
) -> None:
    some_point = _a_point(SOME_PATH, SOME_TEXT)

    Scenario() \
        .given(_stored(store, [some_point])) \
        .when(lambda: ids_held_for(store, SOME_PATH)) \
        .then(_exactly_these_ids({some_point.id}))


@pytest.mark.integration
def test_the_ids_held_for_one_path_leave_out_another_paths(
    store: QdrantIndex
) -> None:
    # The filter, which is what this store was chosen for. A re-index asks what
    # it holds for the file it is re-indexing, and an answer that swept in the
    # neighbours would have it delete points belonging to a file nobody touched.
    some_point = _a_point(SOME_PATH, SOME_TEXT)
    another_point = _a_point(ANOTHER_PATH, ANOTHER_TEXT)

    Scenario() \
        .given(_stored(store, [some_point, another_point])) \
        .when(lambda: ids_held_for(store, SOME_PATH)) \
        .then(_exactly_these_ids({some_point.id}))


@pytest.mark.integration
def test_a_path_the_store_has_never_seen_holds_nothing(
    store: QdrantIndex
) -> None:
    # Answered, not raised. A file new to the index is the ordinary case on
    # every push, and it means "embed all of it" rather than "the store broke".
    Scenario() \
        .given(_stored(store, [_a_point(SOME_PATH, SOME_TEXT)])) \
        .when(lambda: ids_held_for(store, ANOTHER_PATH)) \
        .then(_exactly_these_ids(set()))


@pytest.mark.integration
def test_a_collection_that_does_not_exist_is_made_on_the_first_write(
    store: QdrantIndex
) -> None:
    # The first deployment: nothing has run a setup step, and the index must
    # still build. Nothing is stored in the `given` - that is the point.
    some_point = _a_point(SOME_PATH, SOME_TEXT)

    Scenario() \
        .when(lambda: _stored_then_held(store, [some_point], SOME_PATH)) \
        .then(_exactly_these_ids({some_point.id}))


@pytest.mark.integration
def test_writing_the_same_id_twice_leaves_one_point(
    store: QdrantIndex
) -> None:
    # What makes a re-index safe to repeat. A pass killed halfway and run again
    # must not leave the collection holding two of everything it had written.
    some_point = _a_point(SOME_PATH, SOME_TEXT)

    Scenario() \
        .given(_stored(store, [some_point])) \
        .when(lambda: _stored_then_held(store, [some_point], SOME_PATH)) \
        .then(_exactly_these_ids({some_point.id}))


@pytest.mark.integration
def test_a_point_that_was_forgotten_is_no_longer_held(
    store: QdrantIndex
) -> None:
    # The delete side of a re-index: a passage edited away leaves a point
    # matching nothing in the file, and retrieval would go on answering with it.
    some_point = _a_point(SOME_PATH, SOME_TEXT)
    another_point = _a_point(SOME_PATH, ANOTHER_TEXT)

    Scenario() \
        .given(_stored(store, [some_point, another_point])) \
        .when(lambda: _forgotten_then_held(store, [some_point.id], SOME_PATH)) \
        .then(_exactly_these_ids({another_point.id}))


@pytest.mark.integration
def test_a_point_is_read_back_exactly_as_it_was_written(
    store: QdrantIndex
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


@pytest.mark.integration
def test_the_passage_nearest_a_query_comes_back_first(
    store: QdrantIndex
) -> None:
    # What retrieval is for. The vectors here are hand-made rather than
    # embedded: what is under test is that the store ranks by nearness and
    # hands back the passage, not that a model has good taste.
    near = _a_point(SOME_PATH, SOME_TEXT, vector=[1.0, 0.0, 0.0, 0.0])
    far = _a_point(ANOTHER_PATH, ANOTHER_TEXT, vector=[0.0, 1.0, 0.0, 0.0])

    Scenario() \
        .given(_stored(store, [near, far])) \
        .when(lambda: nearest(store, [1.0, 0.0, 0.0, 0.0], limit=2)) \
        .then(
            all_of(
                _the_nearest_passage_reads(SOME_TEXT),
                _they_are_ordered_by_nearness()
            )
        )


@pytest.mark.integration
def test_no_more_passages_come_back_than_were_asked_for(
    store: QdrantIndex
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
        .when(lambda: nearest(store, [1.0, 0.0, 0.0, 0.0], limit=1)) \
        .then(_at_most_this_many_came_back(1))


@pytest.mark.integration
def test_a_store_that_has_never_been_written_to_finds_nothing(
    store: QdrantIndex
) -> None:
    # Answered rather than raised. Before the first index there is nothing to
    # find, which is a fact about the index and not a failure of the store.
    Scenario() \
        .when(lambda: nearest(store, [1.0, 0.0, 0.0, 0.0], limit=5)) \
        .then(_nothing_came_back())


@pytest.mark.integration
def test_a_passage_outside_the_service_is_not_answered_even_when_it_is_the_nearest(
    store: QdrantIndex
) -> None:
    # Scoped inside the search, which is the defect this exists for. A
    # deployment's reader searches only the collection its own scope built, and
    # the scope is asked all the same so the answer never rests on which
    # collection the search was handed: one built under a wider scope holds
    # passages outside it, and where one of those is the nearest, asked for the
    # one nearest and scoped afterwards, the answer was nothing, while the
    # service's own passage sat second in the ranking.
    the_service_lives_in = SOME_PATH.rsplit("/", 1)[0]
    indexed_wider = _a_point(SOME_PATH_OUTSIDE_THE_SERVICE, ANOTHER_TEXT,
                             vector=[1.0, 0.0, 0.0, 0.0])
    the_services_own = _a_point(SOME_PATH, SOME_TEXT, vector=[0.9, 0.1, 0.0, 0.0])
    room_for_one = 1

    Scenario() \
        .given(_stored(store, [indexed_wider, the_services_own])) \
        .when(lambda: nearest(store, [1.0, 0.0, 0.0, 0.0], limit=room_for_one,
                              source_paths=the_service_lives_in)) \
        .then(_the_nearest_passage_reads(SOME_TEXT))


@pytest.mark.integration
def test_a_passage_further_off_than_the_floor_is_not_answered(
    store: QdrantIndex
) -> None:
    # Floored inside the search: a store always answers its k nearest, however
    # far away they are, and what is not near enough must not reach a caller.
    near = _a_point(SOME_PATH, SOME_TEXT, vector=[1.0, 0.0, 0.0, 0.0])
    far = _a_point(ANOTHER_PATH, ANOTHER_TEXT, vector=[0.0, 1.0, 0.0, 0.0])
    a_floor_only_the_near_one_clears = 0.5

    Scenario() \
        .given(_stored(store, [near, far])) \
        .when(lambda: nearest(store, [1.0, 0.0, 0.0, 0.0], limit=2,
                              floor=a_floor_only_the_near_one_clears)) \
        .then(all_of(
            _the_nearest_passage_reads(SOME_TEXT),
            _at_most_this_many_came_back(1)
        ))


@pytest.mark.integration
def test_the_field_every_query_filters_by_is_indexed(store: QdrantIndex,
                                                      client: QdrantClient) -> None:
    # The property the provisioning exists for, and the one thing here that
    # nothing else would notice the loss of. Every case above filters by path
    # and passes either way: without the payload index Qdrant answers the same
    # questions by scanning the collection instead of traversing an index -
    # correct, and slower with every file added, which surfaces as a search
    # that used to be quick rather than as a failure.
    #
    # Only a real store can answer this. The in-memory client accepts the call,
    # warns that payload indexes do nothing locally, and reports no schema.
    Scenario() \
        .given(_stored(store, [_a_point(SOME_PATH, SOME_TEXT)])) \
        .when(lambda: client.get_collection(THE_STORES_COLLECTION)) \
        .then(all_of(
            _the_payload_field_indexed_is(PATH_FIELD),
            # The path is asked by prefix - a reader's scope - and a keyword index
            # that cannot serve one answers a scope by scanning, as surely as no
            # index at all.
            _the_payload_field_serves_a_prefix(PATH_FIELD)
        ))


@pytest.mark.unit
def test_a_scope_is_asked_as_the_paths_starting_with_any_of_its_directories() -> None:
    # Read as `core.source_scope` reads it - space after a comma included - so
    # a passage the substring channel answers from is one the index offers.
    Scenario() \
        .given(the_service_lives_in := f"{SOME_SERVICE_DIRECTORY}, {SOME_TESTS_DIRECTORY}") \
        .when(lambda: in_scope(the_service_lives_in)) \
        .then(the_answer_was([
            StartsWithAnyOf(field=PATH_FIELD,
                            prefixes=(SOME_SERVICE_DIRECTORY, SOME_TESTS_DIRECTORY))
        ]))


@pytest.mark.unit
def test_a_deployment_that_scoped_nothing_asks_for_no_condition() -> None:
    # A repository that is all service: everything in it may be answered from.
    Scenario() \
        .given(nothing_was_scoped := "") \
        .when(lambda: in_scope(nothing_was_scoped)) \
        .then(the_answer_was([]))


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


def _stored(store: QdrantIndex, points: list[Point]) -> list[Point]:
    """Writes the points, and hands them back so a `given` can name them."""
    store_points(store, points, width=SOME_WIDTH)

    return points


def _stored_then_held(store: QdrantIndex,
                      points: list[Point],
                      path: str) -> set[str]:
    """Writes, then reads back - the round trip as one subject to assert on."""
    _stored(store, points)

    return ids_held_for(store, path)


def _forgotten_then_held(store: QdrantIndex,
                         ids: list[str],
                         path: str) -> set[str]:
    forget(store, ids)

    return ids_held_for(store, path)


def _the_only_chunk_held_for(store: QdrantIndex, path: str) -> Chunk:
    [chunk] = chunks_held_for(store, path)

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


def _the_payload_field_indexed_is(field: str) -> Assertion[CollectionInfo]:
    """The store's own account of which field it can filter on cheaply.

    Written here, in `incident_memory`'s suite and in the store adapter's, on
    purpose. The obvious home for it is `argus_testkit` - and putting it there
    would give the shared test package a `qdrant-client` dependency, which
    every module's dev environment installs: the vendor's client in every
    suite, for the sake of a helper. Three short assertions are the cheaper of
    the two prices.
    """
    def assertion(described: CollectionInfo) -> bool:
        indexed = dict(described.payload_schema or {})

        if field not in indexed:
            raise AssertionError(
                f"Expected [{field}] to carry a payload index, and the collection "
                f"indexes {sorted(indexed)} - so every filter on it is answered by "
                f"scanning."
            )

        if indexed[field].data_type != PayloadSchemaType.KEYWORD:
            raise AssertionError(
                f"Expected [{field}] indexed as a keyword, and it is indexed as "
                f"[{indexed[field].data_type}] - a filter matching an exact value "
                f"has nothing to traverse."
            )

        return True

    return assertion


def _the_payload_field_serves_a_prefix(field: str) -> Assertion[CollectionInfo]:
    """The store's own account of whether a prefix asked of the field is
    traversed rather than scanned for."""
    def assertion(described: CollectionInfo) -> bool:
        indexed = dict(described.payload_schema or {}).get(field)
        params = indexed.params if indexed is not None else None

        if not (isinstance(params, KeywordIndexParams) and params.prefix):
            raise AssertionError(
                f"Expected [{field}] indexed to serve a prefix, and its index is "
                f"described as [{indexed}] - so every search scoped by it is "
                f"answered by scanning."
            )

        return True

    return assertion
