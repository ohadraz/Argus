"""The reading side, against a real Qdrant and against clients that fail on cue.

The search itself - the conditions, the floor, the ranking - is asked of a real
store, because those are what a stand-in answers the way whoever wrote it
expected. The vectors are made up rather than embedded, and that is the point: a
real embedder would make each case depend on how a sentence happens to land.
Four dimensions, so "near" and "far" are arranged rather than hoped for. The
cases that matter most are the ones a filter applied afterwards would fail: room
for one, and the nearest point outside the condition.

What no real store can be made to do on demand - fail for itself, refuse the
question, give no answer at all, or be reached the moment a client is built - is
asked of a client
that does it on cue.
"""

from __future__ import annotations

import contextlib
from typing import Any
from unittest.mock import Mock, create_autospec
from uuid import NAMESPACE_URL, uuid5

import pytest
from argus_testkit import Assertion, Scenario, an_error_was_raised, attempting
from core.vector_store import (
    Equals,
    Hit,
    StartsWithAnyOf,
    StoredVector,
    VectorQueryRefused,
    VectorStoreUnavailable,
    VectorStoreUnreachable,
)
from httpx import Headers
from qdrant_client import QdrantClient
from qdrant_client.http.exceptions import ResponseHandlingException, UnexpectedResponse
from vector_store_qdrant.indexing import QdrantIndex
from vector_store_qdrant.searching import QdrantSearch, SearchOpenedOnFirstUse

# The collection conftest's `store` fills, mirrored for the one case that
# searches it through the reading side alone.
THE_STORES_COLLECTION = "vector_store_qdrant_test"

DONT_CARE_URL = "http://qdrant.invalid"
DONT_CARE_COLLECTION = "dont-care-collection"
DONT_CARE_VECTOR = [1.0, 0.0, 0.0, 0.0]
DONT_CARE_LIMIT = 5
DONT_CARE_NO_ROUTE = "no route to the store"

# What the store answered a search with when it failed for itself: a server
# error, which says nothing about the question asked.
THE_STORE_FAILED = 500
# And a refusal of the question itself, which asking again cannot change.
THE_QUESTION_WAS_REFUSED = 400

# What each point says it is, so what came back can be said by name.
NAME_FIELD = "name"

SOME_WIDTH = 4

WHAT_IS_SEARCHED_FOR = [1.0, 0.0, 0.0, 0.0]
ALMOST_WHAT_IS_SEARCHED_FOR = [0.9, 0.1, 0.0, 0.0]
SOMEWHAT_LIKE_IT = [0.6, 0.8, 0.0, 0.0]
NOTHING_LIKE_IT = [0.0, 0.0, 0.0, 1.0]

SOME_FIELD = "service"
SOME_VALUE = "io-shop"
ANOTHER_VALUE = "io-warehouse"

SOME_PREFIX = "src/io_shop"
ANOTHER_PREFIX = "tests/io_shop"
SOMEWHERE_ELSE = "src/elsewhere/scenarios.py"
SOME_FILE = f"{SOME_PREFIX}/spend_summary.py"
ANOTHER_FILE = f"{ANOTHER_PREFIX}/test_spend_summary.py"

# Points this suite stages and never asserts on by name.
A_POINT_OF_ANOTHER_SERVICE = "theirs"
A_POINT_OUTSIDE_THE_SCOPE = "outside"
A_FAR_POINT = "far"
A_POINT_CARRYING_A_PAYLOAD = "carrying"
LINES_FIELD = "lines"
SOME_LINES = [12, 19]

ENOUGH_ROOM_FOR_THEM_ALL = 10
ROOM_FOR_ONE = 1


@pytest.mark.integration
def test_a_point_meeting_the_condition_is_not_crowded_out_by_a_nearer_one_that_does_not(
    store: QdrantIndex
) -> None:
    # The defect a port exists to close. Asked for one, a store that narrowed
    # afterwards would rank the nearer point of another service first, drop it,
    # and answer nothing - while this service's point sat second.
    the_one_here = "ours"

    Scenario() \
        .given(_kept(
            store,
            _a_point(A_POINT_OF_ANOTHER_SERVICE, ALMOST_WHAT_IS_SEARCHED_FOR,
                     {SOME_FIELD: ANOTHER_VALUE}),
            _a_point(the_one_here, SOMEWHAT_LIKE_IT, {SOME_FIELD: SOME_VALUE})
        )) \
        .when(lambda: store.nearest(WHAT_IS_SEARCHED_FOR, limit=ROOM_FOR_ONE,
                                    where=[Equals(field=SOME_FIELD, value=SOME_VALUE)])) \
        .then(_these_came_back([the_one_here]))


