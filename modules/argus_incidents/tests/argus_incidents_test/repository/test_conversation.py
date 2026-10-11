"""What people wrote in an incident's thread, kept as part of its record.

The conversation is the one input to an incident Argus did not produce, and
what decides on it - the wait, the press, the agents a lead reaches - reads it
here rather than off the account of it. So what this owes its readers is that a
message written is found again by its own name, whole, and that a message the
chat platform delivers twice is one message.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from argus_core import connect_from_env
from argus_core.models import (
    Alert,
    IncidentStatus,
    Meaning,
    Offer,
    ReportChannel,
    Standing,
    ThreadMessage,
    Weighing,
    a_chat_message,
)
from argus_incidents.repository import conversation
from argus_testkit import (
    Assertion,
    Scenario,
    all_of,
    an_error_was_raised,
    attempting,
    calling,
)
from pydantic import ValidationError

from argus_incidents_test.framework.builders import an_incident_created_for

SOME_MESSAGE = a_chat_message(ReportChannel.SLACK, "C-some-channel", "1760000100.000200")
SOME_PERSON = "U-some-person"
SOME_NAME = "Some Person"
SOME_WORDS = "it's the checkout flag, not the other one"
SOME_TIME = datetime(2026, 10, 11, 1, 0, tzinfo=UTC)


@pytest.mark.integration
def test_a_message_written_is_found_by_its_name_with_who_what_and_when() -> None:
    with connect_from_env() as conn:
        some_incident = an_incident_created_for(conn, _an_alert())
        written = _a_message_in(some_incident, SOME_WORDS)

        Scenario() \
            .given(calling(lambda: conversation.write(conn, written))) \
            .when(lambda: conversation.get(conn, SOME_MESSAGE)) \
            .then(_the_message_found_is(written))


@pytest.mark.integration
def test_a_first_write_of_a_message_says_it_wrote() -> None:
    with connect_from_env() as conn:
        some_incident = an_incident_created_for(conn, _an_alert())

        Scenario() \
            .when(lambda: conversation.write(conn, _a_message_in(some_incident, SOME_WORDS))) \
            .then(_it_wrote(True))


@pytest.mark.integration
def test_a_message_written_again_says_it_wrote_nothing_and_keeps_the_first() -> None:
    # A message the chat platform delivers twice is one message, and the second
    # delivery must know it is the second - or a person's words are read, and
    # offered back to them, twice.
    with connect_from_env() as conn:
        some_incident = an_incident_created_for(conn, _an_alert())
        the_first = _a_message_in(some_incident, SOME_WORDS)

        Scenario() \
            .given(calling(lambda: conversation.write(conn, the_first))) \
            .when(lambda: conversation.write(
                conn, _a_message_in(some_incident, "some other words")
            )) \
            .then(all_of(
                _it_wrote(False),
                _the_record_holds(conn, the_first)
            ))


@pytest.mark.integration
def test_a_message_nobody_wrote_is_not_found() -> None:
    with connect_from_env() as conn:
        Scenario() \
            .given(SOME_MESSAGE) \
            .when(lambda: conversation.get(conn, SOME_MESSAGE)) \
            .then(_the_message_found_is(None))


@pytest.mark.integration
def test_a_message_understood_is_found_with_what_it_meant() -> None:
    with connect_from_env() as conn:
        some_incident = an_incident_created_for(conn, _an_alert())
        written = _a_message_in(some_incident, SOME_WORDS)

        Scenario() \
            .given(
                calling(lambda: conversation.write(conn, written)),
                calling(lambda: conversation.understood(conn, SOME_MESSAGE, Meaning.INFORMATION))
            ) \
            .when(lambda: conversation.get(conn, SOME_MESSAGE)) \
            .then(_the_message_found_is(written.model_copy(update={
                "meaning": Meaning.INFORMATION
            })))


@pytest.mark.integration
@pytest.mark.parametrize("named", [SOME_NAME, None], ids=["named", "unnamed"])
def test_a_message_whose_writer_was_named_is_found_with_their_name(named: str | None) -> None:
    # What an ending is credited to and a lead is reported under - which the
    # chat platform may not have given, and the person's id stands in for.
    with connect_from_env() as conn:
        some_incident = an_incident_created_for(conn, _an_alert())
        written = _a_message_in(some_incident, SOME_WORDS)

        Scenario() \
            .given(
                calling(lambda: conversation.write(conn, written)),
                calling(lambda: conversation.named(conn, SOME_MESSAGE, named))
            ) \
            .when(lambda: conversation.get(conn, SOME_MESSAGE)) \
            .then(_the_message_found_is(written.model_copy(update={"person_name": named})))


@pytest.mark.integration
def test_a_message_offered_is_found_with_the_ending_offered() -> None:
    # What the press confirms, and an offer nobody has let lapse.
    with connect_from_env() as conn:
        some_incident = an_incident_created_for(conn, _an_alert())
        written = _a_message_in(some_incident, SOME_WORDS)

        Scenario() \
            .given(
                calling(lambda: conversation.write(conn, written)),
                calling(lambda: conversation.understood(conn, SOME_MESSAGE, Meaning.RESOLVE)),
                calling(lambda: conversation.offered(conn, SOME_MESSAGE, IncidentStatus.RESOLVED))
            ) \
            .when(lambda: conversation.get(conn, SOME_MESSAGE)) \
            .then(_the_message_found_is(written.model_copy(update={
                "meaning": Meaning.RESOLVE,
                "offer": Offer(ending=IncidentStatus.RESOLVED)
            })))


@pytest.mark.integration
def test_an_offer_that_expired_is_found_expired() -> None:
    # What the wait answers a message by once its five minutes are up, and
    # what a press on it finds: an offer nobody can confirm any more.
    with connect_from_env() as conn:
        some_incident = an_incident_created_for(conn, _an_alert())
        written = _a_message_in(some_incident, SOME_WORDS)

        Scenario() \
            .given(
                calling(lambda: conversation.write(conn, written)),
                calling(lambda: conversation.understood(conn, SOME_MESSAGE, Meaning.RESOLVE)),
                calling(lambda: conversation.offered(conn, SOME_MESSAGE, IncidentStatus.RESOLVED)),
                calling(lambda: conversation.expired(conn, SOME_MESSAGE))
            ) \
            .when(lambda: conversation.get(conn, SOME_MESSAGE)) \
            .then(_the_message_found_is(written.model_copy(update={
                "meaning": Meaning.RESOLVE,
                "offer": Offer(ending=IncidentStatus.RESOLVED, expired=True)
            })))


@pytest.mark.integration
def test_a_stored_offer_of_an_ending_no_press_can_bring_about_is_refused() -> None:
    # Validated on the way out rather than constructed, so a row holding an
    # ending outside the two a person can confirm - written by hand, or by a
    # schema that has since moved on - fails where it is read, and never
    # reaches a press that would act on it.
    with connect_from_env() as conn:
        some_incident = an_incident_created_for(conn, _an_alert())

        Scenario() \
            .given(
                calling(lambda: conversation.write(conn, _a_message_in(some_incident,
                                                                       SOME_WORDS))),
                calling(lambda: _an_ending_stored_by_hand(conn, IncidentStatus.MITIGATED))
            ) \
            .when(attempting(lambda: conversation.get(conn, SOME_MESSAGE))) \
            .then(an_error_was_raised(ValidationError))


@pytest.mark.integration
def test_an_incidents_messages_are_found_in_the_order_they_were_written() -> None:
    # What the wait reads: everything people wrote in this incident's thread,
    # and nothing written in another's.
    with connect_from_env() as conn:
        some_incident = an_incident_created_for(conn, _an_alert())
        some_other_incident = an_incident_created_for(conn, _an_alert())
        the_earlier = _a_message_at(some_incident, "1.000100", minutes=1)
        the_later = _a_message_at(some_incident, "2.000200", minutes=2)
        written_elsewhere = _a_message_at(some_other_incident, "3.000300", minutes=0)

        Scenario() \
            .given(
                calling(lambda: conversation.write(conn, the_later)),
                calling(lambda: conversation.write(conn, written_elsewhere)),
                calling(lambda: conversation.write(conn, the_earlier))
            ) \
            .when(lambda: conversation.get_all_by_incident(conn, some_incident)) \
            .then(_the_messages_found_are([the_earlier, the_later]))


@pytest.mark.integration
def test_a_lead_weighed_is_found_with_its_standing_and_why() -> None:
    # What Code-Fix and the postmortem are handed, and what a later
    # investigation is shown it said before.
    with connect_from_env() as conn:
        some_incident = an_incident_created_for(conn, _an_alert())
        written = _a_message_in(some_incident, SOME_WORDS)
        some_weighing = Weighing(standing=Standing.SUPPORTED,
                                 reason="the checkout flag moved at the onset")

        Scenario() \
            .given(
                calling(lambda: conversation.write(conn, written)),
                calling(lambda: conversation.understood(conn, SOME_MESSAGE,
                                                        Meaning.INFORMATION)),
                calling(lambda: conversation.weighed(conn, SOME_MESSAGE, some_weighing))
            ) \
            .when(lambda: conversation.get(conn, SOME_MESSAGE)) \
            .then(_the_message_found_is(written.model_copy(update={
                "meaning": Meaning.INFORMATION,
                "weighing": some_weighing
            })))


@pytest.mark.integration
def test_a_lead_weighed_again_keeps_the_later_weighing() -> None:
    # A walk that came back to the Investigator after a refutation asks again,
    # and what it found the second time is what it knows now.
    with connect_from_env() as conn:
        some_incident = an_incident_created_for(conn, _an_alert())
        the_later = Weighing(standing=Standing.REFUTED, reason="the flag was reverted to no effect")

        Scenario() \
            .given(
                calling(lambda: conversation.write(conn, _a_message_in(some_incident,
                                                                       SOME_WORDS))),
                calling(lambda: conversation.understood(conn, SOME_MESSAGE,
                                                        Meaning.INFORMATION)),
                calling(lambda: conversation.weighed(conn, SOME_MESSAGE, Weighing(
                    standing=Standing.UNVERIFIED, reason="nothing read bears on it"
                ))),
                calling(lambda: conversation.weighed(conn, SOME_MESSAGE, the_later))
            ) \
            .when(lambda: conversation.get(conn, SOME_MESSAGE)) \
            .then(_the_weighing_is(the_later))


@pytest.mark.integration
def test_an_incidents_leads_are_what_it_was_told_as_information_in_the_order_written() -> None:
    # A lead is a message understood as information. One not yet understood
    # is not a lead yet, and one asking for an ending never is - nor is one
    # written about another incident.
    with connect_from_env() as conn:
        some_incident = an_incident_created_for(conn, _an_alert())
        some_other_incident = an_incident_created_for(conn, _an_alert())
        the_earlier = _a_message_at(some_incident, "1.000100", minutes=1)
        the_later = _a_message_at(some_incident, "2.000200", minutes=2)
        not_yet_understood = _a_message_at(some_incident, "3.000300", minutes=3)
        asking_for_an_ending = _a_message_at(some_incident, "4.000400", minutes=4)
        about_another_incident = _a_message_at(some_other_incident, "5.000500", minutes=0)

        Scenario() \
            .given(
                calling(lambda: conversation.write(conn, the_later)),
                calling(lambda: conversation.write(conn, not_yet_understood)),
                calling(lambda: conversation.write(conn, asking_for_an_ending)),
                calling(lambda: conversation.write(conn, about_another_incident)),
                calling(lambda: conversation.write(conn, the_earlier)),
                calling(lambda: _understood_as_information(conn, the_earlier)),
                calling(lambda: _understood_as_information(conn, the_later)),
                calling(lambda: _understood_as_information(conn, about_another_incident)),
                calling(lambda: conversation.understood(conn, asking_for_an_ending.message,
                                                        Meaning.RESOLVE))
            ) \
            .when(lambda: conversation.get_leads_by_incident(conn, some_incident)) \
            .then(_the_messages_found_are([
                written.model_copy(update={"meaning": Meaning.INFORMATION})
                for written in [the_earlier, the_later]
            ]))


@pytest.mark.integration
def test_the_messages_nobody_has_understood_are_found_oldest_first_in_every_incident() -> None:
    # What the intent agent works through: in the order people wrote, because
    # a message understood out of order can be offered after a later one that
    # changed it - and across incidents, because it is one reader of them all.
    with connect_from_env() as conn:
        some_incident = an_incident_created_for(conn, _an_alert())
        some_other_incident = an_incident_created_for(conn, _an_alert())
        the_earliest = _a_message_at(some_other_incident, "1.000100", minutes=1)
        already_understood = _a_message_at(some_incident, "2.000200", minutes=2)
        the_latest = _a_message_at(some_incident, "3.000300", minutes=3)

        Scenario() \
            .given(
                calling(lambda: conversation.write(conn, the_latest)),
                calling(lambda: conversation.write(conn, already_understood)),
                calling(lambda: conversation.write(conn, the_earliest)),
                calling(lambda: conversation.understood(conn, already_understood.message,
                                                        Meaning.OTHER))
            ) \
            .when(lambda: conversation.get_not_understood(conn, 10)) \
            .then(_the_messages_found_are([the_earliest, the_latest]))


@pytest.mark.integration
def test_no_more_messages_nobody_has_understood_are_found_than_were_asked_for() -> None:
    with connect_from_env() as conn:
        some_incident = an_incident_created_for(conn, _an_alert())
        the_earliest = _a_message_at(some_incident, "1.000100", minutes=1)
        the_latest = _a_message_at(some_incident, "2.000200", minutes=2)

        Scenario() \
            .given(
                calling(lambda: conversation.write(conn, the_latest)),
                calling(lambda: conversation.write(conn, the_earliest))
            ) \
            .when(lambda: conversation.get_not_understood(conn, 1)) \
            .then(_the_messages_found_are([the_earliest]))


def _an_alert() -> Alert:
    return Alert(service="kuki-service", alert_name="HighErrorRate")


def _a_message_in(incident_id: str, text: str) -> ThreadMessage:
    return ThreadMessage(incident_id=incident_id,
                         message=SOME_MESSAGE,
                         person_id=SOME_PERSON,
                         text=text,
                         written_at=SOME_TIME)


def _a_message_at(incident_id: str, ts: str, *, minutes: int) -> ThreadMessage:
    return ThreadMessage(incident_id=incident_id,
                         message=a_chat_message(ReportChannel.SLACK, "C-some-channel", ts),
                         person_id=SOME_PERSON,
                         text=SOME_WORDS,
                         written_at=SOME_TIME + timedelta(minutes=minutes))


def _understood_as_information(conn: psycopg.Connection, written: ThreadMessage) -> None:
    conversation.understood(conn, written.message, Meaning.INFORMATION)


def _an_ending_stored_by_hand(conn: psycopg.Connection, ending: IncidentStatus) -> None:
    """An offer of `ending` on SOME_MESSAGE, written past the repository - the
    only way a row can come to hold an ending no offer is ever made of."""
    conn.execute(
        "UPDATE thread_message SET offered_ending = %s "
        " WHERE source = %s AND kind = %s AND value = %s",
        (ending, SOME_MESSAGE.source, SOME_MESSAGE.kind, SOME_MESSAGE.value)
    )
    conn.commit()


def _it_wrote(expected: bool) -> Assertion[bool]:
    def assertion(wrote: bool) -> bool:
        if wrote != expected:
            raise AssertionError(
                f"Expected the write to report that it {'wrote' if expected else 'wrote nothing'}, "
                f"got {wrote}."
            )

        return True

    return assertion


def _the_record_holds(conn: psycopg.Connection, expected: ThreadMessage) -> Assertion[bool]:
    def assertion(_wrote: bool) -> bool:
        return _the_message_found_is(expected)(conversation.get(conn, expected.message))

    return assertion


def _the_message_found_is(expected: ThreadMessage | None) -> Assertion[ThreadMessage | None]:
    def assertion(found: ThreadMessage | None) -> bool:
        if found != expected:
            raise AssertionError(f"Expected the message found to be {expected}, got {found}.")

        return True

    return assertion


def _the_weighing_is(expected: Weighing) -> Assertion[ThreadMessage | None]:
    def assertion(found: ThreadMessage | None) -> bool:
        weighing = found.weighing if found is not None else None

        if weighing != expected:
            raise AssertionError(f"Expected the lead weighed as {expected}, got {weighing}.")

        return True

    return assertion


def _the_messages_found_are(expected: list[ThreadMessage]) -> Assertion[list[ThreadMessage]]:
    def assertion(found: list[ThreadMessage]) -> bool:
        if found != expected:
            raise AssertionError(f"Expected the messages found to be {expected}, got {found}.")

        return True

    return assertion
