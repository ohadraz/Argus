from __future__ import annotations

import psycopg
import pytest
from agent_communicator.repository import threads
from argus_core.db import connect
from argus_core.models.alert import Alert
from argus_incidents.repository import incidents
from argus_testkit import Assertion, Scenario, all_of, calling

"""Which conversation an incident is being told in, remembered between passes.

Slack has no thread id: a reply names the timestamp of the message it is
replying to. So the first message an incident gets is its thread, and every
later line has to find that timestamp again - in another pass, another process,
another day.

Here rather than as a column on `incident`, because an incident knows nothing
about Slack and should not learn: a second destination adds a row of its own
shape here, where it would otherwise add a column to the one table every part
of this system reads.

Each test asks for an empty database rather than being handed one. This
module's suite is mostly unit tests that never open a connection, so the
fixture is offered rather than autouse.
"""

A_WAR_ROOM = "C0INCIDENTS"
ANOTHER_CHANNEL = "C0POSTMORTEMS"

# Slack's own shape for a message's identity - seconds and microseconds - kept
# as text because that is what a reply has to send back, to the digit.
THE_FIRST_MESSAGE = "1756554000.001900"
A_LATER_MESSAGE = "1756554321.004200"


@pytest.mark.integration
def test_the_thread_an_incident_was_given_is_the_one_that_comes_back(
        a_clean_database: None) -> None:
    # The whole purpose: a line written twenty minutes later lands in the same
    # conversation as the one that opened the incident.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect() as conn:
        incident_id = incidents.create(conn, some_alert)

        Scenario() \
            .given(
                calling(lambda: threads.remember(conn,
                                                 incident_id,
                                                 A_WAR_ROOM,
                                                 THE_FIRST_MESSAGE))
            ) \
            .when(lambda: threads.get(conn, incident_id, A_WAR_ROOM)) \
            .then(_the_thread_is(THE_FIRST_MESSAGE))


@pytest.mark.integration
def test_an_incident_nobody_has_posted_about_has_no_thread(
        a_clean_database: None) -> None:
    # Not an error, and the ordinary state of every incident until its first
    # message lands: the caller reads this as "open one", and a raised error
    # would make the commonest path the exceptional one.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect() as conn:
        incident_id = incidents.create(conn, some_alert)

        Scenario() \
            .given(
                an_incident_with_nothing_said_about_it := incident_id
            ) \
            .when(lambda: threads.get(conn,
                                      an_incident_with_nothing_said_about_it,
                                      A_WAR_ROOM)) \
            .then(_there_is_no_thread())


@pytest.mark.integration
def test_an_incident_keeps_the_first_thread_it_was_given(
        a_clean_database: None) -> None:
    # Two relays running at once, or a pass repeated after a crash, can each
    # post an opening message. The first one is the conversation people are
    # reading, so a second must not move the incident into a thread nobody is
    # watching - the duplicate message is the cost of at-least-once, and
    # scattering the rest of the incident after it is not.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect() as conn:
        incident_id = incidents.create(conn, some_alert)

        Scenario() \
            .given(
                calling(lambda: threads.remember(conn,
                                                 incident_id,
                                                 A_WAR_ROOM,
                                                 THE_FIRST_MESSAGE))
            ) \
            .when(lambda: threads.remember(conn,
                                           incident_id,
                                           A_WAR_ROOM,
                                           A_LATER_MESSAGE)) \
            .then(_the_thread_on_record_is(conn,
                                           incident_id,
                                           A_WAR_ROOM,
                                           THE_FIRST_MESSAGE))


@pytest.mark.integration
def test_one_incident_in_two_channels_has_a_thread_in_each(
        a_clean_database: None) -> None:
    # The war room and the postmortem channel are two conversations, and the
    # same incident runs in both. A mapping keyed by the channel is what lets a
    # second destination arrive without the incident record changing shape.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect() as conn:
        incident_id = incidents.create(conn, some_alert)

        Scenario() \
            .given(
                calling(lambda: threads.remember(conn,
                                                 incident_id,
                                                 A_WAR_ROOM,
                                                 THE_FIRST_MESSAGE)),
                calling(lambda: threads.remember(conn,
                                                 incident_id,
                                                 ANOTHER_CHANNEL,
                                                 A_LATER_MESSAGE))
            ) \
            .when(lambda: threads.get(conn, incident_id, A_WAR_ROOM)) \
            .then(all_of(
                _the_thread_is(THE_FIRST_MESSAGE),
                _the_thread_on_record_is(conn,
                                         incident_id,
                                         ANOTHER_CHANNEL,
                                         A_LATER_MESSAGE)
            ))


@pytest.mark.integration
def test_two_incidents_in_one_channel_keep_their_own_threads(
        a_clean_database: None) -> None:
    # Two incidents at once is the case a single channel exists to survive:
    # each is its own conversation, and a line that landed in the other one is
    # a line read as being about the wrong failure.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect() as conn:
        incident_id = incidents.create(conn, some_alert)
        another_incident_id = incidents.create(conn, some_alert)

        Scenario() \
            .given(
                calling(lambda: threads.remember(conn,
                                                 incident_id,
                                                 A_WAR_ROOM,
                                                 THE_FIRST_MESSAGE)),
                calling(lambda: threads.remember(conn,
                                                 another_incident_id,
                                                 A_WAR_ROOM,
                                                 A_LATER_MESSAGE))
            ) \
            .when(lambda: threads.get(conn, incident_id, A_WAR_ROOM)) \
            .then(_the_thread_is(THE_FIRST_MESSAGE))


def _the_thread_is(expected: str) -> Assertion[str | None]:
    def assertion(thread: str | None) -> bool:
        if thread != expected:
            raise AssertionError(f"Expected the thread [{expected}], got [{thread}].")

        return True

    return assertion


def _there_is_no_thread() -> Assertion[str | None]:
    def assertion(thread: str | None) -> bool:
        if thread is not None:
            raise AssertionError(f"Expected no thread, got [{thread}].")

        return True

    return assertion


def _the_thread_on_record_is(conn: psycopg.Connection,
                             incident_id: str,
                             channel: str,
                             expected: str) -> Assertion[object]:
    def assertion(_: object) -> bool:
        on_record = threads.get(conn, incident_id, channel)
        if on_record != expected:
            raise AssertionError(
                f"Expected [{incident_id}] in [{channel}] to be in thread "
                f"[{expected}], it is in [{on_record}]."
            )

        return True

    return assertion
