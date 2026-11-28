"""What Slack delivers, written and signed as Slack sends it.

The one writer of Slack's deliveries in this suite: the wire suite builds its
bodies and signatures here, and the ports' suite writes what was delivered -
an Argus `Delivery` - through `as_slack_sends` for the Slack adapter, beside
the double over its own writing of the same thing. Every word of Slack's it
speaks is imported from the adapter, so the two cannot spell one differently.

How each is written: the platform checking the address as `url_verification`;
a person writing in a thread as a message event, its thread and its id the
places the references name; a press as a `block_actions` form whose one action
is the confirm button, its value the message the offer was made about; and
something Argus does not act on as an envelope of a type it does not read.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime
from typing import Any, Final
from urllib.parse import urlencode

from chat_platform import Delivery, Handshake, Irrelevant, Pressed, Written
from chat_platform.slack_deliveries import (
    ACTION_ID,
    ACTIONS,
    BLOCK_ACTIONS,
    CHALLENGE,
    CHANNEL,
    CONFIRM_ACTION,
    CONTENT_TYPE_HEADER,
    EVENT,
    EVENT_CALLBACK,
    FORM_CONTENT_TYPE,
    ID,
    MESSAGE,
    MESSAGE_EVENT,
    PAYLOAD,
    SIGNATURE_HEADER,
    SIGNATURE_VERSION,
    TEXT,
    THREAD_TS,
    TIMESTAMP_HEADER,
    TS,
    TYPE,
    URL_VERIFICATION,
    USER,
    VALUE,
)
from core.models import the_place_of

# An envelope type Slack sends and the adapter does not read: Slack telling an
# app its events are being rate limited.
APP_RATE_LIMITED: Final = "app_rate_limited"

# The id of the message a button was pressed on, which the adapter does not
# read: the button's value names the message the offer was made about.
_THE_OFFERS_OWN_MESSAGE: Final = "1760000200.000300"


def an_event(event: dict[str, Any]) -> bytes:
    """One Events API body, as the bytes Slack signs."""
    return json.dumps({TYPE: EVENT_CALLBACK, EVENT: event}).encode()


def a_press(*,
            person_id: str,
            channel: str,
            thread: str | None,
            action_id: str,
            value: str,
            kind: str = BLOCK_ACTIONS) -> bytes:
    """One interaction body, `block_actions` unless told otherwise."""
    return an_interaction(a_press_payload(person_id=person_id, channel=channel, thread=thread,
                                          action_id=action_id, value=value, kind=kind))


def a_press_payload(*,
                    person_id: str,
                    channel: str,
                    thread: str | None,
                    action_id: str,
                    value: str,
                    kind: str = BLOCK_ACTIONS) -> dict[str, Any]:
    """What a press says, before it is put in its form: `block_actions` unless
    told otherwise, on a message in `thread` - or in none, where that is
    `None`."""
    pressed_on = {TS: _THE_OFFERS_OWN_MESSAGE} | ({THREAD_TS: thread} if thread else {})

    return {
        TYPE: kind,
        USER: {ID: person_id},
        CHANNEL: {ID: channel},
        MESSAGE: pressed_on,
        ACTIONS: [{ACTION_ID: action_id, VALUE: value}]
    }


def an_interaction(payload: Any) -> bytes:
    """One interaction body: a form whose one field holds `payload` as JSON."""
    return a_form({PAYLOAD: json.dumps(payload)})


def a_form(fields: dict[str, str]) -> bytes:
    """A form body holding `fields`, as Slack sends an interaction."""
    return urlencode(fields).encode()


def slack_signed(body: bytes,
                 *,
                 secret: str,
                 at: datetime,
                 form: bool = False,
                 timestamp: str | None = None) -> dict[str, str]:
    """Slack's signature: an HMAC-SHA256, in hex, of the version, the
    timestamp and the raw body joined by colons - and the content type, where
    the body is a form.

    The timestamp is `at` in epoch seconds, unless one is given as it is to be
    sent."""
    sent = timestamp if timestamp is not None else str(int(at.timestamp()))
    signed = f"{SIGNATURE_VERSION}:{sent}:".encode() + body
    digest = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    headers = {SIGNATURE_HEADER: f"{SIGNATURE_VERSION}={digest}", TIMESTAMP_HEADER: sent}

    return headers | ({CONTENT_TYPE_HEADER: FORM_CONTENT_TYPE} if form else {})


def as_slack_sends(said: Delivery,
                   *,
                   signed_with: str,
                   at: datetime) -> tuple[bytes, dict[str, str]]:
    """`said` as Slack delivers it, and the headers signing exactly those
    bytes as sent at `at`."""
    match said:
        case Handshake(challenge=challenge):
            body = json.dumps({TYPE: URL_VERIFICATION, CHALLENGE: challenge}).encode()

            return body, slack_signed(body, secret=signed_with, at=at)
        case Written(thread=thread, message=message, person_id=person_id, text=text):
            channel, opened_by = the_place_of(thread.value)
            _, written = the_place_of(message.value)
            body = an_event({TYPE: MESSAGE_EVENT, CHANNEL: channel, USER: person_id,
                             TEXT: text, TS: written, THREAD_TS: opened_by})

            return body, slack_signed(body, secret=signed_with, at=at)
        case Pressed(thread=thread, person_id=person_id, message=message):
            channel, opened_by = the_place_of(thread.value)
            _, about = the_place_of(message.value)
            body = a_press(person_id=person_id, channel=channel, thread=opened_by,
                           action_id=CONFIRM_ACTION, value=about)

            return body, slack_signed(body, secret=signed_with, at=at, form=True)
        case Irrelevant():
            body = json.dumps({TYPE: APP_RATE_LIMITED}).encode()

            return body, slack_signed(body, secret=signed_with, at=at)
