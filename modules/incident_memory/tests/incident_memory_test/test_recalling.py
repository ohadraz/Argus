"""Recall, against a real store and against stores that answer on cue.

The search itself - the narrowing, the floor, the ordering, the round trip - is
asked of a real Qdrant through the store's adapter, with records put there by
the writing side's own `remember`, so a search here is a search of what a
deliverer leaves behind. The vectors are made up rather than embedded: four
dimensions, one of them set per record, so "near" and "far" are arranged rather
than hoped for, where a real embedder would make every case depend on how a
sentence happens to land.

What no real store can be made to do on demand - fail once and then answer, fail
every time, refuse the question, or give no answer at all - is asked of a store
that does it on cue, and so is what recall asks of the store, which a real one
answers the same way whether the narrowing was asked of it or done afterwards.
"""

from __future__ import annotations

import logging
from typing import Any, Final
from unittest.mock import create_autospec

import pytest
from argus_testkit import (
    Assertion,
    Kept,
    Scenario,
    all_of,
    an_error_was_raised,
    attempting,
    dont_care_sleep,
    one_record_was_logged,
    the_answer_was,
)
from core.models import REVERT_FEATURE_FLAG, ActionIdentity, Verdict, WhatWasTried
from core.stored import REMEMBERED_INCIDENT, SHIPPED, Shapes
from core.vector_store import (
    Equals,
    Hit,
    VectorQueryRefused,
    VectorSearch,
    VectorStoreUnavailable,
    VectorStoreUnreachable,
)
from incident_memory.keeping import remember
from incident_memory.recalling import RECORD_FIELD, SERVICE_FIELD, SHAPE_FIELD, recalled
from incident_memory.records import RememberedIncident
from vector_store_qdrant.indexing import QdrantIndex

from incident_memory_test.framework.assertions import these_incidents_come_back
from incident_memory_test.framework.builders import a_remembered_incident

DONT_CARE_VECTOR = [1.0, 0.0, 0.0, 0.0]
DONT_CARE_SERVICE = "io-shop"
DONT_CARE_LIMIT = 5
DONT_CARE_FLOOR = 0.5
DONT_CARE_SCORE = 0.9
DONT_CARE_RETRY_SECONDS = 0.5
DONT_CARE_ATTEMPTS = 1
# What a failing store says. Nothing reads it: recall decides by the failure's
# kind, never by its words.
DONT_CARE_FAILURE = "the store failed"
DONT_CARE_REFUSAL = "the question was refused"
DONT_CARE_NO_ROUTE = "no route to the store"

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
DONT_CARE_ALERT = "HighErrorRate"
DONT_CARE_FLAG = "a-flag"
SOME_OTHER_INCIDENT = "the-other-one"

# The logger recall writes to, and what it says of a record it passed over.
RECALL: Final = "incident_memory.recalling"
PASSED_OVER: Final = "recalled record passed over: it cannot be read"
# The id of the point holding nothing a reader can bring up.
UNREADABLE_POINT = "unreadable"
# What a step from a record's shape to the next one writes, where no release
# has shipped a step: a description no record here is kept with, so a record
# carrying it was brought up through the step and not read as it was kept.
A_DESCRIPTION_A_STEP_WROTE = "written by the step to the next shape"


@pytest.mark.integration
def test_an_incident_written_is_found_again(store: QdrantIndex) -> None:
    # The round trip, and the whole record rather than its identity: what a
    # recall is for is the list of what was tried, and an id the caller then has
    # to go and look up somewhere else would make memory a second database.
    the_incident_that_happened_before = "the-flag-one"
    the_flag_that_did_not_help = "new-checkout-flow"

    Scenario() \
        .given(_remembered(store, (
            _an_incident(the_incident_that_happened_before,
                         tried=[(the_flag_that_did_not_help, Verdict.REFUTED)]),
            ALMOST_WHAT_IS_SEARCHED_FOR
        ))) \
        .when(lambda: recalled(
            store,
            WHAT_IS_SEARCHED_FOR,
            service=SOME_SERVICE,
            limit=ENOUGH_ROOM_FOR_THEM_ALL,
            floor=NO_FLOOR_WORTH_MENTIONING
        )) \
        .then(all_of(
            these_incidents_come_back([the_incident_that_happened_before]),
            _it_remembers_trying(the_flag_that_did_not_help, Verdict.REFUTED)
        ))


