"""The account of an incident, written down and read back.

This is the only writer the event stream has, and it writes nothing else. What
it stores has to come back as what went in - the same type, the same payload,
in the same order - because the narration is not re-derivable from anything
else: if a line is lost here it is lost.

It is read two ways. A page asks for one incident's account whole; a relay asks
what has been published since it last looked, across every incident at once,
and carries the place it got to so that a restart resumes rather than repeats.
"""

from __future__ import annotations

from contextlib import ExitStack
from datetime import timedelta
from typing import Any

import psycopg
import pytest
from argus_testkit import Assertion, Scenario, all_of, calling
from core import Fence, utc_now
from core.events import (
    AgentInvoked,
    IncidentEvent,
    LogsRetrieved,
    OnsetDetected,
    RetrievalRequested,
    UnreadableEvent,
)
from core.models import Actor, Alert, RetrievalChannel
from core.stored import SHIPPED, Shapes
from incident_record.repository import events, incidents, runs
from postgres import connect_from_env

from incident_record_test.framework import autocommitting, no_column_is_empty

# Bigger than anything published in these tests. What is under test where this
# appears is which events come back, not how many of them fit in one batch.
A_GENEROUS_BATCH = 100

# Who holds a run, and for how long: a claim is needed for a run to be held for
# a change, and nothing here reads who made it or until when.
DONT_CARE_WORKER = "worker-walking-it"
DONT_CARE_LEASE = timedelta(minutes=5)

# How a batch's entry that could not be read is listed among the kinds of the
# ones that could: one nobody can read, and one a newer release wrote.
CANNOT_BE_READ = "<cannot be read>"
NEWER = "<newer>"

SOME_LOG_LINE = "some log line"
# What a step from an event's shape to the next one adds, where no release has
# shipped a step: a line no event here is published with, so an event carrying
# it was brought up through the step and not read as it was stored.
A_LINE_A_STEP_WROTE = "written by the step to the next shape"
# A kind of event no release of this one publishes.
SOME_KIND_YET_TO_COME = "some-kind-of-event-yet-to-come"


@pytest.mark.integration
def test_a_recorded_event_comes_back_as_the_kind_it_was_published_as() -> None:
    # A reader holding a dictionary has to match on strings to work out what it
    # is looking at, which is the reader doing the discriminating that the
    # publisher already did.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        Scenario() \
            .given(
                incident_id := incidents.create(conn, some_alert, at=utc_now()),
                calling(lambda: _record(
                    conn,
                    OnsetDetected(incident_id=incident_id,
                                  onset="2026-08-30T10:03:00Z")
                ))
            ) \
            .when(lambda: events.get_by_incident(conn, incident_id)) \
            .then(all_of(
                _they_came_back_as(["OnsetDetected"]),
                _the_onset_placed_at("2026-08-30T10:03:00Z")
            ))


@pytest.mark.integration
def test_events_come_back_in_the_order_they_were_published() -> None:
    # The narration is a sequence, and out of order it describes a different
    # investigation - one that read the logs before deciding where to look.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        Scenario() \
            .given(
                incident_id := incidents.create(conn, some_alert, at=utc_now()),
                calling(lambda: _record(conn,
                                        *_an_investigation_in_three_steps(incident_id)))
            ) \
            .when(lambda: events.get_by_incident(conn, incident_id)) \
            .then(_the_account_reads(["agent-invoked",
                                      "retrieval-requested",
                                      "logs-retrieved"]))


@pytest.mark.integration
def test_a_payload_comes_back_whole() -> None:
    # The reason the payload is stored at all: the page shows what Argus read,
    # and a line dropped on the way in is a line nobody can ever show.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")
    the_lines_it_read = [
        "2026-08-30T10:03:00Z ERROR io-shop: division by zero",
        "2026-08-30T10:03:00Z WARN io-shop: retrying"
    ]

    with connect_from_env() as conn:
        Scenario() \
            .given(
                incident_id := incidents.create(conn, some_alert, at=utc_now()),
                calling(lambda: _record(conn, LogsRetrieved(
                    incident_id=incident_id,
                    window_start="2026-08-30T10:02:00Z",
                    window_end="2026-08-30T10:12:00Z",
                    lines=the_lines_it_read
                )))
            ) \
            .when(lambda: events.get_by_incident(conn, incident_id)) \
            .then(all_of(
                _they_came_back_as(["LogsRetrieved"]),
                _the_lines_read_back_are(the_lines_it_read)
            ))


