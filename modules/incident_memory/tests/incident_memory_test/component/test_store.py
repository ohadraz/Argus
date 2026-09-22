"""Records in and out of the store that holds them.

The vectors here are made up rather than embedded, and that is the point: what
these cases are about is the store's behaviour around a search - the narrowing,
the floor, the ordering, the round trip - and a real embedder would make every
one of them depend on how a sentence happens to land. Four dimensions, one of
them set per record, so "near" and "far" are arranged rather than hoped for.

What is not made up is the store. Whether a payload survives, whether a filter
selects only what it names, and whether the same incident written twice is one
record are exactly the questions a stand-in would answer the way its author
expected.
"""

from __future__ import annotations

import pytest
from argus_core.models import REVERT_FEATURE_FLAG, ActionIdentity, Verdict
from argus_testkit import Assertion, Scenario, all_of
from incident_memory.records import RememberedIncident, WhatWasTried
from incident_memory.store import SERVICE_FIELD, recalled, remember
from qdrant_client import QdrantClient
from qdrant_client.models import CollectionInfo, PayloadSchemaType

from incident_memory_test.framework.assertions import these_incidents_come_back

SOME_COLLECTION = "incidents"

# Four dimensions is enough to arrange three records at known distances from a
# search, and few enough that a reader can see the arrangement.
WHAT_IS_SEARCHED_FOR = [1.0, 0.0, 0.0, 0.0]
ALMOST_WHAT_IS_SEARCHED_FOR = [0.9, 0.1, 0.0, 0.0]
SOMEWHAT_LIKE_IT = [0.6, 0.8, 0.0, 0.0]
NOTHING_LIKE_IT = [0.0, 0.0, 0.0, 1.0]

# Wide enough to admit everything the cases below arrange, so that a case about
# ordering is not quietly also a case about the floor. The one case about the
# floor names its own.
NO_FLOOR_WORTH_MENTIONING = 0.0
ENOUGH_ROOM_FOR_THEM_ALL = 10

SOME_SERVICE = "io-shop"
DONT_CARE_DESCRIPTION = "checkout began failing after a flag was switched on"


@pytest.mark.component
def test_an_incident_written_is_found_again(store: QdrantClient) -> None:
    # The round trip, and the whole record rather than its identity: what a
    # recall is for is the list of what was tried, and an id the caller then has
    # to go and look up somewhere else would make memory a second database.
    the_incident_that_happened_before = "the-flag-one"
    the_flag_that_did_not_help = "new-checkout-flow"

    remember(
        store,
        SOME_COLLECTION,
        _an_incident(the_incident_that_happened_before,
                     tried=[(the_flag_that_did_not_help, Verdict.REFUTED)]),
        ALMOST_WHAT_IS_SEARCHED_FOR
    )

    Scenario() \
        .given(store) \
        .when(lambda: recalled(
            store,
            SOME_COLLECTION,
            WHAT_IS_SEARCHED_FOR,
            service=SOME_SERVICE,
            limit=ENOUGH_ROOM_FOR_THEM_ALL,
            floor=NO_FLOOR_WORTH_MENTIONING
        )) \
        .then(all_of(
            these_incidents_come_back([the_incident_that_happened_before]),
            _it_remembers_trying(the_flag_that_did_not_help, Verdict.REFUTED)
        ))


@pytest.mark.component
def test_a_store_that_has_never_been_written_to_finds_nothing(store: QdrantClient) -> None:
    # The ordinary state of a first deployment, and answered rather than raised:
    # before the first incident there is nothing to recall, which is a fact
    # about the corpus rather than a failure of the store.
    Scenario() \
        .given(store) \
        .when(lambda: recalled(
            store,
            SOME_COLLECTION,
            WHAT_IS_SEARCHED_FOR,
            service=SOME_SERVICE,
            limit=ENOUGH_ROOM_FOR_THEM_ALL,
            floor=NO_FLOOR_WORTH_MENTIONING
        )) \
        .then(these_incidents_come_back([]))


