"""What Slack delivers to Argus, parsed only once Slack is proven to have sent
it, just now.

Two kinds of delivery reach Argus: an Events API body, JSON, for a message
posted where the app can see it; and an interaction, a form field holding JSON,
for a button pressed on a message the app posted. Both are signed the same way
(docs.slack.dev, "Verifying requests from Slack"): an HMAC-SHA256 under the
app's signing secret of `v0:<timestamp>:<raw body>`, with the timestamp sent
beside it. Nothing here reaches Slack's API, so this is pure and takes the
secret and the moment as given; the adapter that does reach it composes this.

Which message counts is decided here, because only this module can tell a
person's new reply from everything else Slack delivers. Each rule below says
why it answers as it does.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any, Final
from urllib.parse import parse_qs

from argus_core.models import ReportChannel, a_chat_message, a_chat_thread

from chat_platform.platform import (
    ChatDeliveryUnverified,
    Delivery,
    Handshake,
    Irrelevant,
    Pressed,
    Written,
)

# Where Slack puts its signature and the moment it signed, and how it versions
# the scheme. The version is both the signature's prefix and the first part of
# what is signed.
SIGNATURE_HEADER: Final = "X-Slack-Signature"
TIMESTAMP_HEADER: Final = "X-Slack-Request-Timestamp"
SIGNATURE_VERSION: Final = "v0"

# How an interaction arrives: a form, whose one field is the payload as JSON.
CONTENT_TYPE_HEADER: Final = "Content-Type"
FORM_CONTENT_TYPE: Final = "application/x-www-form-urlencoded"
PAYLOAD: Final = "payload"

# The envelope, and the two kinds of it read: Slack checking the address, and
# an event happening.
TYPE: Final = "type"
URL_VERIFICATION: Final = "url_verification"
CHALLENGE: Final = "challenge"
EVENT_CALLBACK: Final = "event_callback"
EVENT: Final = "event"

# A message event, and the fields read off it.
MESSAGE_EVENT: Final = "message"
CHANNEL: Final = "channel"
USER: Final = "user"
TEXT: Final = "text"
TS: Final = "ts"
THREAD_TS: Final = "thread_ts"
BOT_ID: Final = "bot_id"
SUBTYPE: Final = "subtype"

# A button pressed: who pressed it, where, on which message, and which button.
BLOCK_ACTIONS: Final = "block_actions"
ID: Final = "id"
MESSAGE: Final = "message"
ACTIONS: Final = "actions"
ACTION_ID: Final = "action_id"
VALUE: Final = "value"

# The one button Argus posts: confirming an offer to resolve. Its value is the
# message the offer was made about.
RESOLVE_ACTION: Final = "resolve-incident"

# How far a delivery's timestamp may be from now, either way, and still be
# believed. Slack's own advice: the signature covers the timestamp, so a
# recorded delivery stays correctly signed for ever, and only its age gives a
# replay away.
_LONGEST_BELIEVED: Final = timedelta(minutes=5)


def parse_delivery(body: bytes,
                   headers: Mapping[str, str],
                   secret: str,
                   now: datetime) -> Delivery:
    """What one delivery says, in Argus's words.

    Raises `ChatDeliveryUnverified` unless the body is signed with `secret` at a
    moment within five minutes of `now`, before any of it is parsed.
    """
    _verify(body, headers, secret, now)

    if _the_header(headers, CONTENT_TYPE_HEADER) == FORM_CONTENT_TYPE:
        return _a_press(json.loads(parse_qs(body.decode())[PAYLOAD][0]))

    envelope = json.loads(body)

    if envelope.get(TYPE) == URL_VERIFICATION:
        return Handshake(challenge=str(envelope[CHALLENGE]))

    if envelope.get(TYPE) != EVENT_CALLBACK:
        return Irrelevant(why=f"an envelope of type [{envelope.get(TYPE)}]")

    return _a_message(envelope[EVENT])


def _a_message(event: Mapping[str, Any]) -> Delivery:
    """A message event, which is a person writing only if it passes every rule
    below, checked in this order:

    1. A message, and not any other event the app is subscribed to.
    2. No subtype. Slack marks everything that is not a new message - an edit,
       a deletion, a join, a bot's post - with one, and none of those is a
       person telling Argus something new. An edit taken as new would offer to
       resolve an incident twice for one sentence.
    3. Not a bot's. Argus's own replies arrive here too, and classifying its
       own offer is Argus talking to itself.
    4. A reply in a thread, and not the message that opened it. An incident is
       talked about in its own thread; a channel message is about no incident
       in particular, and the thread's first message is Argus opening it.
    """
    if event.get(TYPE) != MESSAGE_EVENT:
        return Irrelevant(why=f"an event of type [{event.get(TYPE)}]")

    if event.get(SUBTYPE):
        return Irrelevant(why=f"a message of subtype [{event[SUBTYPE]}]")

    if event.get(BOT_ID) or not event.get(USER):
        return Irrelevant(why="a message no person wrote")

    thread = event.get(THREAD_TS)
    ts = str(event[TS])

    if not thread or thread == ts:
        return Irrelevant(why="a message in no thread")

    channel = str(event[CHANNEL])

    return Written(
        thread=a_chat_thread(ReportChannel.SLACK, channel, str(thread)),
        message=a_chat_message(ReportChannel.SLACK, channel, ts),
        person_id=str(event[USER]),
        text=str(event.get(TEXT, ""))
    )


def _a_press(payload: Mapping[str, Any]) -> Delivery:
    """A button pressed, which is Argus's only if it is the resolve button."""
    actions = payload.get(ACTIONS) or []

    if payload.get(TYPE) != BLOCK_ACTIONS or not actions:
        return Irrelevant(why=f"an interaction of type [{payload.get(TYPE)}]")

    action = actions[0]

    if action.get(ACTION_ID) != RESOLVE_ACTION:
        return Irrelevant(why=f"a press of [{action.get(ACTION_ID)}]")

    channel = str(payload[CHANNEL][ID])

    return Pressed(
        thread=a_chat_thread(ReportChannel.SLACK, channel, str(payload[MESSAGE][THREAD_TS])),
        person_id=str(payload[USER][ID]),
        message=a_chat_message(ReportChannel.SLACK, channel, str(action[VALUE]))
    )


