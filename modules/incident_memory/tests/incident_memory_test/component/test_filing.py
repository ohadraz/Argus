"""Where a finished incident's record is filed, and what is still to be delivered.

Against a real Postgres, because what these cases are about is the database's
half: an upsert that bumps a version only when the record changed, and a mark
that moves only as far as the version it was given. A stand-in would answer both
the way its author expected.
"""

from __future__ import annotations

import psycopg
import pytest
from argus_core.models import Verdict
from argus_testkit import Assertion, Scenario, all_of, calling
from incident_memory.filing import Filed, file, get_undelivered, record_delivered
from incident_memory.records import RememberedIncident

from incident_memory_test.framework.builders import (
    SOME_INCIDENT,
    a_remembered_incident,
    an_identity,
)
from incident_memory_test.framework.database import an_incident_on_record

ENOUGH_ROOM_FOR_THEM_ALL = 10


@pytest.mark.component
def test_a_record_filed_waits_to_be_delivered_whole(records: psycopg.Connection) -> None:
    # Filed and not yet searchable: the store is filled from these rows, so a
    # row that lost part of the record on the way in is a memory of less than
    # was tried.
    the_record = _a_record_trying("new-checkout-flow", Verdict.REFUTED)

    Scenario() \
        .given(
            calling(lambda: an_incident_on_record(records, SOME_INCIDENT)),
            calling(lambda: file(records, the_record))
        ) \
        .when(lambda: get_undelivered(records, ENOUGH_ROOM_FOR_THEM_ALL)) \
        .then(_these_wait(the_record, at_version=1))


@pytest.mark.component
def test_the_same_record_filed_again_is_not_a_new_version(records: psycopg.Connection) -> None:
    # A walk that was resumed files its record again. Nothing changed, so
    # nothing is owed the store - a new version here would embed and upsert the
    # same record for every resume.
    the_record = _a_record_trying("new-checkout-flow", Verdict.REFUTED)

    Scenario() \
        .given(
            calling(lambda: an_incident_on_record(records, SOME_INCIDENT)),
            calling(lambda: file(records, the_record)),
            calling(lambda: record_delivered(records, SOME_INCIDENT, version=1)),
            calling(lambda: file(records, the_record))
        ) \
        .when(lambda: get_undelivered(records, ENOUGH_ROOM_FOR_THEM_ALL)) \
        .then(_nothing_waits())


@pytest.mark.component
def test_a_record_that_changed_is_a_new_version(records: psycopg.Connection) -> None:
    # Delivered once, then filed again saying something else. The store holds
    # the old record until this one reaches it, so it waits again.
    what_it_said_first = _a_record_trying("new-checkout-flow", Verdict.REFUTED)
    what_it_says_now = _a_record_trying("new-checkout-flow", Verdict.CONFIRMED)

    Scenario() \
        .given(
            calling(lambda: an_incident_on_record(records, SOME_INCIDENT)),
            calling(lambda: file(records, what_it_said_first)),
            calling(lambda: record_delivered(records, SOME_INCIDENT, version=1)),
            calling(lambda: file(records, what_it_says_now))
        ) \
        .when(lambda: get_undelivered(records, ENOUGH_ROOM_FOR_THEM_ALL)) \
        .then(_these_wait(what_it_says_now, at_version=2))


@pytest.mark.component
def test_a_record_delivered_at_its_version_waits_no_longer(records: psycopg.Connection) -> None:
    Scenario() \
        .given(
            calling(lambda: an_incident_on_record(records, SOME_INCIDENT)),
            calling(lambda: file(records, _a_record_trying("new-checkout-flow",
                                                           Verdict.REFUTED))),
            calling(lambda: record_delivered(records, SOME_INCIDENT, version=1))
        ) \
        .when(lambda: get_undelivered(records, ENOUGH_ROOM_FOR_THEM_ALL)) \
        .then(_nothing_waits())


@pytest.mark.component
def test_a_delivery_of_an_older_version_leaves_the_newer_one_waiting(
    records: psycopg.Connection
) -> None:
    # The race this mark is written against: a record refiled while the old
    # version was on its way to the store. The old version arriving says
    # nothing about the new one, which the store has not seen.
    what_it_says_now = _a_record_trying("new-checkout-flow", Verdict.CONFIRMED)

    Scenario() \
        .given(
            calling(lambda: an_incident_on_record(records, SOME_INCIDENT)),
            calling(lambda: file(records, _a_record_trying("new-checkout-flow",
                                                           Verdict.REFUTED))),
            calling(lambda: file(records, what_it_says_now)),
            calling(lambda: record_delivered(records, SOME_INCIDENT, version=1))
        ) \
        .when(lambda: get_undelivered(records, ENOUGH_ROOM_FOR_THEM_ALL)) \
        .then(_these_wait(what_it_says_now, at_version=2))