@pytest.mark.integration
def test_a_store_that_has_never_been_written_to_finds_nothing(store: QdrantIndex) -> None:
    # The ordinary state of a first deployment, and answered rather than raised:
    # before the first incident there is nothing to recall, which is a fact
    # about the corpus rather than a failure of the store.
    Scenario() \
        .given(_remembered(store)) \
        .when(lambda: recalled(
            store,
            WHAT_IS_SEARCHED_FOR,
            service=SOME_SERVICE,
            limit=ENOUGH_ROOM_FOR_THEM_ALL,
            floor=NO_FLOOR_WORTH_MENTIONING
        )) \
        .then(these_incidents_come_back([]))


@pytest.mark.integration
def test_an_incident_further_off_than_the_floor_is_not_offered(store: QdrantIndex) -> None:
    # A nearest-neighbour search always answers. Without a floor, a corpus
    # holding one unrelated incident would hand it back as the nearest thing it
    # had, and an ordering would demote a candidate on the strength of it.
    the_one_that_is_like_it = "the-near-one"
    the_one_that_is_not = "the-far-one"
    a_floor_only_the_near_one_clears = 0.5

    Scenario() \
        .given(_remembered(store,
                           (_an_incident(the_one_that_is_like_it), ALMOST_WHAT_IS_SEARCHED_FOR),
                           (_an_incident(the_one_that_is_not), NOTHING_LIKE_IT))) \
        .when(lambda: recalled(
            store,
            WHAT_IS_SEARCHED_FOR,
            service=SOME_SERVICE,
            limit=ENOUGH_ROOM_FOR_THEM_ALL,
            floor=a_floor_only_the_near_one_clears
        )) \
        .then(these_incidents_come_back([the_one_that_is_like_it]))


@pytest.mark.integration
def test_the_most_like_it_comes_back_first(store: QdrantIndex) -> None:
    # A caller that trusts the order and is handed an arbitrary one reads the
    # least relevant record first - and where only some of them fit, keeps the
    # wrong ones.
    the_one_most_like_it = "the-nearest-one"
    the_one_less_like_it = "the-next-nearest-one"

    Scenario() \
        .given(_remembered(store,
                           (_an_incident(the_one_less_like_it), SOMEWHAT_LIKE_IT),
                           (_an_incident(the_one_most_like_it), ALMOST_WHAT_IS_SEARCHED_FOR))) \
        .when(lambda: recalled(
            store,
            WHAT_IS_SEARCHED_FOR,
            service=SOME_SERVICE,
            limit=ENOUGH_ROOM_FOR_THEM_ALL,
            floor=NO_FLOOR_WORTH_MENTIONING
        )) \
        .then(these_incidents_come_back([the_one_most_like_it, the_one_less_like_it]))


@pytest.mark.integration
def test_only_this_services_incidents_are_recalled(store: QdrantIndex) -> None:
    # The narrowing, and the one question a vector store answers badly: whether
    # two incidents happened to the same service is exact, and a description
    # that merely mentions a service name is not an answer to it.
    the_one_here = "ours"
    the_one_somewhere_else = "somebody-elses"
    another_service = "io-warehouse"

    Scenario() \
        .given(_remembered(
            store,
            (_an_incident(the_one_here), WHAT_IS_SEARCHED_FOR),
            (_an_incident(the_one_somewhere_else, service=another_service), WHAT_IS_SEARCHED_FOR)
        )) \
        .when(lambda: recalled(
            store,
            WHAT_IS_SEARCHED_FOR,
            service=SOME_SERVICE,
            limit=ENOUGH_ROOM_FOR_THEM_ALL,
            floor=NO_FLOOR_WORTH_MENTIONING
        )) \
        .then(these_incidents_come_back([the_one_here]))


@pytest.mark.integration
def test_no_more_than_what_was_asked_for_comes_back(store: QdrantIndex) -> None:
    # What bounds how much of the corpus one ordering decision reads. Asked for
    # one, a caller gets the nearest one rather than the nearest and whatever
    # else happened to be stored.
    the_one_most_like_it = "the-nearest-one"
    room_for_one = 1

    Scenario() \
        .given(_remembered(store,
                           (_an_incident(SOME_OTHER_INCIDENT), SOMEWHAT_LIKE_IT),
                           (_an_incident(the_one_most_like_it), ALMOST_WHAT_IS_SEARCHED_FOR))) \
        .when(lambda: recalled(
            store,
            WHAT_IS_SEARCHED_FOR,
            service=SOME_SERVICE,
            limit=room_for_one,
            floor=NO_FLOOR_WORTH_MENTIONING
        )) \
        .then(these_incidents_come_back([the_one_most_like_it]))


