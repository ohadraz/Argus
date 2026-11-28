"""What Argus does with a delivery from the chat platform an incident is talked
about in.

Two things, for two deliveries. A person writing in an incident's thread is
ingested: recorded on that incident, once, however often the platform delivers it,
and classified for what it meant later and elsewhere - nothing slow happens inside
the three seconds the platform waits. And a person pressing the button on an offer
resolves or withdraws the incident, whichever the offer offered, credited as the
record says, through the platform, with the words the offer was made about - but
only where the record accepts the press.

Whether it does is the incident record's decision, asserted in its own suite.
What belongs here is that the press is put to it, and that each answer is acted
on or said.

Both parties are stood in for: the platform because it is somebody else's API,
and the incident record because its rows and its decisions are asserted in its
own suite.
"""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import call, create_autospec

import pytest
from argus_testkit import (
    Assertion,
    Scenario,
    all_of,
    an_error_was_raised,
    attempting,
    calling,
    one_record_was_logged,
)
from chat_platform import (
    ChatDeliveryUnreadable,
    ChatDeliveryUnverified,
    ChatPlatformReads,
    Delivery,
    Handshake,
    Irrelevant,
    Pressed,
    Written,
)
from core.models import (
    IncidentStatus,
    OfferedEnding,
    Reference,
    Report,
    ReportChannel,
    a_chat_message,
    a_chat_thread,
)
from incident_record import (
    Accepted,
    EndedAsSaid,
    NotAccepted,
    NotAcceptedBecause,
    PersonsEnding,
    Refused,
)
from web_app.chat import ChatRecord, receive_chat_delivery

# The chat platform's name, as its adapter gives it - what a reader is
# told a report came from, and what its references are filed under.
THE_CHAT_PLATFORM = "Slack"

SOME_ARGUS_INCIDENT = "4c1e2a50-0000-4000-8000-000000000001"
SOME_THREAD = a_chat_thread(THE_CHAT_PLATFORM, "C-some-channel", "1760000000.000100")
SOME_MESSAGE = a_chat_message(THE_CHAT_PLATFORM, "C-some-channel", "1760000100.000200")
SOME_PERSON = "U-some-person"
SOME_WORDS = "rolled the flag back by hand, we're fine"
DONT_CARE_NAME = "dont care"

DONT_CARE_BODY = b"{}"
DONT_CARE_HEADERS: dict[str, str] = {}

# The one person pressing the button on SOME_MESSAGE, in SOME_THREAD.
A_PRESS = Pressed(thread=SOME_THREAD, person_id=SOME_PERSON, message=SOME_MESSAGE)


def _accepted(ending: OfferedEnding, credited_to: str = DONT_CARE_NAME) -> Accepted:
    """The record accepting the press on SOME_ARGUS_INCIDENT, for `ending`."""
    return Accepted(incident_id=SOME_ARGUS_INCIDENT, ending=ending,
                    credited_to=credited_to, note=SOME_WORDS)


@pytest.mark.unit
def test_a_person_writing_in_an_incidents_thread_is_ingested_on_that_incident() -> None:
    platform = _a_platform(saying=Written(thread=SOME_THREAD, message=SOME_MESSAGE,
                                          person_id=SOME_PERSON, text=SOME_WORDS))
    record = _a_record(knowing={SOME_THREAD.value: SOME_ARGUS_INCIDENT})

    Scenario() \
        .when(lambda: receive_chat_delivery(DONT_CARE_BODY, DONT_CARE_HEADERS,
                                            platform=platform, record=record)) \
        .then(_it_was_ingested(record, SOME_ARGUS_INCIDENT, SOME_MESSAGE, SOME_PERSON,
                               SOME_WORDS))


@pytest.mark.unit
def test_a_message_ingested_before_is_said(caplog: pytest.LogCaptureFixture) -> None:
    # The platform retries a delivery it thinks went unanswered. The record
    # knows the message already, and says so; this module only says it.
    platform = _a_platform(saying=Written(thread=SOME_THREAD, message=SOME_MESSAGE,
                                          person_id=SOME_PERSON, text=SOME_WORDS))
    record = _a_record(knowing={SOME_THREAD.value: SOME_ARGUS_INCIDENT}, ingested_before=True)

    Scenario() \
        .given(calling(lambda: caplog.set_level(logging.INFO))) \
        .when(lambda: receive_chat_delivery(DONT_CARE_BODY, DONT_CARE_HEADERS,
                                            platform=platform, record=record)) \
        .then(one_record_was_logged(caplog, "web_app.chat", logging.INFO,
                                    "chat message ingested before",
                                    values={"chat_message": SOME_MESSAGE.value}))


