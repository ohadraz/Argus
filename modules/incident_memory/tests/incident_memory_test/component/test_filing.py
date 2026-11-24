"""Where a finished incident's record is filed, and what is still to be delivered.

Against a real Postgres, because what these cases are about is the database's
half: an upsert that bumps a version only when the record changed, and a mark
that moves only as far as the version it was given - one for each embedding
model's collection, so what one holds says nothing of another. A stand-in would
answer both the way its author expected.

And the reason the walk files a row rather than writing the store: a filing the
fence refused, for a run since taken back, leaves nothing for a deliverer to
carry.
"""

from __future__ import annotations

from typing import Any

import psycopg
import pytest
from argus_testkit import Assertion, Scenario, all_of, attempting, calling
from core import Fence, was_lost
from core.models import Verdict
from core.stored import REMEMBERED_INCIDENT, Shapes
from incident_memory.filing import (
    Filed,
    UnreadableRecord,
    file,
    get_undelivered,
    park,
    record_delivered,
)
from incident_memory.records import RememberedIncident
from postgres import connect_from_env, fence

from incident_memory_test.framework.builders import (
    SOME_INCIDENT,
    a_remembered_incident,
    an_identity,
)
from incident_memory_test.framework.database import (
    a_claim_since_taken_back,
    an_incident_on_record,
    filed_by_a_newer_release,
    filed_unreadable,
)

ENOUGH_ROOM_FOR_THEM_ALL = 10

# The deliverer reading, and one started since - by a later release, which may
# hold the step a record one of them parked needed.
SOME_DELIVERER = "a deliverer"
ANOTHER_DELIVERER = "a deliverer started since"

# The embedding model whose collection is read and marked, and another - as a
# deployment switching models has both.
SOME_EMBEDDING_MODEL = "some-embedding-model"
ANOTHER_EMBEDDING_MODEL = "another-embedding-model"

# What a step from a record's shape to the next one writes, where no release
# has shipped a step: a description no record here is filed with, so a record
# carrying it was brought up through the step and not read as it was stored.
A_DESCRIPTION_A_STEP_WROTE = "written by the step to the next shape"

type _Waiting = list[Filed | UnreadableRecord]


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
        .when(lambda: get_undelivered(records, ENOUGH_ROOM_FOR_THEM_ALL,
                                      deliverer=SOME_DELIVERER,
                                      embedded_with=SOME_EMBEDDING_MODEL)) \
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
            calling(lambda: record_delivered(records, SOME_INCIDENT, version=1,
                                             embedded_with=SOME_EMBEDDING_MODEL)),
            calling(lambda: file(records, the_record))
        ) \
        .when(lambda: get_undelivered(records, ENOUGH_ROOM_FOR_THEM_ALL,
                                      deliverer=SOME_DELIVERER,
                                      embedded_with=SOME_EMBEDDING_MODEL)) \
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
            calling(lambda: record_delivered(records, SOME_INCIDENT, version=1,
                                             embedded_with=SOME_EMBEDDING_MODEL)),
            calling(lambda: file(records, what_it_says_now))
        ) \
        .when(lambda: get_undelivered(records, ENOUGH_ROOM_FOR_THEM_ALL,
                                      deliverer=SOME_DELIVERER,
                                      embedded_with=SOME_EMBEDDING_MODEL)) \
        .then(_these_wait(what_it_says_now, at_version=2))


@pytest.mark.component
def test_a_record_delivered_at_its_version_waits_no_longer(records: psycopg.Connection) -> None:
    Scenario() \
        .given(
            calling(lambda: an_incident_on_record(records, SOME_INCIDENT)),
            calling(lambda: file(records, _a_record_trying("new-checkout-flow",
                                                           Verdict.REFUTED))),
            calling(lambda: record_delivered(records, SOME_INCIDENT, version=1,
                                             embedded_with=SOME_EMBEDDING_MODEL))
        ) \
        .when(lambda: get_undelivered(records, ENOUGH_ROOM_FOR_THEM_ALL,
                                      deliverer=SOME_DELIVERER,
                                      embedded_with=SOME_EMBEDDING_MODEL)) \
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
            calling(lambda: record_delivered(records, SOME_INCIDENT, version=1,
                                             embedded_with=SOME_EMBEDDING_MODEL))
        ) \
        .when(lambda: get_undelivered(records, ENOUGH_ROOM_FOR_THEM_ALL,
                                      deliverer=SOME_DELIVERER,
                                      embedded_with=SOME_EMBEDDING_MODEL)) \
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
            calling(lambda: record_delivered(records, SOME_INCIDENT, version=2,
                                             embedded_with=SOME_EMBEDDING_MODEL)),
            calling(lambda: record_delivered(records, SOME_INCIDENT, version=1,
                                             embedded_with=SOME_EMBEDDING_MODEL))
        ) \
        .when(lambda: get_undelivered(records, ENOUGH_ROOM_FOR_THEM_ALL,
                                      deliverer=SOME_DELIVERER,
                                      embedded_with=SOME_EMBEDDING_MODEL)) \
        .then(_nothing_waits())


