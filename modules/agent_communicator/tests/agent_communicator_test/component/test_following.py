from __future__ import annotations

import psycopg
import pytest
from agent_communicator.following import events_since, place_for
from agent_communicator.policy import Register
from agent_communicator.relaying import Outcome, relay_once
from argus_core.db import connect
from argus_core.events import (
    ActionTaken,
    IncidentEvent,
    OnsetDetected,
    StatusChanged,
)
from argus_core.models.alert import Alert
from argus_core.models.incident_status import IncidentStatus
from argus_incidents.repository import events, incidents
from argus_narration import NarrationLine
from argus_testkit import Assertion, Scenario, all_of, calling

"""The relay's two seams, against the database they are seams over.

`relaying` decides what gets said and in what order and knows about no database
at all; this is where its log and its place meet postgres. So these tests ask
the one question its unit tests cannot: that what was published really comes
back, and that the place really outlives the process that moved it.

A component test rather than an integration one: what talks to postgres is
`argus_incidents`' repositories, which have integration tests of their own.
This is one module through its own front door with the infrastructure it cannot
fake behind it.

One relay's worth of wiring at a time. A test here that re-asked what the flow
does with what it read would be testing `relaying` through a container.
"""

A_READER = "slack"
ANOTHER_READER = "email"

# Where the log starts, said out loud: a reader that has never looked is at the
# beginning, and these tests read from there rather than from a place they had
# to arrange.
THE_BEGINNING = 0

# Bigger than anything published here - what is under test is the wiring, not
# how much of the log fits in one look.
A_GENEROUS_BATCH = 100

# A place far enough along to be unmistakable in a failure message, and
# meaningless otherwise.
SOME_PLACE = 4321


@pytest.mark.component
def test_the_log_hands_back_what_was_published_after_a_place(
        a_clean_database: None) -> None:
    # The seam is a function over the repository, and the repository is what
    # decides what "after" means. What this asks is only that the relay is
    # reading the real log rather than an empty one.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect() as conn:
        incident_id = incidents.create(conn, some_alert)
        the_log = events_since(connect)

        Scenario() \
            .given(
                calling(lambda: _publish(conn, *_three_steps_of(incident_id)))
            ) \
            .when(lambda: the_log(THE_BEGINNING, A_GENEROUS_BATCH)) \
            .then(_the_kinds_read_back_were(["onset-detected",
                                             "action-taken",
                                             "status-changed"]))


@pytest.mark.component
def test_a_place_moved_on_is_where_the_next_process_starts(
        a_clean_database: None) -> None:
    # The reason the place is a seam over a row rather than an attribute: the
    # relay that reads it next is a different process from the one that moved
    # it, and usually a different machine.
    a_place = place_for(connect, A_READER)

    Scenario() \
        .given(
            calling(lambda: a_place.move_to(SOME_PLACE))
        ) \
        .when(lambda: place_for(connect, A_READER).where()) \
        .then(_the_place_is(SOME_PLACE))


@pytest.mark.component
def test_two_readers_of_one_log_keep_their_own_places(
        a_clean_database: None) -> None:
    # Slack and email fall behind at different rates, and the seam is what
    # keeps them apart: one relay's progress must not tell another relay it has
    # already said something it never said.
    Scenario() \
        .given(
            calling(lambda: place_for(connect, A_READER).move_to(SOME_PLACE))
        ) \
        .when(lambda: place_for(connect, ANOTHER_READER).where()) \
        .then(_the_place_is(THE_BEGINNING))


@pytest.mark.component
def test_a_relay_over_the_real_log_says_what_was_published_and_then_stops(
        a_clean_database: None) -> None:
    # The two seams and the flow together, which is the thing that actually
    # runs: everything published is delivered once, and a second look with
    # nothing new to say says nothing.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect() as conn:
        incident_id = incidents.create(conn, some_alert)
        a_relay = _a_recording_relay()

        Scenario() \
            .given(
                calling(lambda: _publish(conn, *_three_steps_of(incident_id))),
                calling(lambda: relay_once(events_since(connect),
                                           place_for(connect, A_READER),
                                           a_relay))
            ) \
            .when(lambda: relay_once(events_since(connect),
                                     place_for(connect, A_READER),
                                     a_relay)) \
            .then(all_of(
                _it_delivered(0),
                _the_lines_delivered_were(a_relay, ["onset-detected",
                                                    "action-taken",
                                                    "status-changed"])
            ))


class _ARelay:
    """A destination that remembers what it was told."""

    def __init__(self) -> None:
        self.told: list[tuple[str, NarrationLine, Register]] = []

    def __call__(self,
                 incident_id: str,
                 line: NarrationLine,
                 register: Register, /) -> Outcome:
        self.told.append((incident_id, line, register))

        return Outcome.SAID


def _a_recording_relay() -> _ARelay:
    return _ARelay()


def _three_steps_of(incident_id: str) -> list[IncidentEvent]:
    return [
        OnsetDetected(incident_id=incident_id, onset="2026-08-30T10:03:00Z"),
        ActionTaken(
            incident_id=incident_id,
            hypothesis_id=None,
            action_type="revert-feature-flag",
            subject="monthly-spend-feature",
            enabled=False
        ),
        StatusChanged(incident_id=incident_id, to_status=IncidentStatus.RESOLVED)
    ]


def _publish(conn: psycopg.Connection, *published: IncidentEvent) -> None:
    """Publishes events and lets them land, as every real publisher does."""
    for event in published:
        events.record(conn, event)

    conn.commit()


def _the_place_is(expected: int) -> Assertion[int]:
    def assertion(place: int) -> bool:
        if place != expected:
            raise AssertionError(f"Expected the place {expected}, got {place}.")

        return True

    return assertion


def _the_kinds_read_back_were(expected: list[str]) -> Assertion[list[events.RecordedEvent]]:
    def assertion(read_back: list[events.RecordedEvent]) -> bool:
        kinds = [entry.event.kind for entry in read_back]
        if kinds != expected:
            raise AssertionError(f"Expected the kinds {expected}, got {kinds}.")

        return True

    return assertion


def _it_delivered(expected: int) -> Assertion[int]:
    def assertion(delivered: int) -> bool:
        if delivered != expected:
            raise AssertionError(
                f"Expected {expected} lines to be delivered, it reported {delivered}."
            )

        return True

    return assertion


def _the_lines_delivered_were(relay: _ARelay, expected: list[str]) -> Assertion[object]:
    def assertion(_: object) -> bool:
        kinds = [line.kind for _, line, _ in relay.told]
        if kinds != expected:
            raise AssertionError(
                f"Expected these lines to have been delivered in all: "
                f"{expected}, got {kinds}."
            )

        return True

    return assertion