@pytest.mark.unit
def test_a_person_writing_in_a_thread_no_incident_holds_is_not_ingested(
        caplog: pytest.LogCaptureFixture) -> None:
    # Argus is in the channel for its war rooms, and people hold other
    # conversations there.
    platform = _a_platform(saying=Written(thread=SOME_THREAD, message=SOME_MESSAGE,
                                          person_id=SOME_PERSON, text=SOME_WORDS))
    record = _a_record(knowing={})

    Scenario() \
        .given(calling(lambda: caplog.set_level(logging.INFO))) \
        .when(lambda: receive_chat_delivery(DONT_CARE_BODY, DONT_CARE_HEADERS,
                                            platform=platform, record=record)) \
        .then(all_of(
            _nothing_was_ingested(record),
            one_record_was_logged(caplog, "web_app.chat", logging.INFO,
                                  "chat message in no incident's thread",
                                  values={"chat_thread": SOME_THREAD.value})
        ))


@pytest.mark.unit
def test_a_press_is_put_to_the_record_as_the_thread_the_message_and_the_person() -> None:
    # The record decides whether the press is accepted, and decides it from
    # these three: where it was pressed, beside what, and by whom.
    platform = _a_platform(saying=A_PRESS)
    record = _a_record(knowing={}, answering=NotAccepted(NotAcceptedBecause.NO_OFFER))

    Scenario() \
        .when(lambda: receive_chat_delivery(DONT_CARE_BODY, DONT_CARE_HEADERS,
                                            platform=platform, record=record)) \
        .then(_the_press_was_put_as(record, SOME_THREAD, SOME_MESSAGE, SOME_PERSON))


@pytest.mark.unit
def test_an_accepted_offer_to_resolve_resolves_the_incident_as_the_record_credits_it() -> None:
    # Credited to whom the record says, through the platform, with the words
    # the offer was made about as the note.
    some_credited = "Some Person"
    platform = _a_platform(saying=A_PRESS)
    record = _a_record(knowing={},
                       answering=_accepted(IncidentStatus.RESOLVED, credited_to=some_credited))

    Scenario() \
        .when(lambda: receive_chat_delivery(DONT_CARE_BODY, DONT_CARE_HEADERS,
                                            platform=platform, record=record)) \
        .then(all_of(
            _it_was_resolved(record, SOME_ARGUS_INCIDENT,
                             Report(by=some_credited, channel=ReportChannel.CHAT_PLATFORM,
                                    platform=THE_CHAT_PLATFORM,
                                    note=SOME_WORDS)),
            _nothing_was_withdrawn(record)
        ))


@pytest.mark.unit
def test_an_accepted_offer_to_withdraw_withdraws_the_incident_as_the_record_credits_it() -> None:
    # The resolution's twin, ending the other way: the accepted offer says
    # which ending the press confirms, so the same button withdraws and
    # resolves nothing.
    some_credited = "Some Person"
    platform = _a_platform(saying=A_PRESS)
    record = _a_record(knowing={},
                       answering=_accepted(IncidentStatus.WITHDRAWN, credited_to=some_credited))

    Scenario() \
        .when(lambda: receive_chat_delivery(DONT_CARE_BODY, DONT_CARE_HEADERS,
                                            platform=platform, record=record)) \
        .then(all_of(
            _it_was_withdrawn(record, SOME_ARGUS_INCIDENT,
                              Report(by=some_credited, channel=ReportChannel.CHAT_PLATFORM,
                                     platform=THE_CHAT_PLATFORM,
                                     note=SOME_WORDS)),
            _nothing_was_resolved(record)
        ))


