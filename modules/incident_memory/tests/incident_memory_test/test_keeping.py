"""Keeping a record in the store, which is where the pairing can break.

The store takes vectors and the walk has text, so something has to embed one
into the other - twice, once at each end. These cases are about that: whether
what is kept is the description's own vector, and whether the question is put
through the same model the records went through. And about what keeping does to
the store itself: one record per incident however often it is kept, in a
collection that can narrow by service without a scan.

The embedder is a stand-in with an arrangement of its own, so "the same model
both times" is something a test can actually observe. Two vectors from two
models are two coordinate systems, and the distance between them is a number
that means nothing - which is exactly the failure that looks like an empty
corpus rather than like a bug.
"""

from __future__ import annotations

import pytest
from argus_testkit import Assertion, Scenario, all_of, calling
from core.embedding import Embedder
from core.models import REVERT_FEATURE_FLAG, ActionIdentity, Verdict, WhatWasTried
from core.stored import REMEMBERED_INCIDENT, SHIPPED
from core.vector_store import Equals, Held, VectorIndex, VectorSearch
from incident_memory.keeping import kept_in
from incident_memory.recalling import SERVICE_FIELD, SHAPE_FIELD, Recaller, recalling_from
from incident_memory.records import RememberedIncident
from qdrant_client import QdrantClient
from qdrant_client.models import CollectionInfo, PayloadSchemaType
from vector_store_qdrant.indexing import QdrantIndex

from incident_memory_test.framework.assertions import these_incidents_come_back

# The collection conftest's `store` keeps records in, mirrored for the one case
# that asks the vendor what it made of it.
THE_STORES_COLLECTION = "incidents"
SOME_SERVICE = "io-shop"
DONT_CARE_INCIDENT = "the-flag-one"
DONT_CARE_ALERT = "HighErrorRate"
ENOUGH_ROOM_FOR_THEM_ALL = 10
NO_FLOOR_WORTH_MENTIONING = 0.0
# What each text embeds to, under the stand-in below. Two descriptions that
# should match sit near each other; the third sits well away from both.
WHAT_HAPPENED_HERE = "checkout began failing after a flag was switched on"
WHAT_HAPPENED_BEFORE = "checkout failures followed a feature flag change"
SOMETHING_ELSE_ENTIRELY = "the warehouse label printer ran out of paper"
_VECTORS = {
    WHAT_HAPPENED_HERE: [1.0, 0.0, 0.0, 0.0],
    WHAT_HAPPENED_BEFORE: [0.9, 0.1, 0.0, 0.0],
    SOMETHING_ELSE_ENTIRELY: [0.0, 0.0, 0.0, 1.0]
}


@pytest.mark.integration
def test_a_record_is_found_by_a_description_that_means_the_same_thing(
    store: QdrantIndex
) -> None:
    # The whole arrangement in one case: a record kept under one description is
    # reached by a different description that embeds near it. Neither end names
    # a vector, which is what the binding is for.
    the_incident_that_happened_before = "the-flag-one"

    Scenario() \
        .given(calling(lambda: kept_in(store, _an_embedder())(
            _an_incident(the_incident_that_happened_before, WHAT_HAPPENED_BEFORE)
        ))) \
        .when(lambda: _recalling(store)(WHAT_HAPPENED_HERE, SOME_SERVICE)) \
        .then(these_incidents_come_back([the_incident_that_happened_before]))


@pytest.mark.integration
def test_a_record_about_something_else_is_not_reached(store: QdrantIndex) -> None:
    # The other half of the same claim. A search that returned this one would
    # mean the description was never what the record was stored under - which a
    # test asserting only the match above would not notice.
    the_one_about_something_else = "the-printer-one"
    a_floor_it_does_not_clear = 0.5

    Scenario() \
        .given(calling(lambda: kept_in(store, _an_embedder())(
            _an_incident(the_one_about_something_else, SOMETHING_ELSE_ENTIRELY)
        ))) \
        .when(lambda: _recalling(store, floor=a_floor_it_does_not_clear)(
            WHAT_HAPPENED_HERE, SOME_SERVICE
        )) \
        .then(these_incidents_come_back([]))


@pytest.mark.integration
def test_the_whole_record_comes_back_not_just_what_it_was_found_by(store: QdrantIndex) -> None:
    # The record goes through an embedder and a store and comes back whole. It
    # is the list of attempts that a later ordering reads, and a binding that
    # kept only what it searched by would be a memory of nothing.
    the_flag_that_did_not_help = "new-checkout-flow"

    Scenario() \
        .given(calling(lambda: kept_in(store, _an_embedder())(
            _an_incident(DONT_CARE_INCIDENT,
                         WHAT_HAPPENED_BEFORE,
                         tried=[(the_flag_that_did_not_help, Verdict.REFUTED)])
        ))) \
        .when(lambda: _recalling(store)(WHAT_HAPPENED_HERE, SOME_SERVICE)) \
        .then(all_of(
            _it_remembers_trying(the_flag_that_did_not_help),
            _it_remembers_the_verdict(Verdict.REFUTED)
        ))