@pytest.mark.integration
def test_an_incident_that_published_nothing_reads_as_empty() -> None:
    # An incident whose components never published is a real incident with no
    # story, which is not an error and not a missing incident.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        Scenario() \
            .given(
                incident_id := incidents.create(conn, some_alert, at=utc_now())
            ) \
            .when(lambda: events.get_by_incident(conn, incident_id)) \
            .then(_the_account_reads([]))


@pytest.mark.integration
def test_only_one_incident_s_events_come_back() -> None:
    # Two incidents can run against one database, and a narration that mixed
    # them would read as one investigation contradicting itself.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        Scenario() \
            .given(
                incident_id := incidents.create(conn, some_alert, at=utc_now()),
                another_incident_id := incidents.create(conn, some_alert, at=utc_now()),
                calling(lambda: _record(
                    conn,
                    AgentInvoked(incident_id=incident_id, agent=Actor.INVESTIGATOR),
                    AgentInvoked(incident_id=another_incident_id,
                                 agent=Actor.MITIGATION)
                ))
            ) \
            .when(lambda: events.get_by_incident(conn, incident_id)) \
            .then(_they_all_belong_to(incident_id))


@pytest.mark.integration
def test_recording_an_event_writes_nothing_else() -> None:
    # The single-writer rule (spec §7.1) survives this table's arrival: the
    # subscriber writes events, and the incident's own state keeps the one
    # writer it already had.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        Scenario() \
            .given(
                incident_id := incidents.create(conn, some_alert, at=utc_now()),
                before := _row_counts(conn)
            ) \
            .when(lambda: events.record(
                conn,
                AgentInvoked(incident_id=incident_id, agent=Actor.INVESTIGATOR)
            )) \
            .then(_no_other_table_was_written(conn, before))


@pytest.mark.integration
def test_only_what_was_published_after_the_cursor_comes_back() -> None:
    # What makes a relay a relay: it asks what has happened since it last
    # looked. An event it has already delivered coming back again is a line a
    # human reads twice.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert, at=utc_now())
        _record(conn, AgentInvoked(incident_id=incident_id,
                                   agent=Actor.INVESTIGATOR))

        Scenario() \
            .given(
                already_delivered := _the_end_of_the_log(conn),
                calling(lambda: _record(
                    conn,
                    OnsetDetected(incident_id=incident_id,
                                  onset="2026-08-30T10:03:00Z")
                ))
            ) \
            .when(lambda: events.get_since(conn, already_delivered, A_GENEROUS_BATCH)) \
            .then(_the_batch_reads(["onset-detected"]))


@pytest.mark.integration
def test_every_incident_s_events_come_back_in_the_one_order_they_happened() -> None:
    # Where `get_by_incident` answers a page about one incident, this answers a
    # relay about the whole log. Two incidents running at once are delivered
    # interleaved as they were published, because that is the order they
    # happened in and nothing downstream can reconstruct it.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert, at=utc_now())
        another_incident_id = incidents.create(conn, some_alert, at=utc_now())

        Scenario() \
            .given(
                the_start_of_the_log := _the_end_of_the_log(conn),
                calling(lambda: _record(
                    conn,
                    AgentInvoked(incident_id=incident_id, agent=Actor.INVESTIGATOR),
                    AgentInvoked(incident_id=another_incident_id,
                                 agent=Actor.MITIGATION),
                    OnsetDetected(incident_id=incident_id,
                                  onset="2026-08-30T10:03:00Z")
                ))
            ) \
            .when(lambda: events.get_since(conn,
                                           the_start_of_the_log,
                                           A_GENEROUS_BATCH)) \
            .then(_the_batch_belongs_to([incident_id,
                                         another_incident_id,
                                         incident_id]))


@pytest.mark.integration
def test_an_event_comes_back_with_the_place_in_the_log_it_was_written_at() -> None:
    # The cursor a relay keeps is the place of the last event it delivered, so
    # reading on from that place has to return what follows it and never it
    # again. Without the place on the event there is nothing to keep.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert, at=utc_now())

        Scenario() \
            .given(
                the_start_of_the_log := _the_end_of_the_log(conn),
                calling(lambda: _record(conn,
                                        *_an_investigation_in_three_steps(incident_id)))
            ) \
            .when(lambda: events.get_since(conn,
                                           the_start_of_the_log,
                                           A_GENEROUS_BATCH)) \
            .then(all_of(
                _their_places_climb(),
                _reading_on_from_each_place_returns_what_follows(conn)
            ))


