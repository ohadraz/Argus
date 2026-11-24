"""The deliverer: one pass against a real store and database, and the loop that
runs the passes.

The store is filled from the rows rather than by the walk, which is what makes
the walk's write one the fence can refuse. The integration cases are about the
pass in between: that what was filed reaches the store - a real Qdrant, through
the store's adapter - and stops waiting, that a record refiled while its old
version was on the way is delivered again, and that one deliverer at a time does
the delivering. The embedder is a stand-in with one arrangement, because what is
under test is which records arrive, never how a sentence lands.

The loop never returns, and so is driven through its sleep. Its one decision is
a unit case: a pass that failed is said and slept off, because the records it
did not deliver are still waiting and the next pass is the retry.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any
from unittest.mock import create_autospec

import psycopg
import pytest
from argus_testkit import Assertion, Scenario, all_of, attempting, calling, one_record_was_logged
from core.embedding import Embedder
from core.models import Verdict
from core.telemetry import ARGUS_INCIDENT_ID
from core.vector_store import VectorIndex, VectorSearch
from incident_memory.delivering import Pass, deliver_forever, deliver_on, holding_the_delivery
from incident_memory.filing import Filed, UnreadableRecord, file, get_undelivered
from incident_memory.keeping import Keeper, kept_in
from incident_memory.recalling import recalling_from
from incident_memory.records import RememberedIncident
from postgres import connect_from_env
from vector_store_qdrant.indexing import QdrantIndex

from incident_memory_test.framework.assertions import these_incidents_come_back
from incident_memory_test.framework.builders import (
    DONT_CARE_DESCRIPTION,
    DONT_CARE_SERVICE,
    SOME_INCIDENT,
    a_remembered_incident,
    an_identity,
)
from incident_memory_test.framework.database import (
    an_incident_on_record,
    filed_unreadable,
)

DONT_CARE_INTERVAL_SECONDS = 2.0

ENOUGH_ROOM_FOR_THEM_ALL = 10
NO_FLOOR_WORTH_MENTIONING = 0.0

# Another incident filed beside `SOME_INCIDENT`.
ANOTHER_INCIDENT = "0f5c4d6e-3a1b-4c2d-8e9f-1a2b3c4d5e70"

# The deliverer making the passes, and one started since - by a later release,
# which may hold the step a record the first one parked needed.
SOME_DELIVERER = "a deliverer"
ANOTHER_DELIVERER = "a deliverer started since"


@pytest.mark.integration
def test_a_filed_record_is_found_in_the_store_once_delivered(
    records: psycopg.Connection, store: QdrantIndex
) -> None:
    # The whole of what delivering is for: a record the walk filed is one a
    # later walk's search reaches.
    Scenario() \
        .given(
            calling(lambda: an_incident_on_record(records, SOME_INCIDENT)),
            calling(lambda: file(records, a_remembered_incident(SOME_INCIDENT)))
        ) \
        .when(lambda: deliver_on(records, _keeping_in(store), deliverer=SOME_DELIVERER)) \
        .then(_the_store_holds(store, [SOME_INCIDENT]))


@pytest.mark.integration
def test_a_delivered_record_waits_no_longer(
    records: psycopg.Connection, store: QdrantIndex
) -> None:
    # Marked once it is in the store, so the next pass does not embed it again.
    Scenario() \
        .given(
            calling(lambda: an_incident_on_record(records, SOME_INCIDENT)),
            calling(lambda: file(records, a_remembered_incident(SOME_INCIDENT)))
        ) \
        .when(lambda: deliver_on(records, _keeping_in(store), deliverer=SOME_DELIVERER)) \
        .then(_nothing_waits(records))


@pytest.mark.integration
def test_a_record_refiled_while_it_was_delivered_waits_again(
    records: psycopg.Connection, store: QdrantIndex
) -> None:
    # The pass read one version and the walk filed another before the pass
    # marked it. The mark is for the version that was kept, so the newer one
    # is still owed the store - and a mark for whatever the row says now would
    # leave the store holding the older record for good.
    what_it_says_now = a_remembered_incident(
        SOME_INCIDENT, tried=[(an_identity("new-checkout-flow"), Verdict.CONFIRMED)]
    )

    Scenario() \
        .given(
            calling(lambda: an_incident_on_record(records, SOME_INCIDENT)),
            calling(lambda: file(records, a_remembered_incident(
                SOME_INCIDENT, tried=[(an_identity("new-checkout-flow"), Verdict.REFUTED)]
            )))
        ) \
        .when(lambda: deliver_on(records, _keeping_in(store, then_refiling=what_it_says_now),
                                 deliverer=SOME_DELIVERER)) \
        .then(_these_wait(records, [(SOME_INCIDENT, 2)]))


@pytest.mark.integration
def test_a_pass_while_another_deliverer_is_in_one_delivers_nothing(
    records: psycopg.Connection, store: QdrantIndex
) -> None:
    # Two deliverers at once can leave the store holding an older record for
    # good: one reads a version, the other delivers a newer one, and the first
    # then writes the older one over it. So a pass waits its turn rather than
    # racing - the next interval is soon enough.
    with connect_from_env() as another_deliverers, holding_the_delivery(another_deliverers):
        Scenario() \
            .given(
                calling(lambda: an_incident_on_record(records, SOME_INCIDENT)),
                calling(lambda: file(records, a_remembered_incident(SOME_INCIDENT)))
            ) \
            .when(lambda: deliver_on(records, _keeping_in(store), deliverer=SOME_DELIVERER)) \
            .then(all_of(
                _the_store_holds(store, []),
                _these_wait(records, [(SOME_INCIDENT, 1)])
            ))


@pytest.mark.integration
def test_a_pass_that_failed_leaves_the_record_for_the_next(
    records: psycopg.Connection, store: QdrantIndex
) -> None:
    # A store that was down for one pass. The record is still waiting and the
    # delivery is free again, so the next pass is the retry - on a connection
    # of its own, as the next pass is: a session may take a lock it already
    # holds, so a retry on the same one would pass with the lock never given
    # back, and every deliverer after it would wait for good.
    Scenario() \
        .given(
            calling(lambda: an_incident_on_record(records, SOME_INCIDENT)),
            calling(lambda: file(records, a_remembered_incident(SOME_INCIDENT))),
            calling(attempting(lambda: deliver_on(records, _a_store_that_is_down(),
                                                  deliverer=SOME_DELIVERER)))
        ) \
        .when(lambda: _on_a_connection_of_its_own(
            lambda the_next_pass: deliver_on(the_next_pass, _keeping_in(store),
                                             deliverer=SOME_DELIVERER)
        )) \
        .then(_the_store_holds(store, [SOME_INCIDENT]))


@pytest.mark.integration
def test_a_record_that_cannot_be_read_is_parked_and_the_rest_delivered(
    records: psycopg.Connection, store: QdrantIndex, caplog: pytest.LogCaptureFixture
) -> None:
    # Left waiting, it would come back first in every batch and fail it, and
    # every record behind it would wait for good. Said as an error, because
    # the store is missing a record until a release that can read it starts.
    Scenario() \
        .given(
            calling(lambda: an_incident_on_record(records, SOME_INCIDENT)),
            calling(lambda: an_incident_on_record(records, ANOTHER_INCIDENT)),
            calling(lambda: file(records, a_remembered_incident(SOME_INCIDENT))),
            calling(lambda: file(records, a_remembered_incident(ANOTHER_INCIDENT))),
            calling(lambda: filed_unreadable(records, SOME_INCIDENT))
        ) \
        .when(lambda: deliver_on(records, _keeping_in(store), deliverer=SOME_DELIVERER)) \
        .then(all_of(
            _the_store_holds(store, [ANOTHER_INCIDENT]),
            _nothing_waits(records),
            one_record_was_logged(caplog, "incident_memory.delivering", logging.ERROR,
                                  "record parked: it cannot be read",
                                  {ARGUS_INCIDENT_ID: SOME_INCIDENT})
        ))


@pytest.mark.integration
def test_a_parked_record_is_not_marked_delivered(
    records: psycopg.Connection, store: QdrantIndex
) -> None:
    # The store never took it, so a deliverer started since - as every release
    # starts one - finds it waiting, for whichever can read it.
    Scenario() \
        .given(
            calling(lambda: an_incident_on_record(records, SOME_INCIDENT)),
            calling(lambda: file(records, a_remembered_incident(SOME_INCIDENT))),
            calling(lambda: filed_unreadable(records, SOME_INCIDENT)),
            calling(lambda: deliver_on(records, _keeping_in(store), deliverer=SOME_DELIVERER))
        ) \
        .when(lambda: get_undelivered(records, ENOUGH_ROOM_FOR_THEM_ALL,
                                      deliverer=ANOTHER_DELIVERER)) \
        .then(_these_are_waiting([(SOME_INCIDENT, CANNOT_BE_READ)]))


@pytest.mark.unit
def test_a_pass_that_failed_is_logged_as_a_warning_and_slept_off(
    caplog: pytest.LogCaptureFixture
) -> None:
    # A warning rather than an error: nobody has to act. The records are still
    # waiting when the loop next wakes, and nothing a walk waits on is behind
    # them.
    Scenario() \
        .when(
            attempting(
                lambda: deliver_forever(
                    DONT_CARE_INTERVAL_SECONDS,
                    _a_pass_that_fails_with(ConnectionError("connection refused")),
                    sleep=_a_sleep_that_ends_the_loop()
                )
            )
        ) \
        .then(
            one_record_was_logged(caplog, "incident_memory.delivering", logging.WARNING,
                                  "delivery pass failed",
                                  failure=ConnectionError)
        )


def _an_embedder() -> Embedder:
    """A model with one arrangement instead of weights.

    Every record here is described the same way, so the one text it is given
    is the one the search asks with.
    """
    def embed(texts: list[str], /) -> list[list[float]]:
        return [[1.0, 0.0, 0.0, 0.0] for _ in texts]

    return embed


def _keeping_in(store: VectorIndex,
                then_refiling: RememberedIncident | None = None) -> Keeper:
    """The store's own keeper - and, where asked, the walk refiling the same
    incident while the record is on its way."""
    keep = kept_in(store, _an_embedder())

    def keeping(record: RememberedIncident) -> None:
        keep(record)

        if then_refiling is not None:
            with connect_from_env() as the_walks:
                file(the_walks, then_refiling)

    return keeping


def _on_a_connection_of_its_own(step: Callable[[psycopg.Connection], int]) -> int:
    """`step`, on a connection no earlier pass has held."""
    with connect_from_env() as conn:
        return step(conn)


def _a_store_that_is_down() -> Keeper:
    def keep(dont_care_record: RememberedIncident) -> None:
        raise ConnectionError("connection refused")

    return keep


def _the_store_holds(store: VectorSearch, expected: list[str]) -> Assertion[object]:
    def assertion(dont_care_result: object) -> bool:
        found = recalling_from(
            store,
            _an_embedder(),
            limit=ENOUGH_ROOM_FOR_THEM_ALL,
            floor=NO_FLOOR_WORTH_MENTIONING
        )(DONT_CARE_DESCRIPTION, DONT_CARE_SERVICE)

        return these_incidents_come_back(expected)(found)

    return assertion


# Which incidents wait, each with the version waiting - or `CANNOT_BE_READ`
# where its record could not be.
type _Waiting = list[tuple[str, int | None]]
CANNOT_BE_READ = None


def _these_wait(records: psycopg.Connection, expected: _Waiting) -> Assertion[object]:
    """What waits for the deliverer that made the passes."""
    def assertion(dont_care_result: object) -> bool:
        return _these_are_waiting(expected)(
            get_undelivered(records, ENOUGH_ROOM_FOR_THEM_ALL, deliverer=SOME_DELIVERER)
        )

    return assertion


def _these_are_waiting(expected: _Waiting) -> Assertion[list[Filed | UnreadableRecord]]:
    def assertion(found: list[Filed | UnreadableRecord]) -> bool:
        waiting = _waiting(found)

        if waiting != expected:
            raise AssertionError(
                f"Expected {expected} waiting to be delivered, got {waiting}."
            )

        return True

    return assertion


def _nothing_waits(records: psycopg.Connection) -> Assertion[object]:
    return _these_wait(records, [])


def _waiting(filed: list[Filed | UnreadableRecord]) -> _Waiting:
    return [(one.incident_id, CANNOT_BE_READ) if isinstance(one, UnreadableRecord)
            else (one.record.incident_id, one.version)
            for one in filed]


def _a_pass_that_fails_with(error: Exception) -> Any:
    return create_autospec(Pass, instance=True, side_effect=error)


class _TheLoopWasEnded(Exception):
    """Raised from the loop's first sleep, which is the only way out of it."""


def _a_sleep_that_ends_the_loop() -> Any:
    """A sleep that never waits, and ends a loop that would otherwise not."""
    def sleep(dont_care_seconds: float) -> None:
        raise _TheLoopWasEnded()

    return sleep
