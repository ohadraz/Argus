"""Delivering filed records to the store, against both of them for real.

The store is filled from the rows rather than by the walk, which is what makes
the walk's write one the fence can refuse. These cases are about the pass in
between: that what was filed reaches the store and stops waiting, that a record
refiled while its old version was on the way is delivered again, that one
deliverer at a time does the delivering, and that a write the fence refused
leaves the store nothing to hold.

The embedder is a stand-in with one arrangement, because what is under test is
which records arrive, never how a sentence lands.
"""

from __future__ import annotations

from collections.abc import Callable

import psycopg
import pytest
from argus_core import Fence, connect_from_env, fence, was_lost
from argus_core.embedding import Embedder
from argus_core.models import Verdict
from argus_testkit import Assertion, Scenario, all_of, attempting, calling
from incident_memory.delivering import deliver_on, holding_the_delivery
from incident_memory.filing import Filed, file, get_undelivered
from incident_memory.keeping import Keeper, kept_in
from incident_memory.recalling import recalling_from
from incident_memory.records import RememberedIncident
from qdrant_client import QdrantClient

from incident_memory_test.framework.assertions import these_incidents_come_back
from incident_memory_test.framework.builders import (
    DONT_CARE_DESCRIPTION,
    DONT_CARE_SERVICE,
    SOME_INCIDENT,
    a_remembered_incident,
    an_identity,
)
from incident_memory_test.framework.database import (
    a_claim_since_taken_back,
    an_incident_on_record,
)

SOME_COLLECTION = "incidents"

ENOUGH_ROOM_FOR_THEM_ALL = 10
NO_FLOOR_WORTH_MENTIONING = 0.0


@pytest.mark.component
def test_a_filed_record_is_found_in_the_store_once_delivered(
    records: psycopg.Connection, store: QdrantClient
) -> None:
    # The whole of what delivering is for: a record the walk filed is one a
    # later walk's search reaches.
    Scenario() \
        .given(
            calling(lambda: an_incident_on_record(records, SOME_INCIDENT)),
            calling(lambda: file(records, a_remembered_incident(SOME_INCIDENT)))
        ) \
        .when(lambda: deliver_on(records, _keeping_in(store))) \
        .then(_the_store_holds(store, [SOME_INCIDENT]))


@pytest.mark.component
def test_a_delivered_record_waits_no_longer(
    records: psycopg.Connection, store: QdrantClient
) -> None:
    # Marked once it is in the store, so the next pass does not embed it again.
    Scenario() \
        .given(
            calling(lambda: an_incident_on_record(records, SOME_INCIDENT)),
            calling(lambda: file(records, a_remembered_incident(SOME_INCIDENT)))
        ) \
        .when(lambda: deliver_on(records, _keeping_in(store))) \
        .then(_nothing_waits(records))


@pytest.mark.component
def test_a_record_refiled_while_it_was_delivered_waits_again(
    records: psycopg.Connection, store: QdrantClient
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
        .when(lambda: deliver_on(records, _keeping_in(store, then_refiling=what_it_says_now))) \
        .then(_these_wait(records, [(SOME_INCIDENT, 2)]))


@pytest.mark.component
def test_a_pass_while_another_deliverer_is_in_one_delivers_nothing(
    records: psycopg.Connection, store: QdrantClient
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
            .when(lambda: deliver_on(records, _keeping_in(store))) \
            .then(all_of(
                _the_store_holds(store, []),
                _these_wait(records, [(SOME_INCIDENT, 1)])
            ))


@pytest.mark.component
def test_a_pass_that_failed_leaves_the_record_for_the_next(
    records: psycopg.Connection, store: QdrantClient
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
            calling(attempting(lambda: deliver_on(records, _a_store_that_is_down())))
        ) \
        .when(lambda: _on_a_connection_of_its_own(
            lambda the_next_pass: deliver_on(the_next_pass, _keeping_in(store))
        )) \
        .then(_the_store_holds(store, [SOME_INCIDENT]))


@pytest.mark.component
def test_a_record_a_lost_run_could_not_file_leaves_nothing_to_deliver(
    records: psycopg.Connection
) -> None:
    # The reason the walk writes a row rather than the store. A walk paused
    # past its lease, its run taken back, wakes and files what it tried: the
    # fence refuses the row, and a deliverer carries only rows, so nothing
    # reaches the store over the record of the walk that holds the run now.
    Scenario() \
        .given(
            an_incident := an_incident_on_record(records, SOME_INCIDENT),
            stale := a_claim_since_taken_back(records, an_incident)
        ) \
        .when(attempting(lambda: _filed_for(stale, a_remembered_incident(SOME_INCIDENT)))) \
        .then(all_of(
            _the_run_was_lost(),
            _nothing_waits(records)
        ))


def _an_embedder() -> Embedder:
    """A model with one arrangement instead of weights.

    Every record here is described the same way, so the one text it is given
    is the one the search asks with.
    """
    def embed(texts: list[str], /) -> list[list[float]]:
        return [[1.0, 0.0, 0.0, 0.0] for _ in texts]

    return embed


def _keeping_in(store: QdrantClient,
                then_refiling: RememberedIncident | None = None) -> Keeper:
    """The store's own keeper - and, where asked, the walk refiling the same
    incident while the record is on its way."""
    keep = kept_in(store, SOME_COLLECTION, _an_embedder())

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


def _filed_for(claim: Fence, record: RememberedIncident) -> None:
    """Files `record` on a connection fenced with `claim`, as a worker's is."""
    with connect_from_env() as the_walks:
        fence(the_walks, claim)
        file(the_walks, record)


def _the_run_was_lost() -> Assertion[Exception | None]:
    """Refused as a lost run, and not for anything else a write can fail for."""
    def assertion(refused: Exception | None) -> bool:
        if refused is None or not was_lost(refused):
            raise AssertionError(
                f"Expected the write refused because the run was lost, got [{refused!r}]."
            )

        return True

    return assertion


def _the_store_holds(store: QdrantClient, expected: list[str]) -> Assertion[object]:
    def assertion(dont_care_result: object) -> bool:
        found = recalling_from(
            store,
            SOME_COLLECTION,
            _an_embedder(),
            limit=ENOUGH_ROOM_FOR_THEM_ALL,
            floor=NO_FLOOR_WORTH_MENTIONING
        )(DONT_CARE_DESCRIPTION, DONT_CARE_SERVICE)

        return these_incidents_come_back(expected)(found)

    return assertion


def _these_wait(records: psycopg.Connection,
                expected: list[tuple[str, int]]) -> Assertion[object]:
    def assertion(dont_care_result: object) -> bool:
        waiting = _waiting(get_undelivered(records, ENOUGH_ROOM_FOR_THEM_ALL))

        if waiting != expected:
            raise AssertionError(
                f"Expected {expected} waiting to be delivered, got {waiting}."
            )

        return True

    return assertion


def _nothing_waits(records: psycopg.Connection) -> Assertion[object]:
    return _these_wait(records, [])


def _waiting(filed: list[Filed]) -> list[tuple[str, int]]:
    return [(one.record.incident_id, one.version) for one in filed]
