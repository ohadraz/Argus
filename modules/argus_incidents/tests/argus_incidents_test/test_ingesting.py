"""The door a person's words about an incident come in through.

Beside the resolution and shaped like it, for the same reason: `argus_web`
calls it, and anything `argus_web` can import must reach nothing that walks a
graph. It ingests and decides nothing - what the words meant is classified
later, by the intent agent.

What it owes its callers is that a message is ingested once. The chat platform
retries a delivery it believes went unanswered, and a message ingested twice is
classified twice and offered back to its writer twice. So the message and the
account of its arrival are one write: recorded together, or neither.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import Mock, create_autospec

import psycopg
import pytest
from argus_core import connect_from_env
from argus_core.events import PersonWrote
from argus_core.models import Alert, ReportChannel, ThreadMessage, a_chat_message
from argus_incidents.ingesting import ingest_a_message
from argus_incidents.repository import conversation, events, incidents
from argus_testkit import Assertion, Scenario, all_of, attempting, calling

SOME_MESSAGE = a_chat_message(ReportChannel.SLACK, "C-some-channel", "1760000100.000200")
SOME_PERSON = "U-some-person"
SOME_WORDS = "rolled the flag back by hand, we're fine"
SOME_TIME = datetime(2026, 10, 11, 1, 0, tzinfo=UTC)


@pytest.mark.component
def test_a_message_ingested_is_recorded_on_the_incident_with_who_and_what(
        a_clean_database: None) -> None:
    incident_id = _an_incident()

    Scenario() \
        .when(lambda: ingest_a_message(incident_id, SOME_MESSAGE, SOME_PERSON, SOME_WORDS,
                                       connect_from_env)) \
        .then(all_of(
            _it_reports(True),
            _the_incident_ingested(incident_id, [(SOME_PERSON, SOME_WORDS)])
        ))


@pytest.mark.component
def test_a_message_ingested_is_kept_in_the_incidents_record_as_written_and_when(
        a_clean_database: None) -> None:
    # The record is what decides on the message - the wait counts a person's
    # five minutes from when it was written - so it is kept there, on the
    # stack's clock, and not only told of.
    incident_id = _an_incident()

    Scenario() \
        .when(lambda: ingest_a_message(incident_id, SOME_MESSAGE, SOME_PERSON, SOME_WORDS,
                                       connect_from_env, now=lambda: SOME_TIME)) \
        .then(_the_record_holds(ThreadMessage(incident_id=incident_id,
                                              message=SOME_MESSAGE,
                                              person_id=SOME_PERSON,
                                              text=SOME_WORDS,
                                              written_at=SOME_TIME)))


@pytest.mark.component
def test_the_account_of_a_message_is_dated_when_the_message_was_written(
        a_clean_database: None) -> None:
    # One moment, kept twice: the wait counts from the record's, and the
    # timeline tells it from the account's. Two readings of the clock would
    # put a person's words on the timeline at a time the wait never counted.
    incident_id = _an_incident()

    Scenario() \
        .when(lambda: ingest_a_message(incident_id, SOME_MESSAGE, SOME_PERSON, SOME_WORDS,
                                       connect_from_env, now=lambda: SOME_TIME)) \
        .then(_the_account_is_dated(incident_id, SOME_TIME))


@pytest.mark.component
def test_a_message_ingested_again_is_recorded_once(a_clean_database: None) -> None:
    incident_id = _an_incident()

    Scenario() \
        .given(calling(lambda: ingest_a_message(incident_id, SOME_MESSAGE, SOME_PERSON,
                                                SOME_WORDS, connect_from_env))) \
        .when(lambda: ingest_a_message(incident_id, SOME_MESSAGE, SOME_PERSON, SOME_WORDS,
                                       connect_from_env)) \
        .then(all_of(
            _it_reports(False),
            _the_incident_ingested(incident_id, [(SOME_PERSON, SOME_WORDS)])
        ))


@pytest.mark.component
def test_a_message_whose_arrival_could_not_be_recorded_can_be_ingested_again(
        a_clean_database: None) -> None:
    # Recorded together, or neither. The message is written first and the
    # account of its arrival after it, so it is the account failing that would
    # leave a message kept and never told of - and the platform's retry
    # finding it taken, with the person's words lost for good.
    incident_id = _an_incident()
    an_event_log_that_refuses = create_autospec(
        events.record, side_effect=psycopg.OperationalError("the event log refused it")
    )

    Scenario() \
        .given(calling(attempting(lambda: ingest_a_message(
            incident_id, SOME_MESSAGE, SOME_PERSON, SOME_WORDS, connect_from_env,
            record_event=an_event_log_that_refuses
        )))) \
        .when(lambda: ingest_a_message(incident_id, SOME_MESSAGE, SOME_PERSON, SOME_WORDS,
                                       connect_from_env)) \
        .then(all_of(
            _the_failed_attempt_reached_the_event_log(an_event_log_that_refuses),
            _it_reports(True),
            _the_incident_ingested(incident_id, [(SOME_PERSON, SOME_WORDS)])
        ))


def _the_failed_attempt_reached_the_event_log(event_log: Mock) -> Assertion[bool]:
    """That the first attempt failed where it was meant to - after the message
    was written - rather than before writing anything, which proves nothing."""
    def assertion(_ingested: bool) -> bool:
        if event_log.call_count != 1:
            raise AssertionError(
                f"Expected the failed attempt to reach the event log once, and it was "
                f"reached {event_log.call_count} times."
            )

        return True

    return assertion


def _an_incident() -> str:
    with connect_from_env() as conn:
        return incidents.create(conn, Alert(service="kuki-service", alert_name="HighErrorRate"))


def _it_reports(expected: bool) -> Assertion[bool]:
    def assertion(ingested: bool) -> bool:
        if ingested != expected:
            raise AssertionError(
                f"Expected ingesting to report that the message was "
                f"{"new" if expected else "ingested before"}, got [{ingested!r}]."
            )

        return True

    return assertion


def _the_incident_ingested(incident_id: str,
                           expected: list[tuple[str, str]]) -> Assertion[bool]:
    def assertion(_ingested: bool) -> bool:
        with connect_from_env() as conn:
            recorded = events.get_by_incident(conn, incident_id)

        ingested = [(event.person_id, event.text) for event in recorded
                    if isinstance(event, PersonWrote) and event.message == SOME_MESSAGE]

        if ingested != expected:
            raise AssertionError(
                f"Expected the incident to have ingested {expected}, got {ingested}."
            )

        return True

    return assertion


def _the_account_is_dated(incident_id: str, expected: datetime) -> Assertion[bool]:
    def assertion(_ingested: bool) -> bool:
        with connect_from_env() as conn:
            recorded = events.get_by_incident(conn, incident_id)

        dated = [event.at for event in recorded
                 if isinstance(event, PersonWrote) and event.message == SOME_MESSAGE]

        if dated != [expected]:
            raise AssertionError(
                f"Expected the account of the message dated [{expected}], got {dated}."
            )

        return True

    return assertion


def _the_record_holds(expected: ThreadMessage) -> Assertion[bool]:
    def assertion(_ingested: bool) -> bool:
        with connect_from_env() as conn:
            kept = conversation.get(conn, expected.message)

        if kept != expected:
            raise AssertionError(
                f"Expected the incident's record to hold {expected}, got {kept}."
            )

        return True

    return assertion