@pytest.mark.unit
@pytest.mark.parametrize(("not_accepted", "level", "logged", "values"), [
    # Only reachable by a press Argus never posted the button for - so it is a
    # warning, where every other refusal here is an ordinary day. No offer, so
    # no incident it was made on.
    (NotAccepted(NotAcceptedBecause.NO_OFFER), logging.WARNING, "press on no offer",
     {"chat_message": SOME_MESSAGE.value}),
    (NotAccepted(NotAcceptedBecause.EXPIRED, SOME_ARGUS_INCIDENT), logging.INFO,
     "press on an expired offer", {"chat_message": SOME_MESSAGE.value}),
    (NotAccepted(NotAcceptedBecause.NOT_THEIRS, SOME_ARGUS_INCIDENT), logging.INFO,
     "offer pressed by someone else",
     {"incident_id": SOME_ARGUS_INCIDENT, "chat_message": SOME_MESSAGE.value,
      "person_id": SOME_PERSON})
], ids=["no-offer", "expired", "not-theirs"])
def test_a_press_the_record_does_not_accept_ends_nothing_and_says_why(
        not_accepted: NotAccepted, level: int, logged: str, values: dict[str, str],
        caplog: pytest.LogCaptureFixture) -> None:
    platform = _a_platform(saying=A_PRESS)
    record = _a_record(knowing={}, answering=not_accepted)

    Scenario() \
        .given(calling(lambda: caplog.set_level(logging.INFO))) \
        .when(lambda: receive_chat_delivery(DONT_CARE_BODY, DONT_CARE_HEADERS,
                                            platform=platform, record=record)) \
        .then(all_of(
            _nothing_ended(record),
            one_record_was_logged(caplog, "web_app.chat", level, logged, values=values)
        ))


@pytest.mark.unit
@pytest.mark.parametrize("ending", [IncidentStatus.RESOLVED, IncidentStatus.WITHDRAWN],
                         ids=["resolution", "withdrawal"])
def test_a_press_on_an_incident_that_has_already_ended_is_said(
        ending: OfferedEnding, caplog: pytest.LogCaptureFixture) -> None:
    # A button outlives the incident until the relay takes it away, so a press
    # can come after the incident ended some other way - or, for a withdrawal,
    # after Code-Fix left it mitigated. The record refuses to move it; this
    # says it did.
    platform = _a_platform(saying=A_PRESS)
    record = _a_record(knowing={}, answering=_accepted(ending), ends=False)

    Scenario() \
        .given(calling(lambda: caplog.set_level(logging.INFO))) \
        .when(lambda: receive_chat_delivery(DONT_CARE_BODY, DONT_CARE_HEADERS,
                                            platform=platform, record=record)) \
        .then(one_record_was_logged(caplog, "web_app.chat", logging.INFO,
                                    "offer pressed on an ended incident",
                                    values={"incident_id": SOME_ARGUS_INCIDENT,
                                            "chat_message": SOME_MESSAGE.value}))


@pytest.mark.unit
def test_the_platform_checking_the_address_is_answered_with_its_challenge() -> None:
    some_challenge = "some-challenge"
    platform = _a_platform(saying=Handshake(challenge=some_challenge))

    Scenario() \
        .when(lambda: receive_chat_delivery(DONT_CARE_BODY, DONT_CARE_HEADERS,
                                            platform=platform, record=_a_record(knowing={}))) \
        .then(_it_answers(some_challenge))


@pytest.mark.unit
def test_anything_else_is_answered_with_nothing_changes_nothing_and_says_why(
        caplog: pytest.LogCaptureFixture) -> None:
    # Most of what the platform delivers is not for Argus - bots, edits, other
    # conversations - so it is said at debug, where it can be looked for
    # without being read every day.
    some_why = "a message no person wrote"
    platform = _a_platform(saying=Irrelevant(why=some_why))
    record = _a_record(knowing={SOME_THREAD.value: SOME_ARGUS_INCIDENT},
                       answering=_accepted(IncidentStatus.RESOLVED))

    Scenario() \
        .given(calling(lambda: caplog.set_level(logging.DEBUG))) \
        .when(lambda: receive_chat_delivery(DONT_CARE_BODY, DONT_CARE_HEADERS,
                                            platform=platform, record=record)) \
        .then(all_of(
            _it_answers(None),
            _nothing_was_ingested(record),
            _nothing_ended(record),
            one_record_was_logged(caplog, "web_app.chat", logging.DEBUG,
                                  "chat delivery not acted on",
                                  values={"why": some_why})
        ))


@pytest.mark.unit
@pytest.mark.parametrize("refusal", [
    pytest.param(ChatDeliveryUnverified("forged"), id="unverified"),
    pytest.param(ChatDeliveryUnreadable("unreadable"), id="unreadable")
])
def test_a_delivery_the_platform_refuses_is_refused_and_changes_nothing(
    refusal: Exception
) -> None:
    platform = _a_platform(saying=A_PRESS)
    platform.parse_delivery.side_effect = refusal
    record = _a_record(knowing={SOME_THREAD.value: SOME_ARGUS_INCIDENT},
                       answering=_accepted(IncidentStatus.RESOLVED))

    Scenario() \
        .when(attempting(lambda: receive_chat_delivery(DONT_CARE_BODY, DONT_CARE_HEADERS,
                                                       platform=platform, record=record))) \
        .then(all_of(an_error_was_raised(type(refusal)), _nothing_ended(record)))