@pytest.mark.component
def test_an_incident_further_off_than_the_floor_is_not_offered(store: QdrantClient) -> None:
    # A nearest-neighbour search always answers. Without a floor, a corpus
    # holding one unrelated incident would hand it back as the nearest thing it
    # had, and an ordering would demote a candidate on the strength of it.
    the_one_that_is_like_it = "the-near-one"
    the_one_that_is_not = "the-far-one"
    a_floor_only_the_near_one_clears = 0.5

    remember(store, SOME_COLLECTION, _an_incident(the_one_that_is_like_it),
             ALMOST_WHAT_IS_SEARCHED_FOR)
    remember(store, SOME_COLLECTION, _an_incident(the_one_that_is_not),
             NOTHING_LIKE_IT)

    Scenario() \
        .given(store) \
        .when(lambda: recalled(
            store,
            SOME_COLLECTION,
            WHAT_IS_SEARCHED_FOR,
            service=SOME_SERVICE,
            limit=ENOUGH_ROOM_FOR_THEM_ALL,
            floor=a_floor_only_the_near_one_clears
        )) \
        .then(these_incidents_come_back([the_one_that_is_like_it]))


@pytest.mark.component
def test_the_most_like_it_comes_back_first(store: QdrantClient) -> None:
    # A caller that trusts the order and is handed an arbitrary one reads the
    # least relevant record first - and where only some of them fit, keeps the
    # wrong ones.
    the_one_most_like_it = "the-nearest-one"
    the_one_less_like_it = "the-next-nearest-one"

    remember(store, SOME_COLLECTION, _an_incident(the_one_less_like_it), SOMEWHAT_LIKE_IT)
    remember(store, SOME_COLLECTION, _an_incident(the_one_most_like_it),
             ALMOST_WHAT_IS_SEARCHED_FOR)

    Scenario() \
        .given(store) \
        .when(lambda: recalled(
            store,
            SOME_COLLECTION,
            WHAT_IS_SEARCHED_FOR,
            service=SOME_SERVICE,
            limit=ENOUGH_ROOM_FOR_THEM_ALL,
            floor=NO_FLOOR_WORTH_MENTIONING
        )) \
        .then(these_incidents_come_back([the_one_most_like_it, the_one_less_like_it]))


@pytest.mark.component
def test_only_this_services_incidents_are_recalled(store: QdrantClient) -> None:
    # The narrowing, and the one question a vector store answers badly: whether
    # two incidents happened to the same service is exact, and a description
    # that merely mentions a service name is not an answer to it.
    the_one_here = "ours"
    the_one_somewhere_else = "somebody-elses"
    another_service = "io-warehouse"

    remember(store, SOME_COLLECTION, _an_incident(the_one_here), WHAT_IS_SEARCHED_FOR)
    remember(store,
             SOME_COLLECTION,
             _an_incident(the_one_somewhere_else, service=another_service),
             WHAT_IS_SEARCHED_FOR)

    Scenario() \
        .given(store) \
        .when(lambda: recalled(
            store,
            SOME_COLLECTION,
            WHAT_IS_SEARCHED_FOR,
            service=SOME_SERVICE,
            limit=ENOUGH_ROOM_FOR_THEM_ALL,
            floor=NO_FLOOR_WORTH_MENTIONING
        )) \
        .then(these_incidents_come_back([the_one_here]))


@pytest.mark.component
def test_no_more_than_what_was_asked_for_comes_back(store: QdrantClient) -> None:
    # What bounds how much of the corpus one ordering decision reads. Asked for
    # one, a caller gets the nearest one rather than the nearest and whatever
    # else happened to be stored.
    the_one_most_like_it = "the-nearest-one"
    room_for_one = 1

    remember(store, SOME_COLLECTION, _an_incident("the-other-one"), SOMEWHAT_LIKE_IT)
    remember(store, SOME_COLLECTION, _an_incident(the_one_most_like_it),
             ALMOST_WHAT_IS_SEARCHED_FOR)

    Scenario() \
        .given(store) \
        .when(lambda: recalled(
            store,
            SOME_COLLECTION,
            WHAT_IS_SEARCHED_FOR,
            service=SOME_SERVICE,
            limit=room_for_one,
            floor=NO_FLOOR_WORTH_MENTIONING
        )) \
        .then(these_incidents_come_back([the_one_most_like_it]))