@pytest.mark.component
def test_a_late_mark_for_an_older_version_moves_nothing_back(
    records: psycopg.Connection
) -> None:
    # Two marks arriving out of order: the newer version delivered and marked,
    # then a mark for the older one, from a pass that read it first. The store
    # holds the newer, and a mark moved back would have it delivered again for
    # nothing - or, read the other way, say the store holds less than it does.
    Scenario() \
        .given(
            calling(lambda: an_incident_on_record(records, SOME_INCIDENT)),
            calling(lambda: file(records, _a_record_trying("new-checkout-flow",
                                                           Verdict.REFUTED))),
            calling(lambda: file(records, _a_record_trying("new-checkout-flow",
                                                           Verdict.CONFIRMED))),
            calling(lambda: record_delivered(records, SOME_INCIDENT, version=2)),
            calling(lambda: record_delivered(records, SOME_INCIDENT, version=1))
        ) \
        .when(lambda: get_undelivered(records, ENOUGH_ROOM_FOR_THEM_ALL)) \
        .then(_nothing_waits())


@pytest.mark.component
def test_the_oldest_filing_is_handed_over_first(records: psycopg.Connection) -> None:
    # What bounds one pass, and in which order. A deliverer that fell behind by
    # a thousand incidents catches up a batch at a time, rather than embedding
    # all of them before marking any - and the incidents that ended first are
    # searchable first. Filed in the order opposite to their ids, so an order
    # that fell back on the id would hand over the wrong one.
    filed_first = "0f5c4d6e-3a1b-4c2d-8e9f-1a2b3c4d5e70"
    filed_second = SOME_INCIDENT
    room_for_one = 1

    Scenario() \
        .given(
            calling(lambda: an_incident_on_record(records, filed_first)),
            calling(lambda: an_incident_on_record(records, filed_second)),
            calling(lambda: file(records, a_remembered_incident(filed_first))),
            calling(lambda: file(records, a_remembered_incident(filed_second)))
        ) \
        .when(lambda: get_undelivered(records, room_for_one)) \
        .then(_these_wait(a_remembered_incident(filed_first), at_version=1))


def _a_record_trying(subject: str, verdict: Verdict) -> RememberedIncident:
    return a_remembered_incident(SOME_INCIDENT, tried=[(an_identity(subject), verdict)])


def _these_wait(record: RememberedIncident, at_version: int) -> Assertion[list[Filed]]:
    return all_of(
        _this_many_wait(1),
        _the_record_waiting_is(record),
        _the_version_waiting_is(at_version)
    )


def _this_many_wait(expected: int) -> Assertion[list[Filed]]:
    def assertion(waiting: list[Filed]) -> bool:
        if len(waiting) != expected:
            raise AssertionError(
                f"Expected [{expected}] record(s) waiting to be delivered, got "
                f"{[one.record.incident_id for one in waiting]}."
            )

        return True

    return assertion


def _the_record_waiting_is(record: RememberedIncident) -> Assertion[list[Filed]]:
    def assertion(waiting: list[Filed]) -> bool:
        if not waiting or waiting[0].record != record:
            raise AssertionError(
                f"Expected [{record}] waiting, got {[one.record for one in waiting]}."
            )

        return True

    return assertion


def _the_version_waiting_is(version: int) -> Assertion[list[Filed]]:
    def assertion(waiting: list[Filed]) -> bool:
        if not waiting or waiting[0].version != version:
            raise AssertionError(
                f"Expected version [{version}] waiting, got "
                f"{[one.version for one in waiting]}."
            )

        return True

    return assertion


def _nothing_waits() -> Assertion[list[Filed]]:
    def assertion(waiting: list[Filed]) -> bool:
        if waiting:
            raise AssertionError(
                f"Expected nothing waiting to be delivered, got "
                f"{[(one.record.incident_id, one.version) for one in waiting]}."
            )

        return True

    return assertion