@pytest.mark.integration
def test_a_batch_stops_at_the_limit_it_was_given_and_starts_at_the_oldest() -> None:
    # A relay that was down for an hour must not read an hour of events into
    # memory to catch up. It reads a batch at a time, and the batch starts at
    # the oldest thing it has not delivered - the other end would deliver the
    # newest line first and lose the ones behind it.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")
    room_for_two = 2

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert, at=utc_now())

        Scenario() \
            .given(
                the_start_of_the_log := _the_end_of_the_log(conn),
                calling(lambda: _record(conn,
                                        *_an_investigation_in_three_steps(incident_id)))
            ) \
            .when(lambda: events.get_since(conn, the_start_of_the_log, room_for_two)) \
            .then(_the_batch_reads(["agent-invoked", "retrieval-requested"]))


@pytest.mark.integration
def test_a_cursor_at_the_end_of_the_log_reads_as_empty() -> None:
    # The state a relay is in almost all the time: caught up, with nothing new
    # to say. Nothing is not an error and not a reason to start again from the
    # beginning.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert, at=utc_now())
        _record(conn, AgentInvoked(incident_id=incident_id,
                                   agent=Actor.INVESTIGATOR))

        Scenario() \
            .given(
                caught_up := _the_end_of_the_log(conn)
            ) \
            .when(lambda: events.get_since(conn, caught_up, A_GENEROUS_BATCH)) \
            .then(_the_batch_reads([]))


@pytest.mark.integration
def test_an_event_still_being_written_holds_back_the_ones_behind_it() -> None:
    # `seq` is handed out when a row is inserted and the row becomes visible
    # when its transaction commits, and those are not the same moment. A walk
    # publishing inside its decision's transaction can hold the earlier place
    # while the intake endpoint commits a later one on its own connection - and
    # a reader that delivered the later event would move its cursor past a line
    # that nobody ever sees.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn, connect_from_env() as an_unfinished_walk:
        incident_id = incidents.create(conn, some_alert, at=utc_now())
        conn.commit()

        Scenario() \
            .given(
                the_start_of_the_log := _the_end_of_the_log(conn),
                calling(lambda: events.record(
                    an_unfinished_walk,
                    AgentInvoked(incident_id=incident_id, agent=Actor.INVESTIGATOR)
                )),
                calling(lambda: _record(
                    conn,
                    OnsetDetected(incident_id=incident_id,
                                  onset="2026-08-30T10:03:00Z")
                ))
            ) \
            .when(lambda: events.get_since(conn,
                                           the_start_of_the_log,
                                           A_GENEROUS_BATCH)) \
            .then(_the_batch_reads([]))


@pytest.mark.integration
def test_a_held_back_event_is_delivered_once_its_transaction_lands() -> None:
    # Held back, not dropped. The reader waits for the walk to commit and then
    # delivers both in the order they were published - which is the order the
    # places were handed out, not the order the transactions finished.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn, connect_from_env() as an_unfinished_walk:
        incident_id = incidents.create(conn, some_alert, at=utc_now())
        conn.commit()

        Scenario() \
            .given(
                the_start_of_the_log := _the_end_of_the_log(conn),
                calling(lambda: events.record(
                    an_unfinished_walk,
                    AgentInvoked(incident_id=incident_id, agent=Actor.INVESTIGATOR)
                )),
                calling(lambda: _record(
                    conn,
                    OnsetDetected(incident_id=incident_id,
                                  onset="2026-08-30T10:03:00Z")
                )),
                calling(an_unfinished_walk.commit)
            ) \
            .when(lambda: events.get_since(conn,
                                           the_start_of_the_log,
                                           A_GENEROUS_BATCH)) \
            .then(_the_batch_reads(["agent-invoked", "onset-detected"]))