@pytest.mark.integration
def test_one_incident_kept_twice_is_one_record(store: QdrantIndex) -> None:
    # A record refiled is delivered again. Two copies of one incident would
    # count twice in an ordering, which is a past incident given a second vote
    # for having been interrupted.
    the_same_incident = "the-flag-one"

    Scenario() \
        .given(
            calling(lambda: kept_in(store, _an_embedder())(
                _an_incident(the_same_incident, WHAT_HAPPENED_BEFORE)
            )),
            calling(lambda: kept_in(store, _an_embedder())(
                _an_incident(the_same_incident, WHAT_HAPPENED_HERE)
            ))
        ) \
        .when(lambda: _recalling(store)(WHAT_HAPPENED_HERE, SOME_SERVICE)) \
        .then(these_incidents_come_back([the_same_incident]))


@pytest.mark.integration
def test_a_record_is_kept_in_the_shape_this_release_writes(store: QdrantIndex) -> None:
    # What a later release reads it as: kept without one, it would be read as
    # the first shape whatever shape it is in.
    Scenario() \
        .given(
            calling(lambda: kept_in(store, _an_embedder())(
                _an_incident(DONT_CARE_INCIDENT, WHAT_HAPPENED_HERE)
            ))
        ) \
        .when(lambda: _every_point_of(store)) \
        .then(_each_was_kept_in_shape(SHIPPED.current(REMEMBERED_INCIDENT)))


@pytest.mark.integration
def test_the_field_every_search_narrows_by_is_indexed(store: QdrantIndex,
                                                      client: QdrantClient) -> None:
    # Every search here narrows to one service before anything is compared, and
    # narrowing during the search rather than after it is why a store like this
    # was chosen. Without the payload index the answers are the same and the
    # work is a scan, which is invisible until there are enough incidents for
    # it not to be.
    #
    # Only a real store can answer this: the in-memory client accepts the call,
    # warns that payload indexes do nothing locally, and reports no schema. The
    # collection is made by the first record kept rather than declared anywhere,
    # so keeping one is what brings it into existence.
    Scenario() \
        .given(
            calling(lambda: kept_in(store, _an_embedder())(
                _an_incident("the-one-that-made-the-collection", WHAT_HAPPENED_BEFORE)
            ))
        ) \
        .when(lambda: client.get_collection(THE_STORES_COLLECTION)) \
        .then(_the_payload_field_indexed_is(SERVICE_FIELD))


def _every_point_of(store: VectorIndex) -> list[Held]:
    return store.held([Equals(field=SERVICE_FIELD, value=SOME_SERVICE)], with_payload=True)


def _each_was_kept_in_shape(expected: int) -> Assertion[list[Held]]:
    def assertion(points: list[Held]) -> bool:
        shapes = [point.payload.get(SHAPE_FIELD) for point in points]
        if not points or any(shape != expected for shape in shapes):
            raise AssertionError(
                f"Expected every point kept in shape [{expected}], got {shapes}."
            )

        return True

    return assertion


def _an_embedder() -> Embedder:
    """A model with an arrangement instead of weights.

    Every text it is given is one of the three above, so what a description
    embeds to is decided by this test rather than by how a sentence happens to
    land - which is what makes "near" and "far" facts here rather than hopes.
    """
    def embed(texts: list[str], /) -> list[list[float]]:
        return [_VECTORS[text] for text in texts]

    return embed


def _recalling(store: VectorSearch,
               floor: float = NO_FLOOR_WORTH_MENTIONING) -> Recaller:
    return recalling_from(
        store,
        _an_embedder(),
        limit=ENOUGH_ROOM_FOR_THEM_ALL,
        floor=floor
    )


def _an_incident(incident_id: str,
                 described_as: str,
                 tried: list[tuple[str, Verdict]] | None = None) -> RememberedIncident:
    return RememberedIncident(
        incident_id=incident_id,
        described_as=described_as,
        service=SOME_SERVICE,
        alert_name=DONT_CARE_ALERT,
        tried=[
            WhatWasTried(
                identity=ActionIdentity(
                    action_type=REVERT_FEATURE_FLAG, subject=subject
                ),
                verdict=verdict
            )
            for subject, verdict in (tried if tried is not None else [("a-flag", Verdict.REFUTED)])
        ]
    )


def _it_remembers_trying(subject: str) -> Assertion[list[RememberedIncident]]:
    def assertion(remembered: list[RememberedIncident]) -> bool:
        subjects = [
            attempt.identity.subject
            for incident in remembered for attempt in incident.tried
        ]

        if subject not in subjects:
            raise AssertionError(f"Expected [{subject}] among {subjects}")

        return True

    return assertion


def _it_remembers_the_verdict(verdict: Verdict) -> Assertion[list[RememberedIncident]]:
    def assertion(remembered: list[RememberedIncident]) -> bool:
        verdicts = [attempt.verdict for incident in remembered for attempt in incident.tried]

        if verdict not in verdicts:
            raise AssertionError(f"Expected [{verdict}] among {verdicts}")

        return True

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