@pytest.mark.unit
def test_only_this_services_incidents_near_enough_are_asked_for() -> None:
    # Inside the search rather than after it. A store answers its `limit`
    # nearest, and a narrowing applied to those would hand back fewer than
    # `limit` of this service's incidents while more exist - the nearest of
    # other services taking the places this one's were owed.
    some_service = "io-warehouse"
    some_floor = 0.7

    Scenario() \
        .given(a_store := _a_store_answering(_the_hits())) \
        .when(
            lambda: recalled(a_store, DONT_CARE_VECTOR,
                             service=some_service, limit=DONT_CARE_LIMIT,
                             floor=some_floor, attempts=DONT_CARE_ATTEMPTS,
                             retry_seconds=DONT_CARE_RETRY_SECONDS,
                             sleep=dont_care_sleep)
        ) \
        .then(
            all_of(
                _the_store_was_asked_within([Equals(field=SERVICE_FIELD, value=some_service)],
                                            a_store),
                _the_store_was_asked_above(some_floor, a_store)
            )
        )


@pytest.mark.unit
def test_a_search_the_store_failed_once_is_asked_again() -> None:
    # A store that answered "Expected at least one response for one query" with
    # a 500 failed the case searching it while the record it looked for was
    # there: the next search would have found it.
    some_incident = a_remembered_incident()
    some_attempts = 2

    Scenario() \
        .given(
            a_store := _a_store_answering(VectorStoreUnavailable(DONT_CARE_FAILURE),
                                          _the_hits(some_incident))
        ) \
        .when(
            lambda: recalled(a_store, DONT_CARE_VECTOR,
                             service=DONT_CARE_SERVICE, limit=DONT_CARE_LIMIT,
                             floor=DONT_CARE_FLOOR, attempts=some_attempts,
                             retry_seconds=DONT_CARE_RETRY_SECONDS,
                             sleep=dont_care_sleep)
        ) \
        .then(
            the_answer_was([some_incident])
        )


@pytest.mark.unit
def test_a_search_the_store_keeps_failing_is_asked_as_often_as_configured_then_raises() -> None:
    # Asked again a few times, never forever: a store that is down stays down,
    # and the caller is the one who knows what to do without it.
    some_attempts = 3

    Scenario() \
        .given(
            a_store := _a_store_answering_every_time(VectorStoreUnavailable(DONT_CARE_FAILURE))
        ) \
        .when(
            attempting(lambda: recalled(a_store, DONT_CARE_VECTOR,
                                        service=DONT_CARE_SERVICE, limit=DONT_CARE_LIMIT,
                                        floor=DONT_CARE_FLOOR, attempts=some_attempts,
                                        retry_seconds=DONT_CARE_RETRY_SECONDS,
                                        sleep=dont_care_sleep))
        ) \
        .then(
            all_of(
                an_error_was_raised(VectorStoreUnavailable),
                _the_store_was_asked(a_store, times=some_attempts)
            )
        )


@pytest.mark.unit
def test_a_search_waits_the_configured_pause_before_asking_again() -> None:
    some_attempts = 2
    some_retry_seconds = 1.5
    waited: Kept[float] = Kept()

    Scenario() \
        .given(
            a_store := _a_store_answering(VectorStoreUnavailable(DONT_CARE_FAILURE),
                                          _the_hits(a_remembered_incident()))
        ) \
        .when(
            lambda: recalled(a_store, DONT_CARE_VECTOR,
                             service=DONT_CARE_SERVICE, limit=DONT_CARE_LIMIT,
                             floor=DONT_CARE_FLOOR, attempts=some_attempts,
                             retry_seconds=some_retry_seconds,
                             sleep=waited.take)
        ) \
        .then(
            _it_waited(waited, [some_retry_seconds])
        )


@pytest.mark.unit
def test_a_question_the_store_refused_is_not_asked_again() -> None:
    # A refusal is about the question, and the same question gets the same answer.
    some_attempts = 3

    Scenario() \
        .given(
            a_store := _a_store_answering(VectorQueryRefused(DONT_CARE_REFUSAL),
                                          _the_hits(a_remembered_incident()))
        ) \
        .when(
            attempting(lambda: recalled(a_store, DONT_CARE_VECTOR,
                                        service=DONT_CARE_SERVICE, limit=DONT_CARE_LIMIT,
                                        floor=DONT_CARE_FLOOR, attempts=some_attempts,
                                        retry_seconds=DONT_CARE_RETRY_SECONDS,
                                        sleep=dont_care_sleep))
        ) \
        .then(
            all_of(
                an_error_was_raised(VectorQueryRefused),
                _the_store_was_asked(a_store, times=1)
            )
        )