@pytest.mark.integration
def test_an_event_published_while_a_run_is_held_for_a_change_is_not_held_back() -> None:
    # The write tier holds a run for as long as its change takes, and a restart
    # takes minutes. Were the hold a transaction, it would be the oldest one in
    # flight for all that time, and every incident's account would stop at it
    # until the change was done. So the hold is no transaction, and what lands
    # meanwhile is delivered.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with (
        connect_from_env() as conn,
        autocommitting(connect_from_env()) as the_tiers_conn,
        ExitStack() as the_change
    ):
        Scenario() \
            .given(
                incident_id := incidents.create(conn, some_alert, at=utc_now()),
                held := _a_claim_on_a_run_for(conn, incident_id),
                the_start_of_the_log := _the_end_of_the_log(conn),
                still_held := the_change.enter_context(
                    runs.hold_for_a_change(the_tiers_conn, held)
                ),
                some_event := AgentInvoked(incident_id=incident_id, agent=Actor.MITIGATION),
                calling(lambda: _record(conn, some_event))
            ) \
            .when(lambda: events.get_since(conn,
                                           the_start_of_the_log,
                                           A_GENEROUS_BATCH)) \
            .then(all_of(
                _the_run_was_held_for_the_change(still_held),
                _the_batch_reads([some_event.kind])
            ))


@pytest.mark.integration
def test_a_recorded_event_leaves_no_column_of_its_row_empty() -> None:
    # `payload` is the record and the columns beside it are what the table is
    # read by - which means an empty one is not a missing detail but a line of
    # the account that no reader's query will reach.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert, at=utc_now())

        Scenario() \
            .when(
                lambda: events.record(conn, AgentInvoked(
                    incident_id=incident_id, agent=Actor.INVESTIGATOR
                ))
            ) \
            .then(
                no_column_is_empty(conn, "incident_event", "incident_id", incident_id)
            )


@pytest.mark.integration
def test_an_event_that_cannot_be_read_comes_back_in_its_place_as_what_stopped_it() -> None:
    # Raised instead, one bad row would fail every batch that reached it, and
    # the relay would say nothing more about any incident for good.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert, at=utc_now())
        the_start = _the_end_of_the_log(conn)
        first, middle, last = _an_investigation_in_three_steps(incident_id)

        Scenario() \
            .given(
                calling(lambda: _record(conn, first, middle, last)),
                calling(lambda: _rewritten(conn, middle, "payload = '{}'"))
            ) \
            .when(lambda: events.get_since(conn, the_start, A_GENEROUS_BATCH)) \
            .then(_the_batch_holds([first.kind, CANNOT_BE_READ, last.kind]))


@pytest.mark.integration
def test_an_event_a_newer_release_wrote_comes_back_in_its_place_as_newer() -> None:
    # Told apart from one nobody can read, because a reader waits for it: the
    # release that knows its shape will read it.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert, at=utc_now())
        the_start = _the_end_of_the_log(conn)
        first, middle, last = _an_investigation_in_three_steps(incident_id)

        Scenario() \
            .given(
                calling(lambda: _record(conn, first, middle, last)),
                calling(lambda: _rewritten(
                    conn, middle, f"shape = {SHIPPED.current(middle.kind) + 1}"
                ))
            ) \
            .when(lambda: events.get_since(conn, the_start, A_GENEROUS_BATCH)) \
            .then(_the_batch_holds([first.kind, NEWER, last.kind]))


@pytest.mark.integration
def test_an_event_of_a_kind_this_release_does_not_publish_comes_back_as_newer() -> None:
    # A release adding a kind of event is the commonest way one writes what an
    # older reader cannot read.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert, at=utc_now())
        the_start = _the_end_of_the_log(conn)
        first, middle, last = _an_investigation_in_three_steps(incident_id)

        Scenario() \
            .given(
                calling(lambda: _record(conn, first, middle, last)),
                calling(lambda: _rewritten(conn, middle, f"kind = '{SOME_KIND_YET_TO_COME}'"))
            ) \
            .when(lambda: events.get_since(conn, the_start, A_GENEROUS_BATCH)) \
            .then(_the_batch_holds([first.kind, NEWER, last.kind]))


@pytest.mark.integration
def test_an_account_written_in_an_older_shape_is_brought_up_before_it_is_read() -> None:
    # Read with the shapes of a release one step on: the row is at the shape
    # this release writes, which that release reads as one step behind.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert, at=utc_now())
        some_logs = LogsRetrieved(incident_id=incident_id,
                                  window_start="2026-08-30T10:02:00Z",
                                  window_end="2026-08-30T10:12:00Z",
                                  lines=[SOME_LOG_LINE])
        one_step_on = Shapes(upcasters={some_logs.kind: [_a_step_adding_a_line]})

        Scenario() \
            .given(
                calling(lambda: _record(conn, some_logs))
            ) \
            .when(lambda: events.get_by_incident(conn, incident_id, one_step_on)) \
            .then(_the_lines_read_back_are([SOME_LOG_LINE, A_LINE_A_STEP_WROTE]))


