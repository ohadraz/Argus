"""Both chat-platform ports, answered from memory.

Everything it says is what the ports promise and their suite pins over both
adapters:
- a delivery signed with its secret, as it arrived, within five minutes of its
  clock either way, is what it says; any other is `ChatDeliveryUnverified`,
  before a byte of it is read; and one so signed that is no delivery of its
  own writing is `ChatDeliveryUnreadable`. Holding no secret, it refuses
  every delivery;
- a person it holds is named as it names them, and anybody else - or
  everybody, where nothing reaches it - is `None`;
- a write lands, and is answered with its message, unless a queued refusal
  answers it first or nothing reaches the platform; a rewrite of a message it
  never posted is refused, and not worth another go. Neither ever raises.

What it was asked to say is kept, in Argus's terms, for whoever needs to read
it back: the ports themselves read nothing back.
"""

from __future__ import annotations

import hmac
import json
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Final

from chat_platform import (
    ChatDeliveryUnreadable,
    ChatDeliveryUnverified,
    Delivery,
    Handshake,
    Irrelevant,
    Line,
    Offer,
    Posted,
    Pressed,
    Written,
)

from chat_platform_double.deliveries import (
    KIND,
    SENT_AT_HEADER,
    SIGNATURE_HEADER,
    headers_signing,
)
from chat_platform_double.state import ChatState

# How far a delivery's moment may be from the clock, either way, and still be
# believed: a delivery recorded and sent again stays signed for ever, and only
# its age gives it away.
_LONGEST_BELIEVED: Final = timedelta(minutes=5)

# What a write is answered with where nothing reaches the platform: no message,
# and worth another go, since an unreachable platform says nothing about the
# message.
_UNREACHABLE: Final = Posted(message=None, refusal="the platform is not reachable",
                             worth_another_go=True)

# What a rewrite of a message the platform never posted is answered with: as
# true on the next pass as on this one.
_NO_SUCH_MESSAGE: Final = "no such message"

_DELIVERIES: Final[Mapping[str, type[Delivery]]] = {
    kind.__name__: kind for kind in (Handshake, Written, Pressed, Irrelevant)
}


@dataclass(frozen=True)
class Said:
    """One message the platform was asked to say, as it says it now: where,
    the line, the thread it answers and the offer it carries, its id, and
    whether a rewrite has replaced what it first said."""

    channel: str
    message: str
    line: Line
    thread: str | None = None
    offer: Offer | None = None
    rewritten: bool = False


class InMemoryChat:
    """A chat platform held in memory, answering both `ChatPlatformReads` and
    `ChatPlatformWrites`.

    `secret` is what a delivery must be signed with to be believed, and `clock`
    what its moment is checked against. `unreachable` builds a platform nothing
    reaches: nobody is named, and no write lands.
    """

    def __init__(self,
                 state: ChatState,
                 *,
                 secret: str,
                 clock: Callable[[], datetime],
                 unreachable: bool = False) -> None:
        self._name = state.name
        self._people = {person.id: person.name for person in state.people}
        self._refusals = deque(state.refusals)
        self._secret = secret
        self._clock = clock
        self._unreachable = unreachable
        self._said: list[Said] = []

    @property
    def name(self) -> str:
        return self._name

    @property
    def said(self) -> tuple[Said, ...]:
        """Every message it was asked to say and did, in the order it was
        first asked, each as it says it now."""
        return tuple(self._said)

    def parse_delivery(self, body: bytes, headers: Mapping[str, str]) -> Delivery:
        self._verify(body, headers)

        # `AttributeError` too: a body that is JSON and no object meets `.pop`
        # on something that has none, or one that takes no name.
        try:
            sent = json.loads(body)

            return _DELIVERIES[sent.pop(KIND)].model_validate(sent)
        except (AttributeError, LookupError, TypeError, ValueError) as unreadable:
            raise ChatDeliveryUnreadable(repr(unreadable)) from unreadable

    def person_named(self, person_id: str) -> str | None:
        return None if self._unreachable else self._people.get(person_id)

    def post(self,
             channel: str,
             line: Line,
             thread: str | None = None,
             offer: Offer | None = None) -> Posted:
        refused = self._refused()

        if refused is not None:
            return refused

        message = str(len(self._said) + 1)
        self._said.append(Said(channel=channel, message=message, line=line, thread=thread,
                               offer=offer))

        return Posted(message=message)

    def rewrite(self, channel: str, message: str, line: Line) -> Posted:
        refused = self._refused()

        if refused is not None:
            return refused

        at = next((index for index, said in enumerate(self._said)
                   if (said.channel, said.message) == (channel, message)), None)

        if at is None:
            return Posted(message=None, refusal=_NO_SUCH_MESSAGE)

        self._said[at] = replace(self._said[at], line=line, offer=None, rewritten=True)

        return Posted(message=message)

    def _refused(self) -> Posted | None:
        """What a write is answered with before it lands, if anything."""
        if self._unreachable:
            return _UNREACHABLE

        if not self._refusals:
            return None

        refusal = self._refusals.popleft()

        return Posted(message=None, refusal=refusal.why,
                      worth_another_go=refusal.worth_another_go)

    def _verify(self, body: bytes, headers: Mapping[str, str]) -> None:
        # An empty secret refuses everything: anybody can sign under it.
        if not self._secret:
            raise ChatDeliveryUnverified("no secret is held, so no delivery can be trusted")

        sent_at = _the_header(headers, SENT_AT_HEADER)
        signature = _the_header(headers, SIGNATURE_HEADER)

        if sent_at is None or signature is None or not sent_at.isdigit():
            raise ChatDeliveryUnverified("the delivery carries no signature")

        now = self._clock()

        if abs(now - datetime.fromtimestamp(int(sent_at), tz=now.tzinfo)) > _LONGEST_BELIEVED:
            raise ChatDeliveryUnverified("the delivery was signed too far from now")

        expected = headers_signing(body, self._secret,
                                   datetime.fromtimestamp(int(sent_at), tz=now.tzinfo))

        if not hmac.compare_digest(expected[SIGNATURE_HEADER], signature):
            raise ChatDeliveryUnverified("the delivery's signature does not match its body")


def _the_header(headers: Mapping[str, str], name: str) -> str | None:
    """One header, however it is cased: header names are case-insensitive, and
    a web framework may hand them over lower-cased."""
    return next((value for key, value in headers.items() if key.lower() == name.lower()), None)