@pytest.mark.unit
def test_a_store_that_could_not_be_reached_is_not_asked_again() -> None:
    # Asking again is for a store that answered with a failure of its own. One
    # that gave no answer at all is left to the caller, which recalls nothing.
    some_attempts = 3

    Scenario() \
        .given(
            a_store := _a_store_answering(VectorStoreUnreachable(DONT_CARE_NO_ROUTE),
                                          _the_hits(a_remembered_incident()))
        ) \
        .when(
            attempting(lambda: recalled(a_store, DONT_CARE_VECTOR,
                                        service=DONT_CARE_SERVICE, limit=DONT_CARE_LIMIT,
                                        floor=DONT_CARE_FLOOR, attempts=some_attempts,
                                        retry_seconds=DONT_CARE_RETRY_SECONDS,
                                        sleep=dont_care_sleep))
        ) \
        .then(
            all_of(
                an_error_was_raised(VectorStoreUnreachable),
                _the_store_was_asked(a_store, times=1)
            )
        )


@pytest.mark.unit
def test_a_search_allowed_no_attempts_is_refused_before_the_store_is_asked() -> None:
    # Zero attempts is not "ask nothing, find nothing": the setting it comes from
    # refuses it, and a caller that got here some other way has a bug to hear of.
    no_attempts = 0

    Scenario() \
        .given(
            a_store := _a_store_answering(_the_hits(a_remembered_incident()))
        ) \
        .when(
            attempting(lambda: recalled(a_store, DONT_CARE_VECTOR,
                                        service=DONT_CARE_SERVICE, limit=DONT_CARE_LIMIT,
                                        floor=DONT_CARE_FLOOR, attempts=no_attempts,
                                        retry_seconds=DONT_CARE_RETRY_SECONDS,
                                        sleep=dont_care_sleep))
        ) \
        .then(
            all_of(
                an_error_was_raised(ValueError),
                _the_store_was_asked(a_store, times=0)
            )
        )


@pytest.mark.unit
def test_a_record_that_cannot_be_read_is_passed_over_and_the_rest_recalled(
    caplog: pytest.LogCaptureFixture
) -> None:
    # One bad point would otherwise take every like incident from the walk.
    # Nothing is lost by it: the store is filled again from the filed rows.
    some_incident = a_remembered_incident()

    Scenario() \
        .given(
            a_store := _a_store_answering([_a_hit_holding_nothing_readable(),
                                           *_the_hits(some_incident)])
        ) \
        .when(
            lambda: recalled(a_store, DONT_CARE_VECTOR,
                             service=DONT_CARE_SERVICE, limit=DONT_CARE_LIMIT,
                             floor=DONT_CARE_FLOOR)
        ) \
        .then(all_of(
            the_answer_was([some_incident]),
            one_record_was_logged(caplog, RECALL, logging.WARNING, PASSED_OVER,
                                  {"point": UNREADABLE_POINT, "newer": False})
        ))


@pytest.mark.unit
def test_a_record_a_newer_release_kept_is_passed_over(
    caplog: pytest.LogCaptureFixture
) -> None:
    # Read as the shape this release knows, it would be read wrong. Said as
    # newer, so a reader of the log knows a release that knows it reads it.
    some_incident = a_remembered_incident()
    the_hit = _the_hits(some_incident)[0]

    Scenario() \
        .given(
            a_store := _a_store_answering([_kept_by_a_newer_release(the_hit)])
        ) \
        .when(
            lambda: recalled(a_store, DONT_CARE_VECTOR,
                             service=DONT_CARE_SERVICE, limit=DONT_CARE_LIMIT,
                             floor=DONT_CARE_FLOOR)
        ) \
        .then(all_of(
            the_answer_was([]),
            one_record_was_logged(caplog, RECALL, logging.WARNING, PASSED_OVER,
                                  {"point": the_hit.id, "newer": True})
        ))


