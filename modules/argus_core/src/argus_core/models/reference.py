"""What another tool calls an incident.

Here rather than beside the parser that first records one, for the reason
`Report` is here: the intake adapter builds one, the incident record keeps it,
and the on-call platform's adapter matches against it. A shape kept inside one
of those parties is one the others read by comparing spellings.
"""

from __future__ import annotations

from typing import Final

from pydantic import BaseModel

# The kind of name a monitor stamps on every notification it also sends a
# paging tool, which is what the paging tool hands back about its incident.
#
# A kind the two sides of a match have to spell alike - the monitor's adapter
# writes it and the paging tool's adapter looks it up - and neither knows the
# other, so it is said once, here. Any monitor's, whatever its source: the
# paging tool cannot tell which monitor stamped the key it holds.
NOTIFICATION_KEY: Final = "notification-key"

# The kind of name an on-call platform's own incident is: the id the platform
# gave it, recorded once a person's resolution there was matched to an Argus
# incident, so that the next question about it goes straight to it. The source
# is the platform's report channel, so two platforms' ids never meet.
ON_CALL_INCIDENT: Final = "on-call-incident"

# The kinds of name a chat platform gives a place in the conversation about an
# incident: the thread it is told in, a message a person wrote there, and an
# offer Argus posted there - one kind per ending offered, because an incident
# can stop accepting one ending and still accept the other, and an offer is
# retired by what it offers. The source is the platform's report channel, as an
# on-call platform's is.
CHAT_THREAD: Final = "chat-thread"
CHAT_MESSAGE: Final = "chat-message"
CHAT_RESOLUTION_OFFER: Final = "chat-resolution-offer"
CHAT_WITHDRAWAL_OFFER: Final = "chat-withdrawal-offer"

# Between the channel and the message in a place's value. A character no chat
# platform puts in a channel id, because the schema finds the channel as
# everything before it, to keep one thread per incident per channel.
_PLACE_SEPARATOR: Final = "/"


class Reference(BaseModel):
    """One name an external tool knows an incident by.

    Three parts, because a value alone says nothing about whose it is: two tools
    can each hand out a key that happens to be the same string, and one tool can
    name an incident several ways - a key it stamps on what it sends, an id it
    assigns itself. `source` is the tool, `kind` is which of its names this is,
    and `value` is the name as that tool spells it, never normalised, because it
    is matched against what the tool says later.

    Rows rather than fields on the incident: a new tool is one more `source`,
    not one more column.
    """

    source: str
    kind: str
    value: str


def a_chat_thread(platform: str, channel: str, message: str) -> Reference:
    """The thread an incident is told in: the channel, and the message that
    opened it."""
    return _a_place(platform, CHAT_THREAD, channel, message)


def a_chat_message(platform: str, channel: str, message: str) -> Reference:
    """One message a person wrote in a channel."""
    return _a_place(platform, CHAT_MESSAGE, channel, message)


def a_chat_resolution_offer(platform: str, channel: str, message: str) -> Reference:
    """One offer to resolve Argus posted in a channel."""
    return _a_place(platform, CHAT_RESOLUTION_OFFER, channel, message)


def a_chat_withdrawal_offer(platform: str, channel: str, message: str) -> Reference:
    """One offer to withdraw Argus posted in a channel."""
    return _a_place(platform, CHAT_WITHDRAWAL_OFFER, channel, message)


def the_place_of(value: str) -> tuple[str, str]:
    """The channel and the message a place in a chat names, exactly as they
    were given - from the value of a thread, a message or an offer reference.

    The value rather than the reference, because a place is stored and read
    back as its value, and a caller holding one should not have to build a
    reference around it only to have it taken apart again.

    Split at the first separator: a channel id never holds one, and a message
    id is returned whole whatever it holds.
    """
    channel, _, message = value.partition(_PLACE_SEPARATOR)

    return channel, message


def _a_place(platform: str, kind: str, channel: str, message: str) -> Reference:
    return Reference(source=platform,
                     kind=kind,
                     value=f"{channel}{_PLACE_SEPARATOR}{message}")