@pytest.mark.component
def test_a_record_another_embedding_model_holds_waits_for_this_ones(
    records: psycopg.Connection
) -> None:
    # Each model is a collection of its own, so a deployment that switched
    # models finds every record waiting for the new collection - where one mark
    # for both would read the empty collection as holding everything.
    the_record = _a_record_trying("new-checkout-flow", Verdict.REFUTED)

    Scenario() \
        .given(
            calling(lambda: an_incident_on_record(records, SOME_INCIDENT)),
            calling(lambda: file(records, the_record)),
            calling(lambda: record_delivered(records, SOME_INCIDENT, version=1,
                                             embedded_with=ANOTHER_EMBEDDING_MODEL))
        ) \
        .when(lambda: get_undelivered(records, ENOUGH_ROOM_FOR_THEM_ALL,
                                      deliverer=SOME_DELIVERER,
                                      embedded_with=SOME_EMBEDDING_MODEL)) \
        .then(_these_wait(the_record, at_version=1))


@pytest.mark.component
def test_a_mark_for_another_embedding_model_moves_this_ones_nowhere(
    records: psycopg.Connection
) -> None:
    # Two deliverers on two models, as an upgrade runs them: the other one
    # marking the older version it took leaves this one's mark where it was,
    # so this collection is not handed the newer record again.
    Scenario() \
        .given(
            calling(lambda: an_incident_on_record(records, SOME_INCIDENT)),
            calling(lambda: file(records, _a_record_trying("new-checkout-flow",
                                                           Verdict.REFUTED))),
            calling(lambda: file(records, _a_record_trying("new-checkout-flow",
                                                           Verdict.CONFIRMED))),
            calling(lambda: record_delivered(records, SOME_INCIDENT, version=2,
                                             embedded_with=SOME_EMBEDDING_MODEL)),
            calling(lambda: record_delivered(records, SOME_INCIDENT, version=1,
                                             embedded_with=ANOTHER_EMBEDDING_MODEL))
        ) \
        .when(lambda: get_undelivered(records, ENOUGH_ROOM_FOR_THEM_ALL,
                                      deliverer=SOME_DELIVERER,
                                      embedded_with=SOME_EMBEDDING_MODEL)) \
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
        .when(lambda: get_undelivered(records, room_for_one,
                                      deliverer=SOME_DELIVERER,
                                      embedded_with=SOME_EMBEDDING_MODEL)) \
        .then(_these_wait(a_remembered_incident(filed_first), at_version=1))


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
            _nothing_is_waiting_in(records)
        ))


@pytest.mark.component
def test_a_record_filed_again_in_another_shape_is_a_new_version(
    records: psycopg.Connection
) -> None:
    # Its JSON matches, and the shape it is written in does not: kept as it
    # was, the row would hold this release's record under a newer release's
    # shape. Delivered again for it, which costs one embedding.
    the_record = _a_record_trying("new-checkout-flow", Verdict.REFUTED)

    Scenario() \
        .given(
            calling(lambda: an_incident_on_record(records, SOME_INCIDENT)),
            calling(lambda: file(records, the_record)),
            calling(lambda: record_delivered(records, SOME_INCIDENT, version=1,
                                             embedded_with=SOME_EMBEDDING_MODEL)),
            calling(lambda: filed_by_a_newer_release(records, SOME_INCIDENT)),
            calling(lambda: file(records, the_record))
        ) \
        .when(lambda: get_undelivered(records, ENOUGH_ROOM_FOR_THEM_ALL,
                                      deliverer=SOME_DELIVERER,
                                      embedded_with=SOME_EMBEDDING_MODEL)) \
        .then(_these_wait(the_record, at_version=2))


