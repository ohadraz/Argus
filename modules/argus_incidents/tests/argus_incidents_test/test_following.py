"""A reader's two seams over the event log, against the database they are
seams over.

Every process that follows the log - the relay telling Slack, the intent agent
reading what people wrote - reads it through a backlog and keeps its place in a
row, and neither knows the other exists. So these ask the one question their
callers' unit tests cannot: that what was published really comes back, and
that the place really outlives the process that moved it.
"""

from __future__ import annotations

import psycopg
import pytest
from argus_core import connect_from_env
from argus_core.events import AgentInvoked, IncidentEvent, OnsetDetected, StatusChanged
from argus_core.models import Actor, Alert, IncidentStatus
from argus_incidents.following import events_since, place_for
from argus_incidents.repository import events, incidents
from argus_testkit import Assertion, Scenario, calling

A_READER = "slack"

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
    # decides what "after" means. What this asks is only that a reader is
    # reading the real log rather than an empty one.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)
        the_log = events_since(connect_from_env)

        Scenario() \
            .given(
                calling(lambda: _publish(
                    conn,
                    AgentInvoked(incident_id=incident_id, agent=Actor.INVESTIGATOR),
                    OnsetDetected(incident_id=incident_id, onset="2026-08-30T10:03:00Z"),
                    StatusChanged(incident_id=incident_id, to_status=IncidentStatus.RESOLVED)
                ))
            ) \
            .when(lambda: the_log(THE_BEGINNING, A_GENEROUS_BATCH)) \
            .then(_the_kinds_read_back_were(["agent-invoked",
                                             "onset-detected",
                                             "status-changed"]))


@pytest.mark.component
def test_a_place_moved_on_is_where_the_next_process_starts(
        a_clean_database: None) -> None:
    # The reason the place is a seam over a row rather than an attribute: the
    # reader that reads it next is a different process from the one that moved
    # it, and usually a different machine.
    a_place = place_for(connect_from_env, A_READER)

    Scenario() \
        .given(
            calling(lambda: a_place.move_to(SOME_PLACE))
        ) \
        .when(lambda: place_for(connect_from_env, A_READER).where()) \
        .then(_the_place_is(SOME_PLACE))


def _publish(conn: psycopg.Connection, *published: IncidentEvent) -> None:
    """Publishes events and lets them land, as every real publisher does."""
    for event in published:
        events.record(conn, event)

    conn.commit()


def _the_kinds_read_back_were(expected: list[str]) -> Assertion[list[events.RecordedEvent]]:
    def assertion(read_back: list[events.RecordedEvent]) -> bool:
        kinds = [entry.event.kind for entry in read_back]
        if kinds != expected:
            raise AssertionError(f"Expected the kinds {expected}, got {kinds}.")

        return True

    return assertion


def _the_place_is(expected: int) -> Assertion[int]:
    def assertion(place: int) -> bool:
        if place != expected:
            raise AssertionError(f"Expected the place {expected}, got {place}.")

        return True

    return assertion