def _an_investigation_in_three_steps(incident_id: str) -> list[IncidentEvent]:
    return [
        AgentInvoked(incident_id=incident_id, agent=Actor.INVESTIGATOR),
        RetrievalRequested(
            incident_id=incident_id,
            channel=RetrievalChannel.LOGS,
            window_start="2026-08-30T10:02:00Z",
            window_end="2026-08-30T10:12:00Z"
        ),
        LogsRetrieved(
            incident_id=incident_id,
            window_start="2026-08-30T10:02:00Z",
            window_end="2026-08-30T10:12:00Z",
            lines=["some log line"]
        )
    ]


def _record(conn: psycopg.Connection, *published: IncidentEvent) -> None:
    """Publishes events and lets them land, which is what a publisher does.

    Committed rather than left open, because every real publisher commits: a
    walk with the decision its event is written beside, the intake endpoint on
    its own. A reader following the log sees what has landed, so a test that
    left its setup open would be asking the reader about a world no reader can
    see.
    """
    for event in published:
        events.record(conn, event)

    conn.commit()


def _rewritten(conn: psycopg.Connection, event: IncidentEvent, assignment: str) -> None:
    """The event's row with one column set by hand, and committed - standing in
    for a row an older release, a newer one or a step gone wrong left behind,
    which the repository itself never writes."""
    conn.execute(f"UPDATE incident_event SET {assignment} WHERE id = %s", (event.id,))
    conn.commit()


def _a_step_adding_a_line(raw: dict[str, Any]) -> dict[str, Any]:
    return {**raw, "lines": [*raw["lines"], A_LINE_A_STEP_WROTE]}


def _the_end_of_the_log(conn: psycopg.Connection) -> int:
    """Where the log ends now, asked of the database rather than of the reader.

    In SQL of its own so that a test setting up a cursor does not set it up
    with the function under test: a `get_since` that answered every question
    with the same wrong place would otherwise agree with itself.
    """
    with conn.cursor() as cursor:
        cursor.execute("SELECT coalesce(max(seq), 0) FROM incident_event")
        row = cursor.fetchone()
        assert row is not None

        return int(row[0])


def _a_claim_on_a_run_for(conn: psycopg.Connection, incident_id: str) -> Fence:
    """The claim a worker holds on a run for the incident, as a call to the
    write tier names it - committed, as a worker commits its claim the moment
    it makes it."""
    runs.enqueue(conn, incident_id)
    claimed = runs.claim(conn, DONT_CARE_WORKER, DONT_CARE_LEASE)
    assert claimed is not None
    conn.commit()

    return Fence(run_id=claimed.id, epoch=claimed.epoch)


def _the_run_was_held_for_the_change(still_held: bool) -> Assertion[Any]:
    """The hold was had - without it, nothing was held and an event delivered
    says nothing about a hold."""
    def assertion(_delivered: Any) -> bool:
        if still_held is not True:
            raise AssertionError(
                f"Expected the run held for the change, and the hold said [{still_held}]."
            )

        return True

    return assertion


def _row_counts(conn: psycopg.Connection) -> dict[str, int]:
    counted = {}
    with conn.cursor() as cursor:
        for table in ("incident", "hypothesis", "action"):
            cursor.execute(f"SELECT count(*) FROM {table}")  # the names are fixed above
            row = cursor.fetchone()
            assert row is not None
            counted[table] = row[0]

    return counted


def _they_came_back_as(expected: list[str]) -> Assertion[list[IncidentEvent]]:
    """The types the events were read back as, named as the classes they are.

    By name rather than by `isinstance`, so that a reader is told what came
    back instead of that something did not match - and so that an event read
    back as a plain payload fails here rather than three lines later.
    """
    def assertion(recorded: list[IncidentEvent]) -> bool:
        types = [type(event).__name__ for event in recorded]
        if types != expected:
            raise AssertionError(f"Expected {expected} to come back, got {types}.")

        return True

    return assertion