@pytest.mark.component
def test_one_incident_written_twice_is_one_record(store: QdrantClient) -> None:
    # A walk that was resumed writes its record again. Two copies of one
    # incident would count twice in an ordering, which is a past incident given
    # a second vote for having been interrupted.
    the_same_incident = "the-flag-one"

    remember(store, SOME_COLLECTION, _an_incident(the_same_incident), SOMEWHAT_LIKE_IT)
    remember(store, SOME_COLLECTION, _an_incident(the_same_incident),
             ALMOST_WHAT_IS_SEARCHED_FOR)

    Scenario() \
        .given(store) \
        .when(lambda: recalled(
            store,
            SOME_COLLECTION,
            WHAT_IS_SEARCHED_FOR,
            service=SOME_SERVICE,
            limit=ENOUGH_ROOM_FOR_THEM_ALL,
            floor=NO_FLOOR_WORTH_MENTIONING
        )) \
        .then(these_incidents_come_back([the_same_incident]))


@pytest.mark.component
def test_the_field_every_search_narrows_by_is_indexed(store: QdrantClient) -> None:
    # Every search here narrows to one service before anything is compared, and
    # narrowing during the search rather than after it is why a store like this
    # was chosen. Without the payload index the answers are the same and the
    # work is a scan, which is invisible until there are enough incidents for
    # it not to be.
    #
    # Only a real store can answer this: the in-memory client accepts the call,
    # warns that payload indexes do nothing locally, and reports no schema.
    Scenario() \
        .given(
            _remembered(store, _an_incident("the-one-that-made-the-collection"))
        ) \
        .when(lambda: store.get_collection(SOME_COLLECTION)) \
        .then(_the_payload_field_indexed_is(SERVICE_FIELD))


def _remembered(store: QdrantClient,
                incident: RememberedIncident) -> RememberedIncident:
    """Writes the record, and hands it back so a `given` can name it.

    The collection is made by the first write rather than declared anywhere, so
    this is also what brings one into existence - which is the arrangement a
    case about the collection itself needs.
    """
    remember(store, SOME_COLLECTION, incident, ALMOST_WHAT_IS_SEARCHED_FOR)

    return incident


def _what_was_tried(subject: str, verdict: Verdict) -> WhatWasTried:
    """One remembered attempt, spelled as a flag put back.

    These cases are about a record surviving the store and coming back the
    same, so the kind is fixed: which of them was done is what the ordering
    reads, and asking that here would be two suites asking one question.
    """
    return WhatWasTried(
        identity=ActionIdentity(action_type=REVERT_FEATURE_FLAG, subject=subject),
        verdict=verdict
    )


def _an_incident(incident_id: str,
                 service: str = SOME_SERVICE,
                 tried: list[tuple[str, Verdict]] | None = None) -> RememberedIncident:
    return RememberedIncident(
        incident_id=incident_id,
        described_as=DONT_CARE_DESCRIPTION,
        service=service,
        alert_name="HighErrorRate",
        tried=[
            _what_was_tried(subject, verdict)
            for subject, verdict in (tried if tried is not None else [("a-flag", Verdict.REFUTED)])
        ]
    )


def _it_remembers_trying(subject: str,
                         verdict: Verdict) -> Assertion[list[RememberedIncident]]:
    def assertion(remembered: list[RememberedIncident]) -> bool:
        tried = [attempt for incident in remembered for attempt in incident.tried]

        if _what_was_tried(subject, verdict) not in tried:
            raise AssertionError(f"Expected [{subject}] [{verdict}] among {tried}")

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