@pytest.mark.unit
def test_a_record_kept_before_shapes_were_recorded_is_read_as_the_first_shape() -> None:
    # Its point carries no shape. Read with the shapes of a release one step
    # on, it is brought up from the first.
    some_incident = a_remembered_incident()
    one_step_on = Shapes(upcasters={REMEMBERED_INCIDENT: [_a_step_writing_the_description]})

    Scenario() \
        .given(
            a_store := _a_store_answering(_the_hits(some_incident))
        ) \
        .when(
            lambda: recalled(a_store, DONT_CARE_VECTOR,
                             service=DONT_CARE_SERVICE, limit=DONT_CARE_LIMIT,
                             floor=DONT_CARE_FLOOR, shapes=one_step_on)
        ) \
        .then(
            the_answer_was([
                some_incident.model_copy(update={"described_as": A_DESCRIPTION_A_STEP_WROTE})
            ])
        )


def _what_was_tried(subject: str, verdict: Verdict) -> WhatWasTried:
    """One remembered attempt, spelled as a flag reverted.

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
        alert_name=DONT_CARE_ALERT,
        tried=[
            _what_was_tried(subject, verdict)
            for subject, verdict in (tried if tried is not None
                                     else [(DONT_CARE_FLAG, Verdict.REFUTED)])
        ]
    )


def _remembered(store: QdrantIndex,
                *records: tuple[RememberedIncident, list[float]]) -> QdrantIndex:
    """The store, holding these records at these vectors - kept by the writing
    side's own `remember`, as a deliverer keeps them."""
    for record, vector in records:
        remember(store, record, vector)

    return store


def _it_remembers_trying(subject: str,
                         verdict: Verdict) -> Assertion[list[RememberedIncident]]:
    def assertion(remembered: list[RememberedIncident]) -> bool:
        tried = [attempt for incident in remembered for attempt in incident.tried]

        if _what_was_tried(subject, verdict) not in tried:
            raise AssertionError(f"Expected [{subject}] [{verdict}] among {tried}.")

        return True

    return assertion


def _a_store_answering(*answers: object) -> Any:
    store = create_autospec(VectorSearch, instance=True)
    store.nearest.side_effect = list(answers)
    return store


def _a_store_answering_every_time(failure: Exception) -> Any:
    store = create_autospec(VectorSearch, instance=True)
    store.nearest.side_effect = failure
    return store


def _a_hit_holding_nothing_readable() -> Hit:
    """A point whose record no reader can bring up - an empty object, missing
    everything a record has - in no shape, so it is read as the first."""
    return Hit(id=UNREADABLE_POINT, score=DONT_CARE_SCORE, payload={RECORD_FIELD: {}})


def _kept_by_a_newer_release(hit: Hit) -> Hit:
    return Hit(id=hit.id, score=hit.score,
               payload={**hit.payload, SHAPE_FIELD: SHIPPED.current(REMEMBERED_INCIDENT) + 1})


def _a_step_writing_the_description(raw: dict[str, Any]) -> dict[str, Any]:
    return {**raw, "described_as": A_DESCRIPTION_A_STEP_WROTE}


def _the_hits(*incidents: RememberedIncident) -> list[Hit]:
    return [
        Hit(id=str(position), score=DONT_CARE_SCORE,
            payload={RECORD_FIELD: incident.model_dump(mode="json")})
        for position, incident in enumerate(incidents)
    ]


def _the_store_was_asked(store: Any, *, times: int) -> Assertion[Any]:
    def assertion(dont_care_result: Any) -> bool:
        asked = store.nearest.call_count
        if asked != times:
            raise AssertionError(f"Expected the store to be searched [{times}] times, "
                                 f"and it was searched [{asked}].")

        return True

    return assertion


def _the_store_was_asked_within(where: list[Equals], store: Any) -> Assertion[Any]:
    def assertion(dont_care_result: Any) -> bool:
        asked = list(store.nearest.call_args.kwargs.get("where", ()))
        if asked != where:
            raise AssertionError(f"Expected the store to be searched within {where}, "
                                 f"and it was searched within {asked}.")

        return True

    return assertion


def _the_store_was_asked_above(floor: float, store: Any) -> Assertion[Any]:
    def assertion(dont_care_result: Any) -> bool:
        asked = store.nearest.call_args.kwargs.get("floor")
        if asked != floor:
            raise AssertionError(f"Expected the store to be searched above [{floor}], "
                                 f"and it was searched above [{asked}].")

        return True

    return assertion


def _it_waited(waited: Kept[float], expected: list[float]) -> Assertion[Any]:
    def assertion(dont_care_result: Any) -> bool:
        if waited.taken != expected:
            raise AssertionError(f"Expected the search to wait [{expected}] seconds between "
                                 f"attempts, and it waited [{waited.taken}].")

        return True

    return assertion
