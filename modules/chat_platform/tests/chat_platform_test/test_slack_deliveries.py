"""Parsing what Slack tells Argus about an incident's thread, and refusing what
it did not sign.

Two jobs, both of them the adapter's alone. The first is trust: a delivery is
parsed only once its signature and its timestamp say Slack sent it just now,
because what it can say - a person pressed "resolve" - ends an incident, and a
press recorded once can otherwise be replayed for ever. The second is
translation into Argus's words, and the rule this suite exists for: only a
person's new reply in a thread is ingested. Argus's own posts, edits, deletions,
joins and channel chatter are not someone telling Argus something.

The payloads are Slack's Events API and `block_actions` shapes as
docs.slack.dev documents them, trimmed to the fields parsed.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import pytest
from argus_core.models import ReportChannel, a_chat_message, a_chat_thread
from argus_testkit import Assertion, Scenario, an_error_was_raised, attempting
from chat_platform.platform import (
    ChatDeliveryUnverified,
    Delivery,
    Handshake,
    Irrelevant,
    Pressed,
    Written,
)
from chat_platform.slack_deliveries import (
    ACTION_ID,
    ACTIONS,
    BLOCK_ACTIONS,
    BOT_ID,
    CHALLENGE,
    CHANNEL,
    CONTENT_TYPE_HEADER,
    EVENT,
    EVENT_CALLBACK,
    FORM_CONTENT_TYPE,
    ID,
    MESSAGE,
    MESSAGE_EVENT,
    PAYLOAD,
    RESOLVE_ACTION,
    SIGNATURE_HEADER,
    SIGNATURE_VERSION,
    SUBTYPE,
    TEXT,
    THREAD_TS,
    TIMESTAMP_HEADER,
    TS,
    TYPE,
    URL_VERIFICATION,
    USER,
    VALUE,
    parse_delivery,
)

SOME_SECRET = "some-signing-secret"
NOW = datetime(2026, 10, 10, 3, 30, tzinfo=UTC)

SOME_CHANNEL = "C-some-channel"
SOME_THREAD = "1760000000.000100"
SOME_REPLY = "1760000100.000200"
SOME_PERSON = "U-some-person"


@pytest.mark.unit
def test_a_reply_in_a_thread_is_parsed_as_a_person_writing() -> None:
    some_words = "rolled the flag back by hand, we're fine"
    some_delivery = _an_event({TYPE: MESSAGE_EVENT, CHANNEL: SOME_CHANNEL, USER: SOME_PERSON,
                               TEXT: some_words, TS: SOME_REPLY, THREAD_TS: SOME_THREAD})

    Scenario() \
        .given(some_delivery) \
        .when(lambda: parse_delivery(some_delivery, _signed(some_delivery), SOME_SECRET, NOW)) \
        .then(_it_is_parsed_as(Written(
            thread=a_chat_thread(ReportChannel.SLACK, SOME_CHANNEL, SOME_THREAD),
            message=a_chat_message(ReportChannel.SLACK, SOME_CHANNEL, SOME_REPLY),
            person_id=SOME_PERSON,
            text=some_words
        )))


@pytest.mark.unit
def test_a_press_of_the_resolve_button_is_parsed_as_that_person_pressing_it() -> None:
    # The button's value is the message the offer was made about, which is
    # what the press is checked against.
    some_delivery = _a_press(RESOLVE_ACTION, value=SOME_REPLY)

    Scenario() \
        .given(some_delivery) \
        .when(lambda: parse_delivery(some_delivery, _signed(some_delivery, form=True),
                                    SOME_SECRET, NOW)) \
        .then(_it_is_parsed_as(Pressed(
            thread=a_chat_thread(ReportChannel.SLACK, SOME_CHANNEL, SOME_THREAD),
            person_id=SOME_PERSON,
            message=a_chat_message(ReportChannel.SLACK, SOME_CHANNEL, SOME_REPLY)
        )))


@pytest.mark.unit
def test_slack_checking_the_address_is_answered_with_its_challenge() -> None:
    some_challenge = "some-challenge"
    some_delivery = json.dumps({TYPE: URL_VERIFICATION, CHALLENGE: some_challenge}).encode()

    Scenario() \
        .given(some_delivery) \
        .when(lambda: parse_delivery(some_delivery, _signed(some_delivery), SOME_SECRET, NOW)) \
        .then(_it_is_parsed_as(Handshake(challenge=some_challenge)))


@pytest.mark.unit
def test_a_delivery_signed_with_another_secret_is_refused() -> None:
    # What a forged "this person pressed resolve" looks like. Parsed, it would
    # end an incident nobody ended.
    some_delivery = _a_reply()

    Scenario() \
        .given(some_delivery) \
        .when(attempting(lambda: parse_delivery(
            some_delivery, _signed(some_delivery, secret="some-other-secret"), SOME_SECRET, NOW
        ))) \
        .then(an_error_was_raised(ChatDeliveryUnverified))


@pytest.mark.unit
def test_a_delivery_with_no_signature_is_refused() -> None:
    some_delivery = _a_reply()

    Scenario() \
        .given(some_delivery) \
        .when(attempting(lambda: parse_delivery(some_delivery, {}, SOME_SECRET, NOW))) \
        .then(an_error_was_raised(ChatDeliveryUnverified))


@pytest.mark.unit
def test_a_delivery_whose_timestamp_is_not_a_number_is_refused() -> None:
    # Signed correctly over what it says, and still no moment anybody can
    # check its age against.
    some_delivery = _a_reply()
    not_a_number = "some-moment"

    Scenario() \
        .given(some_delivery) \
        .when(attempting(lambda: parse_delivery(
            some_delivery, _signed(some_delivery, timestamp=not_a_number), SOME_SECRET, NOW
        ))) \
        .then(an_error_was_raised(ChatDeliveryUnverified))


@pytest.mark.unit
def test_with_no_secret_configured_every_delivery_is_refused() -> None:
    # An empty secret is a deployment that never set one, not a key anybody
    # holds - and anybody can compute a signature under it.
    no_secret = ""
    some_delivery = _a_reply()

    Scenario() \
        .given(some_delivery) \
        .when(attempting(lambda: parse_delivery(
            some_delivery, _signed(some_delivery, secret=no_secret), no_secret, NOW
        ))) \
        .then(an_error_was_raised(ChatDeliveryUnverified))


@pytest.mark.unit
def test_a_delivery_signed_six_minutes_ago_is_refused() -> None:
    # The signature covers the timestamp, so a recorded press stays correctly
    # signed for ever. Slack's own advice is five minutes either way, and a
    # press replayed after that is refused however well it is signed.
    some_delivery = _a_reply()

    Scenario() \
        .given(some_delivery) \
        .when(attempting(lambda: parse_delivery(
            some_delivery, _signed(some_delivery, at=NOW - timedelta(minutes=6)),
            SOME_SECRET, NOW
        ))) \
        .then(an_error_was_raised(ChatDeliveryUnverified))


@pytest.mark.unit
def test_a_delivery_signed_six_minutes_ahead_is_refused() -> None:
    # Five minutes either way: a timestamp in the future is one somebody chose,
    # and a press signed ahead would be good for as long as it was ahead.
    some_delivery = _a_reply()

    Scenario() \
        .given(some_delivery) \
        .when(attempting(lambda: parse_delivery(
            some_delivery, _signed(some_delivery, at=NOW + timedelta(minutes=6)),
            SOME_SECRET, NOW
        ))) \
        .then(an_error_was_raised(ChatDeliveryUnverified))


@pytest.mark.unit
def test_a_delivery_signed_four_minutes_ago_is_parsed() -> None:
    # Slack retries a delivery that was not answered in time, and the retry
    # carries the first attempt's timestamp - so a delivery a few minutes old
    # is an ordinary one.
    some_delivery = _a_reply()

    Scenario() \
        .given(some_delivery) \
        .when(lambda: parse_delivery(some_delivery,
                                    _signed(some_delivery, at=NOW - timedelta(minutes=4)),
                                    SOME_SECRET, NOW)) \
        .then(_it_is_a_person_writing())


@pytest.mark.unit
def test_a_message_in_the_channel_rather_than_a_thread_is_irrelevant() -> None:
    # An incident is talked about in its own thread. A channel message is not
    # about any one incident, and guessing which would be Argus putting words
    # into an incident nobody addressed.
    some_delivery = _an_event({TYPE: MESSAGE_EVENT, CHANNEL: SOME_CHANNEL, USER: SOME_PERSON,
                               TEXT: "anyone around?", TS: SOME_REPLY})

    Scenario() \
        .given(some_delivery) \
        .when(lambda: parse_delivery(some_delivery, _signed(some_delivery), SOME_SECRET, NOW)) \
        .then(_it_is_irrelevant())


@pytest.mark.unit
def test_the_message_that_opened_a_thread_is_not_a_reply_in_it() -> None:
    # Slack marks a thread's first message with its own timestamp as the
    # thread's. That message is Argus opening the war room, not anyone writing
    # in it.
    some_delivery = _an_event({TYPE: MESSAGE_EVENT, CHANNEL: SOME_CHANNEL, USER: SOME_PERSON,
                               TEXT: "some words", TS: SOME_THREAD, THREAD_TS: SOME_THREAD})

    Scenario() \
        .given(some_delivery) \
        .when(lambda: parse_delivery(some_delivery, _signed(some_delivery), SOME_SECRET, NOW)) \
        .then(_it_is_irrelevant())


@pytest.mark.unit
def test_a_bots_reply_is_irrelevant() -> None:
    # Argus's own replies arrive here too. Ingested, each one would be
    # classified, and classifying Argus's own offer is Argus talking to itself.
    some_delivery = _an_event({TYPE: MESSAGE_EVENT, CHANNEL: SOME_CHANNEL, BOT_ID: "B-some-bot",
                               TEXT: "some words", TS: SOME_REPLY, THREAD_TS: SOME_THREAD})

    Scenario() \
        .given(some_delivery) \
        .when(lambda: parse_delivery(some_delivery, _signed(some_delivery), SOME_SECRET, NOW)) \
        .then(_it_is_irrelevant())


@pytest.mark.unit
def test_a_reply_nobody_is_named_as_writing_is_irrelevant() -> None:
    # No bot's id and no person's either. There is nobody to offer anything to,
    # and nobody to credit a resolution to.
    some_delivery = _an_event({TYPE: MESSAGE_EVENT, CHANNEL: SOME_CHANNEL,
                               TEXT: "some words", TS: SOME_REPLY, THREAD_TS: SOME_THREAD})

    Scenario() \
        .given(some_delivery) \
        .when(lambda: parse_delivery(some_delivery, _signed(some_delivery), SOME_SECRET, NOW)) \
        .then(_it_is_irrelevant())


@pytest.mark.unit
@pytest.mark.parametrize("subtype", ["message_changed", "message_deleted", "channel_join"])
def test_anything_other_than_a_new_message_is_irrelevant(subtype: str) -> None:
    # An edit is the same message again, and a deletion is a person taking
    # their words back. Neither is a person telling Argus something new, and
    # ingesting either would offer to resolve an incident twice for one sentence.
    some_delivery = _an_event({TYPE: MESSAGE_EVENT, SUBTYPE: subtype, CHANNEL: SOME_CHANNEL,
                               USER: SOME_PERSON, TS: SOME_REPLY, THREAD_TS: SOME_THREAD})

    Scenario() \
        .given(some_delivery) \
        .when(lambda: parse_delivery(some_delivery, _signed(some_delivery), SOME_SECRET, NOW)) \
        .then(_it_is_irrelevant())


@pytest.mark.unit
def test_an_event_that_is_not_a_message_is_irrelevant() -> None:
    some_delivery = _an_event({TYPE: "reaction_added", USER: SOME_PERSON})

    Scenario() \
        .given(some_delivery) \
        .when(lambda: parse_delivery(some_delivery, _signed(some_delivery), SOME_SECRET, NOW)) \
        .then(_it_is_irrelevant())


@pytest.mark.unit
def test_a_press_of_a_button_argus_did_not_post_is_irrelevant() -> None:
    some_delivery = _a_press("some-other-action", value=SOME_REPLY)

    Scenario() \
        .given(some_delivery) \
        .when(lambda: parse_delivery(some_delivery, _signed(some_delivery, form=True),
                                    SOME_SECRET, NOW)) \
        .then(_it_is_irrelevant())


@pytest.mark.unit
def test_an_interaction_that_is_not_a_press_is_irrelevant() -> None:
    # A form submitted, a shortcut run: the same form-field shape, and still
    # not somebody answering an offer.
    some_delivery = _a_press(RESOLVE_ACTION, value=SOME_REPLY, kind="view_submission")

    Scenario() \
        .given(some_delivery) \
        .when(lambda: parse_delivery(some_delivery, _signed(some_delivery, form=True),
                                    SOME_SECRET, NOW)) \
        .then(_it_is_irrelevant())


def _a_reply() -> bytes:
    return _an_event({TYPE: MESSAGE_EVENT, CHANNEL: SOME_CHANNEL, USER: SOME_PERSON,
                      TEXT: "some words", TS: SOME_REPLY, THREAD_TS: SOME_THREAD})


def _an_event(event: dict[str, Any]) -> bytes:
    """One Events API body, as the bytes Slack signs."""
    return json.dumps({TYPE: EVENT_CALLBACK, EVENT: event}).encode()


def _a_press(action_id: str, value: str, kind: str = BLOCK_ACTIONS) -> bytes:
    """One interaction body, `block_actions` unless told otherwise: a form
    field holding the payload as JSON."""
    payload = {
        TYPE: kind,
        USER: {ID: SOME_PERSON},
        CHANNEL: {ID: SOME_CHANNEL},
        MESSAGE: {TS: "1760000200.000300", THREAD_TS: SOME_THREAD},
        ACTIONS: [{ACTION_ID: action_id, VALUE: value}]
    }

    return urlencode({PAYLOAD: json.dumps(payload)}).encode()


def _signed(body: bytes,
            secret: str = SOME_SECRET,
            at: datetime = NOW,
            form: bool = False,
            timestamp: str | None = None) -> dict[str, str]:
    """Slack's signature: an HMAC-SHA256, in hex, of the version, the
    timestamp and the raw body joined by colons.

    The timestamp is `at` in epoch seconds, unless one is given as it is to be
    sent."""
    sent = timestamp if timestamp is not None else str(int(at.timestamp()))
    signed = f"{SIGNATURE_VERSION}:{sent}:".encode() + body
    digest = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    headers = {SIGNATURE_HEADER: f"{SIGNATURE_VERSION}={digest}", TIMESTAMP_HEADER: sent}

    return headers | ({CONTENT_TYPE_HEADER: FORM_CONTENT_TYPE} if form else {})


def _it_is_parsed_as(expected: Delivery) -> Assertion[Delivery]:
    def assertion(parsed: Delivery) -> bool:
        if parsed != expected:
            raise AssertionError(
                f"Expected the delivery parsed as {expected!r}, got {parsed!r}."
            )

        return True

    return assertion


def _it_is_a_person_writing() -> Assertion[Delivery]:
    def assertion(parsed: Delivery) -> bool:
        if not isinstance(parsed, Written):
            raise AssertionError(
                f"Expected the delivery parsed as a person writing, got {parsed!r}."
            )

        return True

    return assertion


def _it_is_irrelevant() -> Assertion[Delivery]:
    def assertion(parsed: Delivery) -> bool:
        if not isinstance(parsed, Irrelevant):
            raise AssertionError(f"Expected the delivery to be irrelevant, got {parsed!r}.")

        return True

    return assertion