def _verify(body: bytes, headers: Mapping[str, str], secret: str, now: datetime) -> None:
    """Refuses a body no signature of `secret` covers, or one signed too long
    ago or too far ahead.

    An empty secret refuses everything: it is a deployment that never set one,
    and anybody can sign under it. The signature is compared in constant time,
    so how long a refusal takes says nothing about how close a guess was.
    """
    if not secret:
        raise ChatDeliveryUnverified(
            "no signing secret is configured, so no delivery can be trusted"
        )

    timestamp = _the_header(headers, TIMESTAMP_HEADER)
    stated = _the_header(headers, SIGNATURE_HEADER)

    if not timestamp or not stated or not timestamp.isdigit():
        raise ChatDeliveryUnverified("the delivery carries no signature")

    signed_at = datetime.fromtimestamp(int(timestamp), tz=now.tzinfo)

    if abs(now - signed_at) > _LONGEST_BELIEVED:
        raise ChatDeliveryUnverified(f"the delivery was signed at {signed_at}, too far from now")

    signed = f"{SIGNATURE_VERSION}:{timestamp}:".encode() + body
    expected = f"{SIGNATURE_VERSION}=" + hmac.new(secret.encode(), signed,
                                                   hashlib.sha256).hexdigest()

    if not hmac.compare_digest(expected, stated):
        raise ChatDeliveryUnverified("the delivery's signature does not match its body")


def _the_header(headers: Mapping[str, str], name: str) -> str | None:
    """One header, however the server that received it cased the name.

    HTTP header names are case-insensitive, and a web framework's mapping may
    hand them over lower-cased. A content type is compared without its
    parameters, which a client may add.
    """
    wanted = name.lower()
    value = next((value for key, value in headers.items() if key.lower() == wanted), None)

    return value.split(";")[0].strip() if value is not None else None