@pytest.mark.component
def test_a_record_a_newer_release_filed_waits_for_a_deliverer_that_knows_it(
    records: psycopg.Connection
) -> None:
    # Neither handed over nor parked: read as the shape this release knows, it
    # would be read wrong, and the deliverer of the release that wrote it will
    # deliver it.
    Scenario() \
        .given(
            calling(lambda: an_incident_on_record(records, SOME_INCIDENT)),
            calling(lambda: file(records, a_remembered_incident(SOME_INCIDENT))),
            calling(lambda: filed_by_a_newer_release(records, SOME_INCIDENT))
        ) \
        .when(lambda: get_undelivered(records, ENOUGH_ROOM_FOR_THEM_ALL,
                                      deliverer=SOME_DELIVERER,
                                      embedded_with=SOME_EMBEDDING_MODEL)) \
        .then(_nothing_waits())


@pytest.mark.component
def test_a_record_in_an_older_shape_is_brought_up_before_it_is_handed_over(
    records: psycopg.Connection
) -> None:
    # Read with the shapes of a release one step on: the row is at the shape
    # this release writes, which that release reads as one step behind.
    the_record = a_remembered_incident(SOME_INCIDENT)
    one_step_on = Shapes(upcasters={REMEMBERED_INCIDENT: [_a_step_writing_the_description]})

    Scenario() \
        .given(
            calling(lambda: an_incident_on_record(records, SOME_INCIDENT)),
            calling(lambda: file(records, the_record))
        ) \
        .when(lambda: get_undelivered(records, ENOUGH_ROOM_FOR_THEM_ALL,
                                      deliverer=SOME_DELIVERER,
                                      embedded_with=SOME_EMBEDDING_MODEL,
                                      shapes=one_step_on)) \
        .then(_these_wait(
            the_record.model_copy(update={"described_as": A_DESCRIPTION_A_STEP_WROTE}),
            at_version=1
        ))


@pytest.mark.component
def test_a_record_that_cannot_be_read_is_handed_over_as_what_stopped_it(
    records: psycopg.Connection
) -> None:
    # In its place rather than raised: raised, it would fail every pass that
    # reached it, and every record behind it would wait for good.
    Scenario() \
        .given(
            calling(lambda: an_incident_on_record(records, SOME_INCIDENT)),
            calling(lambda: file(records, a_remembered_incident(SOME_INCIDENT))),
            calling(lambda: filed_unreadable(records, SOME_INCIDENT))
        ) \
        .when(lambda: get_undelivered(records, ENOUGH_ROOM_FOR_THEM_ALL,
                                      deliverer=SOME_DELIVERER,
                                      embedded_with=SOME_EMBEDDING_MODEL)) \
        .then(_it_could_not_be_read(SOME_INCIDENT))


@pytest.mark.component
def test_a_record_this_deliverer_parked_waits_no_longer_for_it(
    records: psycopg.Connection
) -> None:
    Scenario() \
        .given(
            calling(lambda: an_incident_on_record(records, SOME_INCIDENT)),
            calling(lambda: file(records, a_remembered_incident(SOME_INCIDENT))),
            calling(lambda: park(records, SOME_INCIDENT, SOME_DELIVERER))
        ) \
        .when(lambda: get_undelivered(records, ENOUGH_ROOM_FOR_THEM_ALL,
                                      deliverer=SOME_DELIVERER,
                                      embedded_with=SOME_EMBEDDING_MODEL)) \
        .then(_nothing_waits())


@pytest.mark.component
def test_a_record_another_deliverer_parked_waits_for_this_one(
    records: psycopg.Connection
) -> None:
    # Every release starts a deliverer of its own, and the one that holds the
    # step a parked record needed delivers it - with nothing to put the parks
    # back as it starts.
    the_record = a_remembered_incident(SOME_INCIDENT)

    Scenario() \
        .given(
            calling(lambda: an_incident_on_record(records, SOME_INCIDENT)),
            calling(lambda: file(records, the_record)),
            calling(lambda: park(records, SOME_INCIDENT, ANOTHER_DELIVERER))
        ) \
        .when(lambda: get_undelivered(records, ENOUGH_ROOM_FOR_THEM_ALL,
                                      deliverer=SOME_DELIVERER,
                                      embedded_with=SOME_EMBEDDING_MODEL)) \
        .then(_these_wait(the_record, at_version=1))


