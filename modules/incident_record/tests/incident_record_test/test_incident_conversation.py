"""What people wrote in an incident's thread, and what Argus made of it, kept
through the conversation's role.

A message nobody has understood is found by the reader of people's messages;
once understood, it is not found again. The message a press answers is found
by its own name. Built over connections, the role opens nothing until asked,
and keeps what it writes once it has answered.
"""

from __future__ import annotations

import pytest
from argus_testkit import Assertion, Scenario, calling, the_answer_was
from core.models import Alert, Meaning, ThreadMessage, a_chat_message
from incident_record import (
    incident_conversation_on,
    incident_conversation_over,
    ingest_a_message,
)
from postgres import connect_from_env

from incident_record_test.framework.builders import an_incident_created_for
from incident_record_test.framework.opening import connections_never_opened, it_was_built

DONT_CARE_ALERT = Alert(service="kuki-service", alert_name="HighErrorRate")
THE_CHAT_PLATFORM = "Slack"
SOME_MESSAGE = a_chat_message(THE_CHAT_PLATFORM, "C-some-channel", "1760000100.000200")
SOME_PERSON = "U-some-person"
SOME_WORDS = "rolled the flag back by hand, we're fine"
SOME_MEANING = Meaning.INFORMATION
# More than any case here has written.
EVERY_MESSAGE = 10


@pytest.mark.component
def test_a_message_nobody_understood_is_one_to_understand() -> None:
    incident_id = _an_incident_with_a_message()

    with connect_from_env() as conn:
        Scenario() \
            .when(lambda: incident_conversation_on(conn).not_understood(EVERY_MESSAGE)) \
            .then(_the_messages_are([(incident_id, SOME_MESSAGE.value)]))


@pytest.mark.component
def test_a_message_understood_is_not_one_to_understand_again() -> None:
    _an_incident_with_a_message()
    conversation = incident_conversation_over(connect_from_env)

    Scenario() \
        .given(calling(lambda: conversation.understood(SOME_MESSAGE, SOME_MEANING))) \
        .when(lambda: conversation.not_understood(EVERY_MESSAGE)) \
        .then(the_answer_was([]))


@pytest.mark.component
def test_a_message_is_found_by_its_own_name() -> None:
    incident_id = _an_incident_with_a_message()

    Scenario() \
        .when(lambda: incident_conversation_over(connect_from_env).message(SOME_MESSAGE)) \
        .then(_the_message_found_is(incident_id, SOME_WORDS))


@pytest.mark.component
def test_the_conversation_over_connections_opens_nothing_when_built() -> None:
    Scenario() \
        .when(lambda: incident_conversation_over(connections_never_opened())) \
        .then(it_was_built())


def _an_incident_with_a_message() -> str:
    """An incident, and one message a person wrote in its thread, committed."""
    with connect_from_env() as conn:
        incident_id = an_incident_created_for(conn, DONT_CARE_ALERT)

    ingest_a_message(incident_id, SOME_MESSAGE, SOME_PERSON, SOME_WORDS, connect_from_env)

    return incident_id


def _the_messages_are(expected: list[tuple[str, str]]) -> Assertion[list[ThreadMessage]]:
    def assertion(messages: list[ThreadMessage]) -> bool:
        found = [(written.incident_id, written.message.value) for written in messages]

        if found != expected:
            raise AssertionError(
                f"Expected the messages nobody understood to be {expected}, and they "
                f"were {found}."
            )

        return True

    return assertion


def _the_message_found_is(incident_id: str, text: str) -> Assertion[ThreadMessage | None]:
    def assertion(written: ThreadMessage | None) -> bool:
        found = (written.incident_id, written.text) if written is not None else None

        if found != (incident_id, text):
            raise AssertionError(
                f"Expected the message found to be {(incident_id, text)}, and it was {found}."
            )

        return True

    return assertion
