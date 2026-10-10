"""The door a person's words about an incident come in through.

Beside the resolution and shaped like it, for the same reason: `argus_web`
calls it, and anything `argus_web` can import must reach nothing that walks a
graph. It ingests and decides nothing - what the words meant is classified
later, by the intent agent, from the event this writes.

What it owes its callers is that a message is ingested once. The chat platform
retries a delivery it believes went unanswered, and a message ingested twice is
classified twice and offered back to its writer twice. So the message's own
name and the account of it are one write: claimed and recorded together, or
neither.
"""

from __future__ import annotations

import pytest
from argus_core import connect_from_env
from argus_core.events import PersonWrote
from argus_core.models import Alert, ReportChannel, a_chat_message
from argus_incidents.ingesting import ingest_a_message
from argus_incidents.repository import events, incidents
from argus_testkit import Assertion, Scenario, all_of, attempting, calling

SOME_MESSAGE = a_chat_message(ReportChannel.SLACK, "C-some-channel", "1760000100.000200")
SOME_PERSON = "U-some-person"
SOME_WORDS = "rolled the flag back by hand, we're fine"


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
def test_a_message_whose_account_could_not_be_written_is_not_claimed_either(
        a_clean_database: None) -> None:
    # Claimed and recorded together, or neither. A claim that outlived a failed
    # write would leave the platform's retry finding the message taken, and the
    # person's words lost for good. Postgres refuses a NUL inside JSON, which
    # fails the write after the claim and for no other reason.
    incident_id = _an_incident()
    words_postgres_refuses = "rolled the flag back\x00"

    Scenario() \
        .given(calling(attempting(lambda: ingest_a_message(
            incident_id, SOME_MESSAGE, SOME_PERSON, words_postgres_refuses, connect_from_env
        )))) \
        .when(lambda: ingest_a_message(incident_id, SOME_MESSAGE, SOME_PERSON, SOME_WORDS,
                                       connect_from_env)) \
        .then(all_of(
            _it_reports(True),
            _the_incident_ingested(incident_id, [(SOME_PERSON, SOME_WORDS)])
        ))


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