def _a_platform(saying: Delivery) -> Any:
    platform = create_autospec(ChatPlatformReads, instance=True)
    platform.name = THE_CHAT_PLATFORM
    platform.parse_delivery.return_value = saying

    return platform


def _a_record(knowing: dict[str, str],
              answering: Accepted | NotAccepted | None = None,
              ingested_before: bool = False,
              ends: bool = True) -> Any:
    """An incident record holding these threads, each as value -> incident,
    answering every press with `answering`. `ends` is whether a resolution or a
    withdrawal moves the incident."""
    record = create_autospec(ChatRecord, instance=True)

    def incident_of_thread(thread: Reference) -> str | None:
        return knowing.get(thread.value)

    def ending(incident_id: str, _reported: Report) -> PersonsEnding:
        return EndedAsSaid(incident_id) if ends else Refused(incident_id)

    record.incident_of_thread.side_effect = incident_of_thread
    record.ingest.return_value = not ingested_before
    record.accept_offer.return_value = answering
    record.resolve.side_effect = ending
    record.withdraw.side_effect = ending

    return record


def _it_was_ingested(record: Any,
                     incident_id: str,
                     message: Reference,
                     person_id: str,
                     text: str) -> Assertion[object]:
    def assertion(_: object) -> bool:
        if record.ingest.call_args_list != [call(incident_id, message, person_id, text)]:
            raise AssertionError(
                f"Expected [{incident_id}] to ingest {person_id} saying [{text}] once, got "
                f"{record.ingest.call_args_list}."
            )

        return True

    return assertion


def _the_press_was_put_as(record: Any,
                          thread: Reference,
                          message: Reference,
                          presser: str) -> Assertion[object]:
    def assertion(_: object) -> bool:
        if record.accept_offer.call_args_list != [call(thread, message, presser)]:
            raise AssertionError(
                f"Expected the press put to the record once as [{thread}], [{message}] and "
                f"[{presser}], got {record.accept_offer.call_args_list}"
            )

        return True

    return assertion


def _it_was_resolved(record: Any, incident_id: str, reported: Report) -> Assertion[object]:
    def assertion(_: object) -> bool:
        if record.resolve.call_args_list != [call(incident_id, reported)]:
            raise AssertionError(
                f"Expected [{incident_id}] resolved once as reported by {reported!r}, got "
                f"{record.resolve.call_args_list}."
            )

        return True

    return assertion


def _nothing_was_ingested(record: Any) -> Assertion[object]:
    def assertion(_: object) -> bool:
        if record.ingest.call_args_list:
            raise AssertionError(f"Expected nothing ingested, got {record.ingest.call_args_list}.")

        return True

    return assertion


def _it_was_withdrawn(record: Any, incident_id: str, reported: Report) -> Assertion[object]:
    def assertion(_: object) -> bool:
        if record.withdraw.call_args_list != [call(incident_id, reported)]:
            raise AssertionError(
                f"Expected [{incident_id}] withdrawn once as reported by {reported!r}, got "
                f"{record.withdraw.call_args_list}."
            )

        return True

    return assertion


def _nothing_was_resolved(record: Any) -> Assertion[object]:
    def assertion(_: object) -> bool:
        if record.resolve.call_args_list:
            raise AssertionError(
                f"Expected nothing resolved, got {record.resolve.call_args_list}."
            )

        return True

    return assertion


def _nothing_was_withdrawn(record: Any) -> Assertion[object]:
    def assertion(_: object) -> bool:
        if record.withdraw.call_args_list:
            raise AssertionError(
                f"Expected nothing withdrawn, got {record.withdraw.call_args_list}."
            )

        return True

    return assertion


def _nothing_ended(record: Any) -> Assertion[object]:
    """Neither ending a press can bring about was brought about."""
    return all_of(_nothing_was_resolved(record), _nothing_was_withdrawn(record))


def _it_answers(expected: str | None) -> Assertion[str | None]:
    def assertion(answer: str | None) -> bool:
        if answer != expected:
            raise AssertionError(
                f"Expected the delivery answered with [{expected}], got [{answer}]."
            )

        return True

    return assertion
