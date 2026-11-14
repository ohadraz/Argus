"""What a search does when the store answers it with a failure.

The search itself - the narrowing, the floor, the round trip - is asserted
against a real store in this module's component tests. What belongs here is
what no real store can be made to do on demand: fail once and then answer,
fail every time, or refuse the question outright.
"""

from __future__ import annotations

from typing import Any
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
    the_answer_was,
)
from httpx import Headers
from incident_memory.recalling import RECORD_FIELD, recalled
from incident_memory.records import RememberedIncident
from qdrant_client import QdrantClient
from qdrant_client.http.exceptions import UnexpectedResponse
from qdrant_client.http.models import QueryResponse, ScoredPoint

from incident_memory_test.framework.builders import a_remembered_incident

DONT_CARE_COLLECTION = "incidents"
DONT_CARE_VECTOR = [1.0, 0.0, 0.0, 0.0]
DONT_CARE_SERVICE = "io-shop"
DONT_CARE_LIMIT = 5
DONT_CARE_FLOOR = 0.5
DONT_CARE_SCORE = 0.9
DONT_CARE_RETRY_SECONDS = 0.5

# What the store answered a test search with when it failed for itself: a
# server error, which says nothing about the question asked.
THE_STORE_FAILED = 500
# And a refusal of the question itself, which asking again cannot change.
THE_QUESTION_WAS_REFUSED = 400


@pytest.mark.unit
def test_a_search_the_store_failed_once_is_asked_again() -> None:
    # A store that answered "Expected at least one response for one query" with
    # a 500 failed the case searching it while the record it looked for was
    # there: the next search would have found it.
    some_incident = a_remembered_incident()
    some_attempts = 2

    Scenario() \
        .given(
            a_store := _a_store_answering(_it_failed(THE_STORE_FAILED),
                                          _the_points(some_incident))
        ) \
        .when(
            lambda: recalled(a_store, DONT_CARE_COLLECTION, DONT_CARE_VECTOR,
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
            a_store := _a_store_answering_every_time(_it_failed(THE_STORE_FAILED))
        ) \
        .when(
            attempting(lambda: recalled(a_store, DONT_CARE_COLLECTION, DONT_CARE_VECTOR,
                                        service=DONT_CARE_SERVICE, limit=DONT_CARE_LIMIT,
                                        floor=DONT_CARE_FLOOR, attempts=some_attempts,
                                        retry_seconds=DONT_CARE_RETRY_SECONDS,
                                        sleep=dont_care_sleep))
        ) \
        .then(
            all_of(
                an_error_was_raised(UnexpectedResponse),
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
            a_store := _a_store_answering(_it_failed(THE_STORE_FAILED),
                                          _the_points(a_remembered_incident()))
        ) \
        .when(
            lambda: recalled(a_store, DONT_CARE_COLLECTION, DONT_CARE_VECTOR,
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
    # A 4xx is about the question, and the same question gets the same answer.
    some_attempts = 3

    Scenario() \
        .given(
            a_store := _a_store_answering(_it_failed(THE_QUESTION_WAS_REFUSED),
                                          _the_points(a_remembered_incident()))
        ) \
        .when(
            attempting(lambda: recalled(a_store, DONT_CARE_COLLECTION, DONT_CARE_VECTOR,
                                        service=DONT_CARE_SERVICE, limit=DONT_CARE_LIMIT,
                                        floor=DONT_CARE_FLOOR, attempts=some_attempts,
                                        retry_seconds=DONT_CARE_RETRY_SECONDS,
                                        sleep=dont_care_sleep))
        ) \
        .then(
            all_of(
                an_error_was_raised(UnexpectedResponse),
                _the_store_was_asked(a_store, times=1)
            )
        )


def _a_store_answering(*answers: object) -> Any:
    store = create_autospec(QdrantClient, instance=True)
    store.collection_exists.return_value = True
    store.query_points.side_effect = list(answers)
    return store


def _a_store_answering_every_time(failure: Exception) -> Any:
    store = create_autospec(QdrantClient, instance=True)
    store.collection_exists.return_value = True
    store.query_points.side_effect = failure
    return store


def _it_failed(status: int) -> UnexpectedResponse:
    return UnexpectedResponse(status_code=status, reason_phrase="", content=b"",
                              headers=Headers())


def _the_points(*incidents: RememberedIncident) -> QueryResponse:
    return QueryResponse(points=[
        ScoredPoint(id=position, version=0, score=DONT_CARE_SCORE,
                    payload={RECORD_FIELD: incident.model_dump(mode="json")})
        for position, incident in enumerate(incidents)
    ])


def _the_store_was_asked(store: Any, *, times: int) -> Assertion[Any]:
    def assertion(dont_care_result: Any) -> bool:
        asked = store.query_points.call_count
        if asked != times:
            raise AssertionError(f"Expected the store to be searched [{times}] times, "
                                 f"and it was searched [{asked}].")

        return True

    return assertion


def _it_waited(waited: Kept[float], expected: list[float]) -> Assertion[Any]:
    def assertion(dont_care_result: Any) -> bool:
        if waited.taken != expected:
            raise AssertionError(f"Expected the search to wait [{expected}] seconds between "
                                 f"attempts, and it waited [{waited.taken}].")

        return True

    return assertion