def _the_onset_placed_at(expected: str) -> Assertion[list[IncidentEvent]]:
    def assertion(recorded: list[IncidentEvent]) -> bool:
        placed = [event.onset for event in recorded if isinstance(event, OnsetDetected)]
        if placed != [expected]:
            raise AssertionError(f"Expected the onset [{expected}], got {placed}.")

        return True

    return assertion


def _the_lines_read_back_are(expected: list[str]) -> Assertion[list[IncidentEvent]]:
    def assertion(recorded: list[IncidentEvent]) -> bool:
        lines = [event.lines for event in recorded if isinstance(event, LogsRetrieved)]
        if lines != [expected]:
            raise AssertionError(f"Expected the lines {expected}, got {lines}.")

        return True

    return assertion


def _the_account_reads(expected: list[str]) -> Assertion[list[IncidentEvent]]:
    def assertion(recorded: list[IncidentEvent]) -> bool:
        kinds = [event.kind for event in recorded]
        if kinds != expected:
            raise AssertionError(f"Expected the kinds {expected}, got {kinds}.")

        return True

    return assertion


def _they_all_belong_to(expected: str) -> Assertion[list[IncidentEvent]]:
    def assertion(recorded: list[IncidentEvent]) -> bool:
        incident_ids = [event.incident_id for event in recorded]
        if incident_ids != [expected]:
            raise AssertionError(
                f"Expected the events of [{expected}] alone, got {incident_ids}."
            )

        return True

    return assertion


def _no_other_table_was_written(conn: psycopg.Connection,
                                before: dict[str, int]) -> Assertion[None]:
    def assertion(_: None) -> bool:
        after = _row_counts(conn)
        if after != before:
            raise AssertionError(
                f"Expected the other tables to be untouched at {before}, got {after}."
            )

        return True

    return assertion


type _Batch = list[events.RecordedEvent | UnreadableEvent]


def _the_batch_reads(expected: list[str]) -> Assertion[_Batch]:
    def assertion(delivered: _Batch) -> bool:
        kinds = [event.kind for event in _the_events_in(delivered)]
        if kinds != expected:
            raise AssertionError(f"Expected the kinds {expected}, got {kinds}.")

        return True

    return assertion


def _the_batch_holds(expected: list[str]) -> Assertion[_Batch]:
    """Each entry's kind, or `CANNOT_BE_READ` or `NEWER` where it could not be
    read, in the order the log holds them."""
    def assertion(delivered: _Batch) -> bool:
        held = [
            (NEWER if entry.unreadable.newer else CANNOT_BE_READ)
            if isinstance(entry, UnreadableEvent) else entry.event.kind
            for entry in delivered
        ]
        if held != expected:
            raise AssertionError(f"Expected the batch to hold {expected}, it held {held}.")

        return True

    return assertion


def _the_events_in(delivered: _Batch) -> list[IncidentEvent]:
    unreadable = [entry for entry in delivered if isinstance(entry, UnreadableEvent)]
    if unreadable:
        raise AssertionError(f"Expected every event to be read, these were not: {unreadable}.")

    return [entry.event for entry in delivered if not isinstance(entry, UnreadableEvent)]


def _the_batch_belongs_to(expected: list[str]) -> Assertion[_Batch]:
    def assertion(delivered: _Batch) -> bool:
        incident_ids = [event.incident_id for event in _the_events_in(delivered)]
        if incident_ids != expected:
            raise AssertionError(
                f"Expected the events of {expected}, in that order, "
                f"got {incident_ids}."
            )

        return True

    return assertion


def _their_places_climb() -> Assertion[_Batch]:
    def assertion(delivered: _Batch) -> bool:
        places = [entry.seq for entry in delivered]
        if places != sorted(set(places)):
            raise AssertionError(
                f"Expected each event to sit after the one before it, got {places}."
            )

        return True

    return assertion


def _reading_on_from_each_place_returns_what_follows(
        conn: psycopg.Connection) -> Assertion[_Batch]:
    def assertion(delivered: _Batch) -> bool:
        for position, entry in enumerate(delivered):
            following = events.get_since(conn, entry.seq, A_GENEROUS_BATCH)
            expected = [each.seq for each in delivered[position + 1:]]
            if [each.seq for each in following] != expected:
                raise AssertionError(
                    f"Reading on from {entry.seq} should have returned "
                    f"{expected}, it returned {[each.seq for each in following]}."
                )

        return True

    return assertion
