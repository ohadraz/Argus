"""What Argus does with a delivery from the chat platform an incident is talked
about in.

Two things, for two deliveries. A person writing in an incident's thread is
ingested: recorded on that incident, once, however often the platform delivers it,
and classified for what it meant later and elsewhere - nothing slow happens inside
the three seconds the platform waits. And a person pressing the button on an offer
resolves or withdraws the incident, whichever the offer offered, credited to
them, through the platform, with the words the offer was made about - but only
if the offer was made to them.

Both parties are stood in for: the platform because it is somebody else's API,
and the incident record because its rows are asserted against a real database
in its own suite.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any
from unittest.mock import call, create_autospec

import pytest
from argus_core.events import Offered, ResolutionOffered, WithdrawalOffered
from argus_core.models import (
    CHAT_THREAD,
    Reference,
    Report,
    ReportChannel,
    a_chat_message,
    a_chat_thread,
)
from argus_testkit import (
    Assertion,
    Scenario,
    all_of,
    an_error_was_raised,
    attempting,
    calling,
    one_record_was_logged,
)
from argus_web.chat import ChatRecord, receive_chat_delivery
from chat_platform import (
    ChatDeliveryUnverified,
    ChatPlatformReads,
    Delivery,
    Handshake,
    Irrelevant,
    Pressed,
    Written,
)

SOME_ARGUS_INCIDENT = "4c1e2a50-0000-4000-8000-000000000001"
SOME_THREAD = a_chat_thread(ReportChannel.SLACK, "C-some-channel", "1760000000.000100")
SOME_MESSAGE = a_chat_message(ReportChannel.SLACK, "C-some-channel", "1760000100.000200")
SOME_PERSON = "U-some-person"
SOME_WORDS = "rolled the flag back by hand, we're fine"

DONT_CARE_BODY = b"{}"
DONT_CARE_HEADERS: dict[str, str] = {}

# An offer made to a person, named or not - either kind, for the cases that
# hold for both.
type OfferOf = Callable[[str, str | None], Offered]


def _an_offer(to: str, named: str | None) -> ResolutionOffered:
    return ResolutionOffered(incident_id=SOME_ARGUS_INCIDENT, message=SOME_MESSAGE,
                             person_id=to, person_name=named, said=SOME_WORDS)


def _a_withdrawal_offer(to: str, named: str | None) -> WithdrawalOffered:
    return WithdrawalOffered(incident_id=SOME_ARGUS_INCIDENT, message=SOME_MESSAGE,
                             person_id=to, person_name=named, said=SOME_WORDS)


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
        .then(one_record_was_logged(caplog, "argus_web.chat", logging.INFO,
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
            one_record_was_logged(caplog, "argus_web.chat", logging.INFO,
                                  "chat message in no incident's thread",
                                  values={"chat_thread": SOME_THREAD.value})
        ))


@pytest.mark.unit
def test_the_person_an_offer_was_made_to_pressing_it_resolves_the_incident() -> None:
    # Credited by the name the offer was made with, through the platform, with
    # their own words as the note: all of it read off the offer, which is the
    # one record of what the person said and who they are.
    some_name = "Some Person"
    platform = _a_platform(saying=Pressed(thread=SOME_THREAD, person_id=SOME_PERSON,
                                          message=SOME_MESSAGE))
    record = _a_record(knowing={SOME_THREAD.value: SOME_ARGUS_INCIDENT},
                       offers=[_an_offer(to=SOME_PERSON, named=some_name)])

    Scenario() \
        .when(lambda: receive_chat_delivery(DONT_CARE_BODY, DONT_CARE_HEADERS,
                                            platform=platform, record=record)) \
        .then(_it_was_resolved(record, SOME_ARGUS_INCIDENT,
                               Report(by=some_name, channel=ReportChannel.SLACK,
                                      note=SOME_WORDS)))


@pytest.mark.unit
def test_an_offer_to_a_person_the_platform_could_not_name_credits_them_by_their_id() -> None:
    # Somebody resolved it, and the account must say who. The platform's id is
    # the one name for them Argus holds - one a reader can look up, where
    # "could not say" would send them nowhere.
    platform = _a_platform(saying=Pressed(thread=SOME_THREAD, person_id=SOME_PERSON,
                                          message=SOME_MESSAGE))
    record = _a_record(knowing={SOME_THREAD.value: SOME_ARGUS_INCIDENT},
                       offers=[_an_offer(to=SOME_PERSON, named=None)])

    Scenario() \
        .when(lambda: receive_chat_delivery(DONT_CARE_BODY, DONT_CARE_HEADERS,
                                            platform=platform, record=record)) \
        .then(_it_was_resolved(record, SOME_ARGUS_INCIDENT,
                               Report(by=SOME_PERSON, channel=ReportChannel.SLACK,
                                      note=SOME_WORDS)))


@pytest.mark.unit
@pytest.mark.parametrize(("named", "credited"), [("Some Person", "Some Person"),
                                                 (None, SOME_PERSON)],
                         ids=["named", "unnamed"])
def test_the_person_a_withdrawal_offer_was_made_to_pressing_it_withdraws_the_incident(
        named: str | None, credited: str) -> None:
    # The resolution's twin, ending the other way: the offer found by the
    # message is what says which ending the press confirms, so the same button
    # withdraws - credited, through the platform, with their words - and
    # resolves nothing.
    platform = _a_platform(saying=Pressed(thread=SOME_THREAD, person_id=SOME_PERSON,
                                          message=SOME_MESSAGE))
    record = _a_record(knowing={SOME_THREAD.value: SOME_ARGUS_INCIDENT},
                       offers=[_a_withdrawal_offer(to=SOME_PERSON, named=named)])

    Scenario() \
        .when(lambda: receive_chat_delivery(DONT_CARE_BODY, DONT_CARE_HEADERS,
                                            platform=platform, record=record)) \
        .then(all_of(
            _it_was_withdrawn(record, SOME_ARGUS_INCIDENT,
                              Report(by=credited, channel=ReportChannel.SLACK,
                                     note=SOME_WORDS)),
            _nothing_was_resolved(record)
        ))


@pytest.mark.unit
def test_pressing_an_offer_to_resolve_withdraws_nothing() -> None:
    platform = _a_platform(saying=Pressed(thread=SOME_THREAD, person_id=SOME_PERSON,
                                          message=SOME_MESSAGE))
    record = _a_record(knowing={SOME_THREAD.value: SOME_ARGUS_INCIDENT},
                       offers=[_an_offer(to=SOME_PERSON, named="dont care")])

    Scenario() \
        .when(lambda: receive_chat_delivery(DONT_CARE_BODY, DONT_CARE_HEADERS,
                                            platform=platform, record=record)) \
        .then(_nothing_was_withdrawn(record))


@pytest.mark.unit
@pytest.mark.parametrize("offer_of", [_an_offer, _a_withdrawal_offer],
                         ids=["resolution", "withdrawal"])
def test_somebody_else_pressing_an_offer_ends_nothing(
        offer_of: OfferOf, caplog: pytest.LogCaptureFixture) -> None:
    # The offer is to the person who asked. Anybody else pressing it would be
    # ending the incident in their name.
    someone_else = "U-someone-else"
    platform = _a_platform(saying=Pressed(thread=SOME_THREAD, person_id=someone_else,
                                          message=SOME_MESSAGE))
    record = _a_record(knowing={SOME_THREAD.value: SOME_ARGUS_INCIDENT},
                       offers=[offer_of(SOME_PERSON, "dont care")])

    Scenario() \
        .given(calling(lambda: caplog.set_level(logging.INFO))) \
        .when(lambda: receive_chat_delivery(DONT_CARE_BODY, DONT_CARE_HEADERS,
                                            platform=platform, record=record)) \
        .then(all_of(
            _nothing_ended(record),
            one_record_was_logged(caplog, "argus_web.chat", logging.INFO,
                                  "offer pressed by someone else",
                                  values={"incident_id": SOME_ARGUS_INCIDENT,
                                          "chat_message": SOME_MESSAGE.value,
                                          "person_id": someone_else})
        ))


@pytest.mark.unit
def test_a_press_on_no_offer_argus_made_ends_nothing(
        caplog: pytest.LogCaptureFixture) -> None:
    # Only reachable by a press Argus never posted the button for - so it is a
    # warning, where every other refusal here is an ordinary day.
    platform = _a_platform(saying=Pressed(thread=SOME_THREAD, person_id=SOME_PERSON,
                                          message=SOME_MESSAGE))
    record = _a_record(knowing={SOME_THREAD.value: SOME_ARGUS_INCIDENT}, offers=[])

    Scenario() \
        .when(lambda: receive_chat_delivery(DONT_CARE_BODY, DONT_CARE_HEADERS,
                                            platform=platform, record=record)) \
        .then(all_of(
            _nothing_ended(record),
            one_record_was_logged(caplog, "argus_web.chat", logging.WARNING,
                                  "press on no offer",
                                  values={"chat_message": SOME_MESSAGE.value})
        ))


@pytest.mark.unit
def test_a_press_in_a_thread_no_incident_holds_ends_nothing(
        caplog: pytest.LogCaptureFixture) -> None:
    # The same warning as a press on no offer: Argus posts the button only in
    # an incident's own thread, so a press anywhere else is on a button it did
    # not post, or in a thread whose incident it lost.
    platform = _a_platform(saying=Pressed(thread=SOME_THREAD, person_id=SOME_PERSON,
                                          message=SOME_MESSAGE))
    record = _a_record(knowing={}, offers=[_an_offer(to=SOME_PERSON, named="dont care")])

    Scenario() \
        .when(lambda: receive_chat_delivery(DONT_CARE_BODY, DONT_CARE_HEADERS,
                                            platform=platform, record=record)) \
        .then(all_of(
            _nothing_ended(record),
            one_record_was_logged(caplog, "argus_web.chat", logging.WARNING,
                                  "press on no offer",
                                  values={"chat_message": SOME_MESSAGE.value})
        ))


@pytest.mark.unit
@pytest.mark.parametrize("offer_of", [_an_offer, _a_withdrawal_offer],
                         ids=["resolution", "withdrawal"])
def test_a_press_on_an_incident_that_has_already_ended_is_said(
        offer_of: OfferOf, caplog: pytest.LogCaptureFixture) -> None:
    # A button outlives the incident until the relay takes it away, so a press
    # can come after the incident ended some other way - or, for a withdrawal,
    # after Code-Fix left it mitigated. The record refuses to move it; this
    # says it did.
    platform = _a_platform(saying=Pressed(thread=SOME_THREAD, person_id=SOME_PERSON,
                                          message=SOME_MESSAGE))
    record = _a_record(knowing={SOME_THREAD.value: SOME_ARGUS_INCIDENT},
                       offers=[offer_of(SOME_PERSON, "dont care")],
                       ends=False)

    Scenario() \
        .given(calling(lambda: caplog.set_level(logging.INFO))) \
        .when(lambda: receive_chat_delivery(DONT_CARE_BODY, DONT_CARE_HEADERS,
                                            platform=platform, record=record)) \
        .then(one_record_was_logged(caplog, "argus_web.chat", logging.INFO,
                                    "offer pressed on an ended incident",
                                    values={"incident_id": SOME_ARGUS_INCIDENT,
                                            "chat_message": SOME_MESSAGE.value}))


@pytest.mark.unit
@pytest.mark.parametrize("offer_of", [_an_offer, _a_withdrawal_offer],
                         ids=["resolution", "withdrawal"])
def test_a_press_on_an_offer_that_expired_ends_nothing(
        offer_of: OfferOf, caplog: pytest.LogCaptureFixture) -> None:
    # Argus stopped waiting for this answer and carried on. A button still on
    # screen - the relay not yet round to taking it away - must not end the
    # incident on a question nobody is asking any more; the person who means
    # it writes again.
    platform = _a_platform(saying=Pressed(thread=SOME_THREAD, person_id=SOME_PERSON,
                                          message=SOME_MESSAGE))
    record = _a_record(knowing={SOME_THREAD.value: SOME_ARGUS_INCIDENT},
                       offers=[offer_of(SOME_PERSON, "dont care")],
                       expired=True)

    Scenario() \
        .given(calling(lambda: caplog.set_level(logging.INFO))) \
        .when(lambda: receive_chat_delivery(DONT_CARE_BODY, DONT_CARE_HEADERS,
                                            platform=platform, record=record)) \
        .then(all_of(
            _nothing_ended(record),
            one_record_was_logged(caplog, "argus_web.chat", logging.INFO,
                                  "press on an expired offer",
                                  values={"chat_message": SOME_MESSAGE.value})
        ))


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
    record = _a_record(knowing={SOME_THREAD.value: SOME_ARGUS_INCIDENT})

    Scenario() \
        .given(calling(lambda: caplog.set_level(logging.DEBUG))) \
        .when(lambda: receive_chat_delivery(DONT_CARE_BODY, DONT_CARE_HEADERS,
                                            platform=platform, record=record)) \
        .then(all_of(
            _it_answers(None),
            _nothing_was_ingested(record),
            _nothing_ended(record),
            one_record_was_logged(caplog, "argus_web.chat", logging.DEBUG,
                                  "chat delivery not acted on",
                                  values={"why": some_why})
        ))


@pytest.mark.unit
def test_an_unverified_delivery_is_refused_and_changes_nothing() -> None:
    platform = _a_platform(saying=Pressed(thread=SOME_THREAD, person_id=SOME_PERSON,
                                          message=SOME_MESSAGE))
    platform.parse_delivery.side_effect = ChatDeliveryUnverified("forged")
    record = _a_record(knowing={SOME_THREAD.value: SOME_ARGUS_INCIDENT},
                       offers=[_an_offer(to=SOME_PERSON, named="dont care")])

    Scenario() \
        .when(attempting(lambda: receive_chat_delivery(DONT_CARE_BODY, DONT_CARE_HEADERS,
                                                       platform=platform, record=record))) \
        .then(all_of(an_error_was_raised(ChatDeliveryUnverified), _nothing_ended(record)))


def _a_platform(saying: Delivery) -> Any:
    platform = create_autospec(ChatPlatformReads, instance=True)
    platform.channel = ReportChannel.SLACK
    platform.parse_delivery.return_value = saying

    return platform


def _a_record(knowing: dict[str, str],
              offers: list[Offered] | None = None,
              ingested_before: bool = False,
              ends: bool = True,
              expired: bool = False) -> Any:
    """An incident record holding these threads, each as value -> incident, and
    these offers. `ends` is whether a resolution or a withdrawal moves it."""
    record = create_autospec(ChatRecord, instance=True)

    def incident_known_as(kind: str, values: list[str]) -> str | None:
        if kind != CHAT_THREAD:
            return None

        return next((knowing[value] for value in values if value in knowing), None)

    def offer_about(incident_id: str, message: Reference) -> Offered | None:
        return next((offer for offer in offers or []
                     if offer.incident_id == incident_id and offer.message == message), None)

    record.incident_known_as.side_effect = incident_known_as
    record.offer_about.side_effect = offer_about
    record.ingest.return_value = not ingested_before
    record.resolve.return_value = ends
    record.withdraw.return_value = ends
    record.offer_expired.return_value = expired

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
