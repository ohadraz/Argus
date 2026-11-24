"""What a chat thread's deliveries ask of the incident record: which incident a
thread is, and whether a press of an offer's button is accepted.

A thread is one incident's or nobody's: a thread several incidents hold names
none of them, and acting on one would be guessing. A press is accepted only
where the message it was pressed beside belongs to the thread's incident,
carries an offer, the offer has not expired, and the person pressing wrote the
message - and then it is credited by the name they were given when the offer
was made, or by the platform's id for them where it could not name them.

The names and the conversation are stood in for, because their rows are
asserted against a real database in their own suites. What belongs here is the
decision made from what they answer.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import create_autospec

import pytest
from argus_testkit import Assertion, Scenario
from core.models import (
    CHAT_THREAD,
    IncidentStanding,
    IncidentStatus,
    Meaning,
    Offer,
    OfferedEnding,
    Reference,
    ThreadMessage,
    a_chat_message,
    a_chat_thread,
)
from incident_record import (
    Accepted,
    IncidentConversation,
    IncidentNames,
    NotAccepted,
    NotAcceptedBecause,
    accept_offer,
    the_incident_of_thread,
)

# The chat platform's name, as its adapter gives it.
THE_CHAT_PLATFORM = "Slack"

SOME_ARGUS_INCIDENT = "4c1e2a50-0000-4000-8000-000000000001"
SOME_OTHER_ARGUS_INCIDENT = "4c1e2a50-0000-4000-8000-000000000002"
SOME_THREAD = a_chat_thread(THE_CHAT_PLATFORM, "C-some-channel", "1760000000.000100")
SOME_MESSAGE = a_chat_message(THE_CHAT_PLATFORM, "C-some-channel", "1760000100.000200")
SOME_PERSON = "U-some-person"
SOME_WORDS = "rolled the flag back by hand, we're fine"
DONT_CARE_NAME = "dont care"
DONT_CARE_TIME = datetime(2026, 10, 11, 1, 0, tzinfo=UTC)


@pytest.mark.unit
def test_a_thread_one_incident_holds_is_that_incidents() -> None:
    names = _names(holding={SOME_THREAD.value: [SOME_ARGUS_INCIDENT]})

    Scenario() \
        .when(lambda: the_incident_of_thread(names, SOME_THREAD)) \
        .then(_the_incident_is(SOME_ARGUS_INCIDENT))


@pytest.mark.unit
def test_a_thread_no_incident_holds_is_nobodys() -> None:
    # Argus is in the channel for its war rooms, and people hold other
    # conversations there.
    names = _names(holding={})

    Scenario() \
        .when(lambda: the_incident_of_thread(names, SOME_THREAD)) \
        .then(_the_incident_is(None))


@pytest.mark.unit
def test_a_thread_two_incidents_hold_is_nobodys() -> None:
    # A name several incidents hold names none of them: acting on either would
    # be guessing which one a person meant.
    names = _names(holding={SOME_THREAD.value: [SOME_ARGUS_INCIDENT, SOME_OTHER_ARGUS_INCIDENT]})

    Scenario() \
        .when(lambda: the_incident_of_thread(names, SOME_THREAD)) \
        .then(_the_incident_is(None))


@pytest.mark.unit
def test_the_writer_pressing_an_offer_to_resolve_is_accepted_and_credited_by_name() -> None:
    # Credited by the name the offer was made with, with their own words as the
    # note: the one record of what the person said and who they are.
    some_name = "Some Person"
    names = _names(holding={SOME_THREAD.value: [SOME_ARGUS_INCIDENT]})
    conversation = _a_conversation(keeping=_a_message_offered(IncidentStatus.RESOLVED,
                                                             named=some_name))

    Scenario() \
        .when(lambda: accept_offer(conversation, names, SOME_THREAD, SOME_MESSAGE, SOME_PERSON)) \
        .then(_the_answer_is(Accepted(incident_id=SOME_ARGUS_INCIDENT,
                                      ending=IncidentStatus.RESOLVED,
                                      credited_to=some_name,
                                      note=SOME_WORDS)))


@pytest.mark.unit
def test_a_writer_the_platform_could_not_name_is_credited_by_their_id() -> None:
    # Somebody ended it, and the account must say who. The platform's id is
    # the one name for them Argus holds - one a reader can look up, where
    # "could not say" would send them nowhere.
    names = _names(holding={SOME_THREAD.value: [SOME_ARGUS_INCIDENT]})
    conversation = _a_conversation(keeping=_a_message_offered(IncidentStatus.RESOLVED,
                                                             named=None))

    Scenario() \
        .when(lambda: accept_offer(conversation, names, SOME_THREAD, SOME_MESSAGE, SOME_PERSON)) \
        .then(_the_answer_is(Accepted(incident_id=SOME_ARGUS_INCIDENT,
                                      ending=IncidentStatus.RESOLVED,
                                      credited_to=SOME_PERSON,
                                      note=SOME_WORDS)))


@pytest.mark.unit
def test_the_writer_pressing_an_offer_to_withdraw_is_accepted_as_a_withdrawal() -> None:
    # The offer kept on the message is what says which ending the press
    # confirms, so the same button accepts a withdrawal.
    some_name = "Some Person"
    names = _names(holding={SOME_THREAD.value: [SOME_ARGUS_INCIDENT]})
    conversation = _a_conversation(keeping=_a_message_offered(IncidentStatus.WITHDRAWN,
                                                             named=some_name))

    Scenario() \
        .when(lambda: accept_offer(conversation, names, SOME_THREAD, SOME_MESSAGE, SOME_PERSON)) \
        .then(_the_answer_is(Accepted(incident_id=SOME_ARGUS_INCIDENT,
                                      ending=IncidentStatus.WITHDRAWN,
                                      credited_to=some_name,
                                      note=SOME_WORDS)))


@pytest.mark.unit
def test_somebody_else_pressing_an_offer_is_not_accepted_and_names_the_incident() -> None:
    # The offer is to the person who asked. Anybody else pressing it would be
    # ending the incident in their name.
    someone_else = "U-someone-else"
    names = _names(holding={SOME_THREAD.value: [SOME_ARGUS_INCIDENT]})
    conversation = _a_conversation(keeping=_a_message_offered(IncidentStatus.RESOLVED,
                                                             named=DONT_CARE_NAME))

    Scenario() \
        .when(lambda: accept_offer(conversation, names, SOME_THREAD, SOME_MESSAGE, someone_else)) \
        .then(_the_answer_is(NotAccepted(NotAcceptedBecause.NOT_THEIRS, SOME_ARGUS_INCIDENT)))


@pytest.mark.unit
def test_a_press_in_a_thread_no_incident_holds_is_on_no_offer() -> None:
    # Argus posts the button only in an incident's own thread, so a press
    # anywhere else is on a button it did not post, or in a thread whose
    # incident it lost.
    names = _names(holding={})
    conversation = _a_conversation(keeping=_a_message_offered(IncidentStatus.RESOLVED,
                                                             named=DONT_CARE_NAME))

    Scenario() \
        .when(lambda: accept_offer(conversation, names, SOME_THREAD, SOME_MESSAGE, SOME_PERSON)) \
        .then(_the_answer_is(NotAccepted(NotAcceptedBecause.NO_OFFER)))


@pytest.mark.unit
def test_a_press_beside_no_message_kept_is_on_no_offer() -> None:
    names = _names(holding={SOME_THREAD.value: [SOME_ARGUS_INCIDENT]})
    conversation = _a_conversation(keeping=None)

    Scenario() \
        .when(lambda: accept_offer(conversation, names, SOME_THREAD, SOME_MESSAGE, SOME_PERSON)) \
        .then(_the_answer_is(NotAccepted(NotAcceptedBecause.NO_OFFER)))


@pytest.mark.unit
def test_a_press_beside_a_message_kept_but_never_offered_is_on_no_offer() -> None:
    # Kept, but with nothing offered on it - a lead, or a request for an ending
    # the incident no longer took. No button was posted beside it.
    names = _names(holding={SOME_THREAD.value: [SOME_ARGUS_INCIDENT]})
    a_lead = ThreadMessage(incident_id=SOME_ARGUS_INCIDENT, message=SOME_MESSAGE,
                           person_id=SOME_PERSON, text=SOME_WORDS, written_at=DONT_CARE_TIME,
                           meaning=Meaning.INFORMATION)
    conversation = _a_conversation(keeping=a_lead)

    Scenario() \
        .when(lambda: accept_offer(conversation, names, SOME_THREAD, SOME_MESSAGE, SOME_PERSON)) \
        .then(_the_answer_is(NotAccepted(NotAcceptedBecause.NO_OFFER)))


@pytest.mark.unit
def test_a_press_in_one_incidents_thread_beside_anothers_message_is_on_no_offer() -> None:
    # A message is found by its own name and belongs to one incident: a press
    # in one incident's thread on another's message ends neither.
    names = _names(holding={SOME_THREAD.value: [SOME_ARGUS_INCIDENT]})
    anothers = _a_message_offered(IncidentStatus.RESOLVED, named=DONT_CARE_NAME,
                                  of=SOME_OTHER_ARGUS_INCIDENT)
    conversation = _a_conversation(keeping=anothers)

    Scenario() \
        .when(lambda: accept_offer(conversation, names, SOME_THREAD, SOME_MESSAGE, SOME_PERSON)) \
        .then(_the_answer_is(NotAccepted(NotAcceptedBecause.NO_OFFER)))


@pytest.mark.unit
def test_a_press_on_an_offer_that_expired_is_not_accepted_and_names_the_incident() -> None:
    # Argus stopped waiting for this answer and carried on. A button still on
    # screen must not end the incident on a question nobody is asking any
    # more; the person who means it writes again.
    names = _names(holding={SOME_THREAD.value: [SOME_ARGUS_INCIDENT]})
    conversation = _a_conversation(keeping=_a_message_offered(IncidentStatus.RESOLVED,
                                                             named=DONT_CARE_NAME,
                                                             expired=True))

    Scenario() \
        .when(lambda: accept_offer(conversation, names, SOME_THREAD, SOME_MESSAGE, SOME_PERSON)) \
        .then(_the_answer_is(NotAccepted(NotAcceptedBecause.EXPIRED, SOME_ARGUS_INCIDENT)))


def _a_message_offered(ending: OfferedEnding,
                       named: str | None,
                       of: str = SOME_ARGUS_INCIDENT,
                       expired: bool = False) -> ThreadMessage:
    """SOME_MESSAGE, written by SOME_PERSON on incident `of`, kept with the
    ending offered back to them."""
    meaning = Meaning.RESOLVE if ending == IncidentStatus.RESOLVED else Meaning.WITHDRAW

    return ThreadMessage(incident_id=of, message=SOME_MESSAGE, person_id=SOME_PERSON,
                         person_name=named, text=SOME_WORDS, written_at=DONT_CARE_TIME,
                         meaning=meaning, offer=Offer(ending=ending, expired=expired))


def _names(holding: dict[str, list[str]]) -> Any:
    """The incident's names, holding these threads, each as value -> the
    incidents holding it."""
    names = create_autospec(IncidentNames, instance=True)

    def incidents_known_as(kind: str, values: list[str]) -> list[IncidentStanding]:
        if kind != CHAT_THREAD:
            return []

        return [IncidentStanding(id=incident_id, status=IncidentStatus.INVESTIGATING,
                                 created_at=DONT_CARE_TIME, ended_at=None)
                for value in values
                for incident_id in holding.get(value, [])]

    names.incidents_known_as.side_effect = incidents_known_as

    return names


def _a_conversation(keeping: ThreadMessage | None) -> Any:
    """The conversation, keeping this one message - or none."""
    conversation = create_autospec(IncidentConversation, instance=True)

    def message(asked: Reference) -> ThreadMessage | None:
        return keeping if keeping is not None and keeping.message == asked else None

    conversation.message.side_effect = message

    return conversation


def _the_incident_is(expected: str | None) -> Assertion[str | None]:
    def assertion(incident_id: str | None) -> bool:
        if incident_id != expected:
            raise AssertionError(
                f"Expected the thread to be incident [{expected}]'s, got [{incident_id}]."
            )

        return True

    return assertion


def _the_answer_is(expected: Accepted | NotAccepted) -> Assertion[Accepted | NotAccepted]:
    def assertion(answer: Accepted | NotAccepted) -> bool:
        if answer != expected:
            raise AssertionError(f"Expected the press answered [{expected}], got [{answer}].")

        return True

    return assertion