@pytest.mark.integration
def test_a_point_under_one_of_the_prefixes_is_not_crowded_out_by_a_nearer_one_outside_them(
    store: QdrantIndex
) -> None:
    # The same defect, as a repository index meets it: the indexer and the
    # reader are configured separately, and an index built wider than the
    # reader holds passages outside its scope that may be the nearest.
    the_services_own = "ours"

    Scenario() \
        .given(_kept(
            store,
            _a_point(A_POINT_OUTSIDE_THE_SCOPE, ALMOST_WHAT_IS_SEARCHED_FOR,
                     {SOME_FIELD: SOMEWHERE_ELSE}),
            _a_point(the_services_own, SOMEWHAT_LIKE_IT, {SOME_FIELD: SOME_FILE})
        )) \
        .when(lambda: store.nearest(
            WHAT_IS_SEARCHED_FOR, limit=ROOM_FOR_ONE,
            where=[StartsWithAnyOf(field=SOME_FIELD, prefixes=(SOME_PREFIX,))]
        )) \
        .then(_these_came_back([the_services_own]))


@pytest.mark.integration
def test_a_point_under_any_one_of_several_prefixes_meets_them(store: QdrantIndex) -> None:
    # A service and the tests that cover it are both the service, and they do
    # not live in one directory.
    the_source = "the-source"
    the_test = "the-test"

    Scenario() \
        .given(_kept(
            store,
            _a_point(the_source, ALMOST_WHAT_IS_SEARCHED_FOR, {SOME_FIELD: SOME_FILE}),
            _a_point(the_test, SOMEWHAT_LIKE_IT, {SOME_FIELD: ANOTHER_FILE}),
            _a_point(A_POINT_OUTSIDE_THE_SCOPE, WHAT_IS_SEARCHED_FOR,
                     {SOME_FIELD: SOMEWHERE_ELSE})
        )) \
        .when(lambda: store.nearest(
            WHAT_IS_SEARCHED_FOR, limit=ENOUGH_ROOM_FOR_THEM_ALL,
            where=[StartsWithAnyOf(field=SOME_FIELD, prefixes=(SOME_PREFIX, ANOTHER_PREFIX))]
        )) \
        .then(_these_came_back([the_source, the_test]))


@pytest.mark.integration
def test_a_prefix_asked_of_a_field_not_indexed_for_one_is_still_answered(
    store: QdrantIndex
) -> None:
    # A repository index whose path was indexed before it was scoped by prefix,
    # searched before its writer next indexes it again: slower, never refused.
    the_services_own = "ours"

    Scenario() \
        .given(_kept_under_an_exact_index(
            store,
            _a_point(A_POINT_OUTSIDE_THE_SCOPE, ALMOST_WHAT_IS_SEARCHED_FOR,
                     {SOME_FIELD: SOMEWHERE_ELSE}),
            _a_point(the_services_own, SOMEWHAT_LIKE_IT, {SOME_FIELD: SOME_FILE})
        )) \
        .when(lambda: store.nearest(
            WHAT_IS_SEARCHED_FOR, limit=ROOM_FOR_ONE,
            where=[StartsWithAnyOf(field=SOME_FIELD, prefixes=(SOME_PREFIX,))]
        )) \
        .then(_these_came_back([the_services_own]))


@pytest.mark.integration
def test_a_point_further_off_than_the_floor_is_not_offered(store: QdrantIndex) -> None:
    # A nearest-neighbour search always answers, however far away its nearest
    # is. What is not near enough must not reach a caller at all.
    the_near_one = "near"
    a_floor_only_the_near_one_clears = 0.5

    Scenario() \
        .given(_kept(
            store,
            _a_point(the_near_one, ALMOST_WHAT_IS_SEARCHED_FOR),
            _a_point(A_FAR_POINT, NOTHING_LIKE_IT)
        )) \
        .when(lambda: store.nearest(WHAT_IS_SEARCHED_FOR, limit=ENOUGH_ROOM_FOR_THEM_ALL,
                                    floor=a_floor_only_the_near_one_clears)) \
        .then(_these_came_back([the_near_one]))


@pytest.mark.integration
def test_the_nearest_comes_back_first(store: QdrantIndex) -> None:
    the_nearest = "nearest"
    the_next = "next"

    Scenario() \
        .given(_kept(
            store,
            _a_point(the_next, SOMEWHAT_LIKE_IT),
            _a_point(the_nearest, ALMOST_WHAT_IS_SEARCHED_FOR)
        )) \
        .when(lambda: store.nearest(WHAT_IS_SEARCHED_FOR, limit=ENOUGH_ROOM_FOR_THEM_ALL)) \
        .then(_these_came_back([the_nearest, the_next]))


