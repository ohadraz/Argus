"""Slack as a case plays it: a person writing in an incident's thread, the
offer Argus answers with, and the person pressing it.

What Slack delivers is posted by the case itself, signed as Slack signs it, at
the moment the stack's own clock says it is - the stack may run on a simulated
one, and a delivery signed by the wall clock would be refused as too old. The
double holds what Argus posted and the people it can name; nothing in the stack
plays Slack's side of the conversation, because a real workspace needs a public
address and a suite has none.

The intent agent asks a model of its own, through a double of its own, so that what
it was answering never takes a place in the walk's queue.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from collections.abc import Callable
from typing import Any, Final
from urllib.parse import urlencode

import httpx2
import psycopg
from argus_core import get_settings, utc_now
from argus_core.models import CHAT_THREAD, the_place_of
from argus_incidents.repository import references
from chat_platform.slack_deliveries import (
    ACTION_ID,
    ACTIONS,
    BLOCK_ACTIONS,
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
    TEXT,
    THREAD_TS,
    TIMESTAMP_HEADER,
    TS,
    TYPE,
    USER,
    VALUE,
)
from chat_platform.slack_posting import ACTIONS_BLOCK, BLOCK_TYPE, BUTTON_ELEMENT, ELEMENTS

from tests.e2e.framework.argus import (
    ARGUS_WEB_BASE_URL,
    DATABASE_URL,
    REQUEST_TIMEOUT_SECONDS,
)

# Where the intent agent's model double listens. Kept in step with the noxfile's
# `_INTENT_ANTHROPIC_DOUBLE_PORT` by hand, as the other addresses here are:
# the noxfile is read before anything is installed, and is imported by nothing.
INTENT_ANTHROPIC_DOUBLE_BASE_URL: Final = "http://localhost:8098"

# The intent agent's one recorded reading: a person saying the incident is over.
RECORDED_INTENT_RESOLVE: Final = "intent-resolve"

# What the recorded reading was asked about. The double never reads the
# request, so these are the words a case has to write for the answer it serves
# to be an answer to them.
THE_WORDS_CLASSIFIED_AS_RESOLVED: Final = "rolled the flag back by hand, we're fine"

# How long a case waits for something the stack does without being asked - the
# relay opening a thread, the intent agent reading a message and offering. Both
# poll every half second; this is that, with room for a loaded machine.
_LONG_ENOUGH_TO_HAPPEN: Final = 60.0
_A_POLL: Final = 0.5


def the_intent_agent_answers_from(recording: str) -> Callable[[], None]:
    """A `given` step naming the stored answer the intent agent's model gives.

    Resets first, for the reason the walk's double does: a seed left by an
    earlier case answers until it is cleared.
    """
    def seeded() -> None:
        with httpx2.Client(base_url=INTENT_ANTHROPIC_DOUBLE_BASE_URL,
                           timeout=REQUEST_TIMEOUT_SECONDS) as control:
            control.post("/double-control/reset").raise_for_status()
            control.post("/double-control/seed",
                         json={"recording": recording, "repeat": 1}).raise_for_status()

    return seeded


def the_chat_platform_knows(person_id: str, real_name: str) -> Callable[[], None]:
    """A `given` step staging somebody the workspace can name."""
    def staged() -> None:
        httpx2.post(f"{_slack()}/double-control/user",
                    json={"id": person_id, "real_name": real_name},
                    timeout=REQUEST_TIMEOUT_SECONDS).raise_for_status()

    return staged


def the_thread_of(incident_id: str) -> tuple[str, str]:
    """The channel and the message Argus opened this incident's conversation
    with, once the relay has opened it."""
    deadline = time.monotonic() + _LONG_ENOUGH_TO_HAPPEN

    while time.monotonic() < deadline:
        with psycopg.connect(DATABASE_URL) as conn:
            values = references.get_values_for(conn, incident_id, CHAT_THREAD)

        if values:
            return the_place_of(values[0])

        time.sleep(_A_POLL)

    raise AssertionError(f"Incident [{incident_id}] was never given a thread in Slack.")


def a_person_writes(person_id: str, words: str, in_thread: tuple[str, str]) -> str:
    """Delivers a reply in the thread, as Slack's Events API sends one, and
    answers with the id Slack would have given the message."""
    channel, thread = in_thread
    written = f"{utc_now().timestamp():.6f}"

    delivered = _deliver(json.dumps({
        TYPE: EVENT_CALLBACK,
        EVENT: {TYPE: MESSAGE_EVENT, CHANNEL: channel, USER: person_id, TEXT: words,
                TS: written, THREAD_TS: thread}
    }).encode(), "application/json", "/webhooks/slack/events")
    delivered.raise_for_status()

    return written


def the_offer_made_in(in_thread: tuple[str, str]) -> dict[str, Any]:
    """The message carrying a button, once one is posted in the thread."""
    _, thread = in_thread
    deadline = time.monotonic() + _LONG_ENOUGH_TO_HAPPEN

    while time.monotonic() < deadline:
        offers = [message for message in posted_to_slack()
                  if message["thread_ts"] == thread and the_buttons_on(message)]
        if offers:
            return offers[-1]

        time.sleep(_A_POLL)

    raise AssertionError(f"Nothing was offered in thread [{thread}].")


def the_person_presses(person_id: str,
                       offer: dict[str, Any],
                       about: str) -> httpx2.Response:
    """Delivers a press of the offer's button, as Slack's interactivity sends
    one: a form whose one field is the payload."""
    payload = {
        TYPE: BLOCK_ACTIONS,
        USER: {ID: person_id},
        CHANNEL: {ID: offer["channel"]},
        MESSAGE: {TS: offer["ts"], THREAD_TS: offer["thread_ts"]},
        ACTIONS: [{ACTION_ID: RESOLVE_ACTION, VALUE: about}]
    }

    return _deliver(urlencode({PAYLOAD: json.dumps(payload)}).encode(),
                    FORM_CONTENT_TYPE, "/webhooks/slack/interactions")


def posted_to_slack() -> list[dict[str, Any]]:
    """Every message the double holds, each as it reads now."""
    answered: dict[str, Any] = httpx2.get(f"{_slack()}/double-control/posted",
                                          timeout=REQUEST_TIMEOUT_SECONDS).json()
    held: list[dict[str, Any]] = answered["posted"]

    return held


def the_buttons_on(message: dict[str, Any]) -> list[dict[str, Any]]:
    """The buttons a message carries, read out of its blocks as Slack lays them
    out."""
    return [element
            for block in message.get("blocks") or [] if block[BLOCK_TYPE] == ACTIONS_BLOCK
            for element in block[ELEMENTS] if element[BLOCK_TYPE] == BUTTON_ELEMENT]


def _deliver(body: bytes, content_type: str, path: str) -> httpx2.Response:
    """Posts one delivery to Argus, signed with the stack's signing secret at
    the stack's own now."""
    timestamp = str(int(utc_now().timestamp()))
    signed = f"{SIGNATURE_VERSION}:{timestamp}:".encode() + body
    secret = get_settings().slack_signing_secret.encode()
    signature = f"{SIGNATURE_VERSION}=" + hmac.new(secret, signed, hashlib.sha256).hexdigest()

    return httpx2.post(
        f"{ARGUS_WEB_BASE_URL}{path}",
        content=body,
        headers={CONTENT_TYPE_HEADER: content_type,
                 TIMESTAMP_HEADER: timestamp,
                 SIGNATURE_HEADER: signature},
        timeout=REQUEST_TIMEOUT_SECONDS
    )


def _slack() -> str:
    """Where Slack is, as the relay was told it - the double, in this stack."""
    return get_settings().slack_base_url
