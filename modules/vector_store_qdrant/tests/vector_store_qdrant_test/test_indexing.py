"""The writing side, against a real Qdrant and against a client that only records.

The questions a corpus builder asks - make it ready, put these, forget those,
what do you hold under this field - against the store that answers them. A
stand-in answers each the way whoever wrote it expected, and the one that most
needs a real store is the index on a field: a local client accepts the call,
warns that it does nothing, and reports no schema.

What a real store cannot show is an index rebuilt to the same shape: it reads
the same before and after. `ensure` runs on every write, so a field indexed
again on every call is asked of a client that records what it was told to do.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import Mock, create_autospec
from uuid import NAMESPACE_URL, uuid5

import pytest
from argus_testkit import Assertion, Scenario, all_of, calling
from core.vector_store import Equals, Held, StoredVector
from qdrant_client import QdrantClient
from qdrant_client.models import (
    CollectionInfo,
    KeywordIndexParams,
    KeywordIndexType,
    PayloadIndexInfo,
    PayloadSchemaType,
)
from vector_store_qdrant.indexing import QdrantIndex

# The collection conftest's `store` fills, mirrored for the cases that ask the
# vendor what it made of it.
THE_STORES_COLLECTION = "vector_store_qdrant_test"
DONT_CARE_COLLECTION = "dont-care-collection"

SOME_WIDTH = 4
SOME_VECTOR = [0.1, 0.2, 0.3, 0.4]

SOME_FIELD = "path"
SOME_PATH = "src/shop/summary.py"
ANOTHER_PATH = "src/shop/accounts.py"

# What each point says, under the field a reader would read it from.
TEXT_FIELD = "text"
SOME_TEXT = "def summary() -> None: ..."
ANOTHER_TEXT = "def accounts() -> None: ..."
A_THIRD_TEXT = "def total() -> None: ..."
SOME_TEXT_REWORDED = "def summary() -> str: ..."

# How the store describes a field indexed for exact matches, and one indexed to
# serve a prefix too.
INDEXED_FOR_EXACT_MATCHES = PayloadIndexInfo(data_type=PayloadSchemaType.KEYWORD, points=0)
INDEXED_FOR_PREFIXES = PayloadIndexInfo(
    data_type=PayloadSchemaType.KEYWORD,
    params=KeywordIndexParams(type=KeywordIndexType.KEYWORD, prefix=True),
    points=0
)


@pytest.mark.integration
def test_the_field_every_search_narrows_by_is_indexed_as_a_keyword(
    store: QdrantIndex, client: QdrantClient
) -> None:
    # Narrowing during the search rather than after it is why a store like this
    # was chosen, and without the index the narrowing is a scan - correct, and
    # slower with every point, which surfaces as a search that used to be quick.
    Scenario() \
        .given(calling(lambda: store.ensure(width=SOME_WIDTH, indexed_field=SOME_FIELD))) \
        .when(lambda: client.get_collection(THE_STORES_COLLECTION)) \
        .then(_the_payload_field_indexed_is(SOME_FIELD))


@pytest.mark.integration
def test_a_field_matched_by_prefix_is_indexed_as_a_keyword_too(
    store: QdrantIndex, client: QdrantClient
) -> None:
    # The repository index's path, which a reader scopes by prefix. Still a
    # keyword, so an exact match on one file is as cheap as it was.
    Scenario() \
        .given(calling(lambda: store.ensure(width=SOME_WIDTH, indexed_field=SOME_FIELD,
                                            matched_by_prefix=True))) \
        .when(lambda: client.get_collection(THE_STORES_COLLECTION)) \
        .then(all_of(
            _the_payload_field_indexed_is(SOME_FIELD),
            _the_payload_field_serves_a_prefix(SOME_FIELD)
        ))


@pytest.mark.integration
def test_a_field_indexed_before_it_was_matched_by_prefix_is_indexed_again_keeping_its_points(
    store: QdrantIndex, client: QdrantClient
) -> None:
    # Every repository index made before its path was scoped by prefix. Asked a
    # prefix, a plain keyword index still answers - by scanning - so nothing
    # would ever say the collection wanted rebuilding. Indexed again rather
    # than dropped, so a deployment does not begin with an empty corpus.
    some_point = _a_point(SOME_PATH, SOME_TEXT)

    Scenario() \
        .given(_kept(store, some_point)) \
        .when(lambda: _ensured_for_prefixes_then_held(store)) \
        .then(all_of(
            _exactly_these_ids({some_point.id}),
            _as_the_store_now_describes_it(client, _the_payload_field_serves_a_prefix(SOME_FIELD))
        ))


@pytest.mark.integration
def test_one_id_kept_twice_is_one_point(store: QdrantIndex) -> None:
    # What makes a re-index and a redelivery safe to repeat: the second write
    # replaces the first rather than standing beside it.
    some_point = _a_point(SOME_PATH, SOME_TEXT)
    the_same_point_again = _a_point(SOME_PATH, SOME_TEXT, said=SOME_TEXT_REWORDED)

    Scenario() \
        .given(_kept(store, some_point), _kept(store, the_same_point_again)) \
        .when(lambda: store.held([Equals(field=SOME_FIELD, value=SOME_PATH)], with_payload=True)) \
        .then(all_of(
            _exactly_these_ids({some_point.id}),
            _the_point_says(SOME_TEXT_REWORDED)
        ))


@pytest.mark.integration
def test_what_is_held_under_one_value_leaves_out_another(store: QdrantIndex) -> None:
    # A re-index asks what it holds for the file it is re-indexing, and an
    # answer that swept in the neighbours would have it forget their points.
    some_point = _a_point(SOME_PATH, SOME_TEXT)

    Scenario() \
        .given(_kept(store, some_point, _a_point(ANOTHER_PATH, ANOTHER_TEXT))) \
        .when(lambda: store.held([Equals(field=SOME_FIELD, value=SOME_PATH)], with_payload=False)) \
        .then(_exactly_these_ids({some_point.id}))


@pytest.mark.integration
def test_a_point_forgotten_is_no_longer_held(store: QdrantIndex) -> None:
    forgotten = _a_point(SOME_PATH, SOME_TEXT)
    still_there = _a_point(SOME_PATH, A_THIRD_TEXT)

    Scenario() \
        .given(_kept(store, forgotten, still_there)) \
        .when(lambda: _forgotten_then_held(store, forgotten)) \
        .then(_exactly_these_ids({still_there.id}))


@pytest.mark.integration
def test_a_store_nobody_has_written_to_holds_nothing(store: QdrantIndex) -> None:
    # The first deployment, and answered rather than raised: everything is new.
    Scenario() \
        .when(lambda: store.held([Equals(field=SOME_FIELD, value=SOME_PATH)], with_payload=False)) \
        .then(_exactly_these_ids(set()))


@pytest.mark.unit
def test_a_field_already_indexed_for_prefixes_is_left_alone() -> None:
    # `ensure` runs before every write. An index dropped and built again each
    # time would leave every search between the two scanning, over and over.
    Scenario() \
        .given(a_client := _a_client_onto_a_collection_indexing(INDEXED_FOR_PREFIXES)) \
        .when(lambda: QdrantIndex(a_client, DONT_CARE_COLLECTION).ensure(
            width=SOME_WIDTH, indexed_field=SOME_FIELD, matched_by_prefix=True
        )) \
        .then(_the_index_was_left_alone(a_client))


@pytest.mark.unit
def test_a_field_matched_exactly_keeps_the_index_it_has() -> None:
    # Long-term memory's service, asked only for an exact value: the keyword
    # index it was made with already answers that, so nothing is rebuilt.
    Scenario() \
        .given(a_client := _a_client_onto_a_collection_indexing(INDEXED_FOR_EXACT_MATCHES)) \
        .when(lambda: QdrantIndex(a_client, DONT_CARE_COLLECTION).ensure(
            width=SOME_WIDTH, indexed_field=SOME_FIELD
        )) \
        .then(_the_index_was_left_alone(a_client))


def _a_point(path: str, text: str, said: str | None = None) -> StoredVector:
    """A point whose id is derived from what it is, as both corpora derive theirs."""
    return StoredVector(id=str(uuid5(NAMESPACE_URL, f"{path}:{text}")),
                        vector=SOME_VECTOR,
                        payload={SOME_FIELD: path, TEXT_FIELD: said or text})


def _kept(store: QdrantIndex, *points: StoredVector) -> list[StoredVector]:
    store.ensure(width=SOME_WIDTH, indexed_field=SOME_FIELD)
    store.upsert(list(points))

    return list(points)


def _a_client_onto_a_collection_indexing(indexed: PayloadIndexInfo) -> Any:
    """A client onto a collection that exists, whose field is indexed as given."""
    client = create_autospec(QdrantClient, instance=True)
    client.collection_exists.return_value = True
    client.get_collection.return_value = Mock(payload_schema={SOME_FIELD: indexed})

    return client


def _ensured_for_prefixes_then_held(store: QdrantIndex) -> list[Held]:
    store.ensure(width=SOME_WIDTH, indexed_field=SOME_FIELD, matched_by_prefix=True)

    return store.held([Equals(field=SOME_FIELD, value=SOME_PATH)], with_payload=False)


def _forgotten_then_held(store: QdrantIndex, point: StoredVector) -> list[Held]:
    store.delete([point.id])

    return store.held([Equals(field=SOME_FIELD, value=SOME_PATH)], with_payload=False)


def _exactly_these_ids(expected: set[str]) -> Assertion[list[Held]]:
    def assertion(held: list[Held]) -> bool:
        ids = {one.id for one in held}

        if ids != expected:
            raise AssertionError(
                f"Expected exactly {sorted(expected)} held, and {sorted(ids)} were."
            )

        return True

    return assertion


def _the_point_says(text: str) -> Assertion[list[Held]]:
    def assertion(held: list[Held]) -> bool:
        said = [one.payload.get(TEXT_FIELD) for one in held]

        if said != [text]:
            raise AssertionError(
                f"Expected the one point held to say [{text}], and they said {said}."
            )

        return True

    return assertion


def _the_index_was_left_alone(client: Any) -> Assertion[object]:
    def assertion(dont_care_result: object) -> bool:
        dropped = client.delete_payload_index.call_count
        made = client.create_payload_index.call_count

        if dropped or made:
            raise AssertionError(
                f"Expected the field's index left as it was, and it was dropped "
                f"[{dropped}] time(s) and made [{made}] time(s)."
            )

        return True

    return assertion


def _as_the_store_now_describes_it(client: QdrantClient,
                                   described: Assertion[CollectionInfo]) -> Assertion[object]:
    """`described`, asked of the collection as the store describes it after the
    case ran rather than of what the case returned."""
    def assertion(dont_care_result: object) -> bool:
        return described(client.get_collection(THE_STORES_COLLECTION))

    return assertion


def _the_payload_field_indexed_is(field: str) -> Assertion[CollectionInfo]:
    """The store's own account of which field it can narrow on cheaply."""
    def assertion(described: CollectionInfo) -> bool:
        indexed = dict(described.payload_schema or {})

        if field not in indexed:
            raise AssertionError(
                f"Expected [{field}] to carry a payload index, and the collection "
                f"indexes {sorted(indexed)} - so every search narrowing by it is "
                f"answered by scanning."
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