@pytest.mark.integration
def test_what_a_point_carried_comes_back_with_it(store: QdrantIndex) -> None:
    some_payload: dict[str, object] = {SOME_FIELD: SOME_VALUE, LINES_FIELD: SOME_LINES}

    Scenario() \
        .given(_kept(
            store,
            _a_point(A_POINT_CARRYING_A_PAYLOAD, ALMOST_WHAT_IS_SEARCHED_FOR, some_payload)
        )) \
        .when(lambda: store.nearest(WHAT_IS_SEARCHED_FOR, limit=ROOM_FOR_ONE)) \
        .then(_the_payload_came_back(some_payload))


@pytest.mark.integration
def test_a_store_nobody_has_written_to_finds_nothing(store: QdrantIndex) -> None:
    # The ordinary state of a first deployment, and answered rather than raised.
    Scenario() \
        .when(lambda: store.nearest(WHAT_IS_SEARCHED_FOR, limit=ENOUGH_ROOM_FOR_THEM_ALL)) \
        .then(_these_came_back([]))


@pytest.mark.integration
def test_the_reading_side_finds_what_the_writing_side_kept(store: QdrantIndex,
                                                           client: QdrantClient) -> None:
    # The walk searches through the reading side alone. A reading side that
    # spoke to the collection differently from the writing side would be a
    # memory nothing could recall from.
    the_one_kept = "kept"

    Scenario() \
        .given(_kept(store, _a_point(the_one_kept, ALMOST_WHAT_IS_SEARCHED_FOR))) \
        .when(lambda: QdrantSearch(client, THE_STORES_COLLECTION).nearest(
            WHAT_IS_SEARCHED_FOR, limit=ENOUGH_ROOM_FOR_THEM_ALL
        )) \
        .then(_these_came_back([the_one_kept]))


@pytest.mark.unit
def test_a_search_the_store_failed_for_itself_is_said_as_the_store_unavailable() -> None:
    # What a caller retries on, said in the port's words: recall asks again
    # after this and only this, and a caller that had to read a vendor's status
    # code to know would be a caller that knows the vendor.
    Scenario() \
        .given(a_store := QdrantSearch(_a_client_failing_with(THE_STORE_FAILED),
                                       DONT_CARE_COLLECTION)) \
        .when(attempting(lambda: a_store.nearest(DONT_CARE_VECTOR, limit=DONT_CARE_LIMIT))) \
        .then(an_error_was_raised(VectorStoreUnavailable))


@pytest.mark.unit
def test_a_question_the_store_refused_is_said_as_refused() -> None:
    # The same question gets the same answer, so nobody should ask it again.
    Scenario() \
        .given(a_store := QdrantSearch(_a_client_failing_with(THE_QUESTION_WAS_REFUSED),
                                       DONT_CARE_COLLECTION)) \
        .when(attempting(lambda: a_store.nearest(DONT_CARE_VECTOR, limit=DONT_CARE_LIMIT))) \
        .then(an_error_was_raised(VectorQueryRefused))


@pytest.mark.unit
def test_a_store_that_gave_no_answer_is_said_as_unreachable() -> None:
    # The client wraps a connection it could not make in an exception of its
    # own. Let through, a caller would have to know the vendor to know what
    # happened; said as the store failing for itself, recall would ask again a
    # store that is not there.
    Scenario() \
        .given(a_store := QdrantSearch(_a_client_that_reaches_nothing(), DONT_CARE_COLLECTION)) \
        .when(attempting(lambda: a_store.nearest(DONT_CARE_VECTOR, limit=DONT_CARE_LIMIT))) \
        .then(an_error_was_raised(VectorStoreUnreachable))


@pytest.mark.unit
def test_a_store_nobody_has_searched_has_reached_for_no_client() -> None:
    # A client reaches out as it is built - its version check runs on a thread
    # of its own and swallows every failure into a warning - so a server built
    # and never asked to search by meaning, a test's or a deployment's, reaches
    # nothing, as the embedder beside it loads nothing until it is asked.
    client_for = _a_client_onto_an_empty_store()

    Scenario() \
        .when(lambda: SearchOpenedOnFirstUse(DONT_CARE_URL, DONT_CARE_COLLECTION,
                                             client_for=client_for)) \
        .then(_clients_reached_for(client_for, 0))