@pytest.mark.component
def test_a_parked_record_filed_again_waits_again(records: psycopg.Connection) -> None:
    # The record parked is not the record there now, so the deliverer that
    # parked it tries it again.
    what_it_says_now = _a_record_trying("new-checkout-flow", Verdict.CONFIRMED)

    Scenario() \
        .given(
            calling(lambda: an_incident_on_record(records, SOME_INCIDENT)),
            calling(lambda: file(records, _a_record_trying("new-checkout-flow",
                                                           Verdict.REFUTED))),
            calling(lambda: park(records, SOME_INCIDENT, SOME_DELIVERER)),
            calling(lambda: file(records, what_it_says_now))
        ) \
        .when(lambda: get_undelivered(records, ENOUGH_ROOM_FOR_THEM_ALL,
                                      deliverer=SOME_DELIVERER,
                                      embedded_with=SOME_EMBEDDING_MODEL)) \
        .then(_these_wait(what_it_says_now, at_version=2))


def _a_record_trying(subject: str, verdict: Verdict) -> RememberedIncident:
    return a_remembered_incident(SOME_INCIDENT, tried=[(an_identity(subject), verdict)])


def _a_step_writing_the_description(raw: dict[str, Any]) -> dict[str, Any]:
    return {**raw, "described_as": A_DESCRIPTION_A_STEP_WROTE}


def _these_wait(record: RememberedIncident, at_version: int) -> Assertion[_Waiting]:
    return all_of(
        _this_many_wait(1),
        _the_record_waiting_is(record),
        _the_version_waiting_is(at_version)
    )


def _the_filed(waiting: _Waiting) -> list[Filed]:
    unreadable = [one for one in waiting if isinstance(one, UnreadableRecord)]
    if unreadable:
        raise AssertionError(f"Expected every record waiting to be read, these were not: "
                             f"{unreadable}.")

    return [one for one in waiting if isinstance(one, Filed)]


def _this_many_wait(expected: int) -> Assertion[_Waiting]:
    def assertion(waiting: _Waiting) -> bool:
        filed = _the_filed(waiting)
        if len(filed) != expected:
            raise AssertionError(
                f"Expected [{expected}] record(s) waiting to be delivered, got "
                f"{[one.record.incident_id for one in filed]}."
            )

        return True

    return assertion


def _the_record_waiting_is(record: RememberedIncident) -> Assertion[_Waiting]:
    def assertion(waiting: _Waiting) -> bool:
        filed = _the_filed(waiting)
        if not filed or filed[0].record != record:
            raise AssertionError(
                f"Expected [{record}] waiting, got {[one.record for one in filed]}."
            )

        return True

    return assertion


def _it_could_not_be_read(incident_id: str) -> Assertion[_Waiting]:
    def assertion(waiting: _Waiting) -> bool:
        held = [one.incident_id if isinstance(one, UnreadableRecord) else one
                for one in waiting]
        if held != [incident_id]:
            raise AssertionError(
                f"Expected only [{incident_id}]'s record, as one that cannot be read, got "
                f"{held}."
            )

        return True

    return assertion


def _the_version_waiting_is(version: int) -> Assertion[_Waiting]:
    def assertion(waiting: _Waiting) -> bool:
        filed = _the_filed(waiting)
        if not filed or filed[0].version != version:
            raise AssertionError(
                f"Expected version [{version}] waiting, got "
                f"{[one.version for one in filed]}."
            )

        return True

    return assertion


def _nothing_is_waiting_in(records: psycopg.Connection) -> Assertion[object]:
    """Nothing waiting, read from the database rather than from what the case
    returned - which, for a filing refused, is the refusal."""
    def assertion(dont_care_result: object) -> bool:
        return _nothing_waits()(
            get_undelivered(records, ENOUGH_ROOM_FOR_THEM_ALL,
                            deliverer=SOME_DELIVERER,
                            embedded_with=SOME_EMBEDDING_MODEL)
        )

    return assertion


def _nothing_waits() -> Assertion[_Waiting]:
    def assertion(waiting: _Waiting) -> bool:
        if waiting:
            raise AssertionError(f"Expected nothing waiting to be delivered, got {waiting}.")

        return True

    return assertion


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
