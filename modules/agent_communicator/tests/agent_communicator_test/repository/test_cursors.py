from __future__ import annotations

import psycopg
import pytest
from agent_communicator.repository import cursors
from argus_core.db import connect
from argus_testkit import Assertion, Scenario, all_of, calling

"""Where a reader of the event log got to, kept so that a restart resumes.

A relay delivering an incident's account somewhere else - Slack today, email
later - asks the log what has happened since it last looked. The place it got
to is the whole of its state: lose it and the relay either says everything
again from the beginning of time or, worse, silently starts from now and drops
whatever was published while it was down.

One row per reader rather than one row: two destinations fall behind at
different rates, and a single place would make the slower of them decide what
the faster one has already said.
"""

A_SLACK_RELAY = "slack"
ANOTHER_RELAY = "email"

# A place far enough along the log to be unmistakable in a failure message, and
# meaningless otherwise: what is under test here is what the cursor remembers,
# not what the number means.
SOME_PLACE = 4321
A_LATER_PLACE = 9876


@pytest.mark.integration
def test_a_reader_that_has_never_looked_starts_at_the_beginning_of_the_log(
        a_clean_database: None) -> None:
    # A relay meeting the log for the first time has missed nothing, so it
    # starts where the log does. Answering "nowhere" instead would make every
    # caller decide what nowhere means, and one of them would decide "now" -
    # which silently drops everything published before the relay first ran.
    with connect() as conn:
        Scenario() \
            .given(
                a_reader_that_never_looked := A_SLACK_RELAY
            ) \
            .when(lambda: cursors.get(conn, a_reader_that_never_looked)) \
            .then(_the_place_is(0))


@pytest.mark.integration
def test_where_a_reader_got_to_outlives_the_connection_that_wrote_it(
        a_clean_database: None) -> None:
    # The reason this is a row and not a variable: the relay is restarted,
    # redeployed and killed, and each time it comes back it has to carry on
    # from where it stopped rather than from wherever the log now ends.
    with connect() as conn, connect() as another_connection:
        Scenario() \
            .given(
                calling(lambda: cursors.advance(conn, A_SLACK_RELAY, SOME_PLACE)),
                calling(conn.commit)
            ) \
            .when(lambda: cursors.get(another_connection, A_SLACK_RELAY)) \
            .then(_the_place_is(SOME_PLACE))


@pytest.mark.integration
def test_a_reader_moved_on_twice_is_at_the_place_it_moved_to_last(
        a_clean_database: None) -> None:
    # The ordinary rhythm: deliver a batch, move on, deliver the next. The
    # cursor holds one place - the last one it was moved to - rather than a
    # history of where it has been, because nothing ever asks where it was.
    with connect() as conn:
        Scenario() \
            .given(
                calling(lambda: cursors.advance(conn, A_SLACK_RELAY, SOME_PLACE)),
                calling(lambda: cursors.advance(conn, A_SLACK_RELAY, A_LATER_PLACE))
            ) \
            .when(lambda: cursors.get(conn, A_SLACK_RELAY)) \
            .then(_the_place_is(A_LATER_PLACE))


@pytest.mark.integration
def test_a_cursor_asked_to_move_back_stays_where_it_is(a_clean_database: None) -> None:
    # A batch delivered twice, or two relays of one name running at once, would
    # otherwise wind the place backwards and say an hour of an incident over
    # again. Duplicates are tolerated where they cannot be helped; a cursor
    # that goes backwards is a duplicate this can help.
    with connect() as conn:
        Scenario() \
            .given(
                calling(lambda: cursors.advance(conn, A_SLACK_RELAY, A_LATER_PLACE))
            ) \
            .when(lambda: cursors.advance(conn, A_SLACK_RELAY, SOME_PLACE)) \
            .then(_the_reader_is_still_at(conn, A_SLACK_RELAY, A_LATER_PLACE))


@pytest.mark.integration
def test_two_readers_keep_their_own_places(a_clean_database: None) -> None:
    # Slack and email fall behind at different rates, and one destination being
    # slow must not decide what another has already said.
    with connect() as conn:
        Scenario() \
            .given(
                calling(lambda: cursors.advance(conn, A_SLACK_RELAY, SOME_PLACE)),
                calling(lambda: cursors.advance(conn, ANOTHER_RELAY, A_LATER_PLACE))
            ) \
            .when(lambda: cursors.get(conn, A_SLACK_RELAY)) \
            .then(all_of(
                _the_place_is(SOME_PLACE),
                _the_reader_is_still_at(conn, ANOTHER_RELAY, A_LATER_PLACE)
            ))


def _the_place_is(expected: int) -> Assertion[int]:
    def assertion(place: int) -> bool:
        if place != expected:
            raise AssertionError(f"Expected the place {expected}, got {place}.")

        return True

    return assertion


def _the_reader_is_still_at(conn: psycopg.Connection,
                            reader: str,
                            expected: int) -> Assertion[object]:
    def assertion(_: object) -> bool:
        place = cursors.get(conn, reader)
        if place != expected:
            raise AssertionError(
                f"Expected [{reader}] to be at {expected}, it is at {place}."
            )

        return True

    return assertion