@pytest.mark.unit
def test_a_store_searched_twice_reaches_for_one_client() -> None:
    # One client for the life of the process: a connection per question is one
    # a model waits through on every search.
    client_for = _a_client_onto_an_empty_store()
    a_store = SearchOpenedOnFirstUse(DONT_CARE_URL, DONT_CARE_COLLECTION, client_for=client_for)

    Scenario() \
        .when(lambda: [a_store.nearest(DONT_CARE_VECTOR, limit=DONT_CARE_LIMIT),
                       a_store.nearest(DONT_CARE_VECTOR, limit=DONT_CARE_LIMIT)]) \
        .then(_clients_reached_for(client_for, 1))


@pytest.mark.unit
def test_a_client_that_could_not_be_built_is_built_again_by_the_next_search() -> None:
    # A store down when the first search came is not down for the life of the
    # process: what failed to be built is not kept, so the next search tries.
    client_for = _a_client_onto_an_empty_store()
    client_for.side_effect = [ConnectionError("no route to qdrant"), client_for.return_value]
    a_store = SearchOpenedOnFirstUse(DONT_CARE_URL, DONT_CARE_COLLECTION, client_for=client_for)

    Scenario() \
        .when(lambda: _searched_again_after_a_failure(a_store)) \
        .then(_clients_reached_for(client_for, 2))


def _a_point(name: str,
             vector: list[float],
             payload: dict[str, object] | None = None) -> StoredVector:
    """A point named by its own id, so what came back can be said by name."""
    return StoredVector(id=str(uuid5(NAMESPACE_URL, name)), vector=vector,
                        payload={NAME_FIELD: name, **(payload or {})})


def _kept(store: QdrantIndex, *points: StoredVector) -> list[StoredVector]:
    store.ensure(width=SOME_WIDTH, indexed_field=SOME_FIELD, matched_by_prefix=True)
    store.upsert(list(points))

    return list(points)


def _kept_under_an_exact_index(store: QdrantIndex, *points: StoredVector) -> list[StoredVector]:
    """Kept in a collection whose field is indexed for exact matches alone - as
    a repository index's path was before a reader scoped it by prefix."""
    store.ensure(width=SOME_WIDTH, indexed_field=SOME_FIELD)
    store.upsert(list(points))

    return list(points)


def _a_client_failing_with(status: int) -> Any:
    client = create_autospec(QdrantClient, instance=True)
    client.collection_exists.return_value = True
    client.query_points.side_effect = UnexpectedResponse(status_code=status, reason_phrase="",
                                                         content=b"", headers=Headers())
    return client


def _a_client_that_reaches_nothing() -> Any:
    client = create_autospec(QdrantClient, instance=True)
    client.collection_exists.side_effect = ResponseHandlingException(
        ConnectionError(DONT_CARE_NO_ROUTE)
    )
    return client


def _a_client_onto_an_empty_store() -> Mock:
    """What builds a client, building one whose store holds no collection - so a
    search through it answers nothing, and reaches nowhere."""
    client = create_autospec(QdrantClient, instance=True)
    client.collection_exists.return_value = False

    return Mock(return_value=client)


def _searched_again_after_a_failure(a_store: SearchOpenedOnFirstUse) -> list[Hit]:
    with contextlib.suppress(ConnectionError):
        a_store.nearest(DONT_CARE_VECTOR, limit=DONT_CARE_LIMIT)

    return a_store.nearest(DONT_CARE_VECTOR, limit=DONT_CARE_LIMIT)


def _these_came_back(expected: list[str]) -> Assertion[list[Hit]]:
    def assertion(hits: list[Hit]) -> bool:
        names = [hit.payload[NAME_FIELD] for hit in hits]

        if names != expected:
            raise AssertionError(f"Expected {expected} back, nearest first, and {names} came back.")

        return True

    return assertion


def _the_payload_came_back(expected: dict[str, object]) -> Assertion[list[Hit]]:
    def assertion(hits: list[Hit]) -> bool:
        carried = {field: value for field, value in hits[0].payload.items() if field != NAME_FIELD}

        if carried != expected:
            raise AssertionError(
                f"Expected the point to carry {expected}, and it carried {carried}."
            )

        return True

    return assertion


def _clients_reached_for(client_for: Mock, times: int) -> Assertion[Any]:
    def assertion(dont_care_result: Any) -> bool:
        if client_for.call_count != times:
            raise AssertionError(
                f"Expected a client reached for {times} time(s), and one was reached for "
                f"{client_for.call_count}."
            )

        return True

    return assertion
