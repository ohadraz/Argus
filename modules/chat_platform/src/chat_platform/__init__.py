"""The chat platform the incident is talked about in, in both directions.

A port named for the role and split by direction, with one adapter named for
its vendor: what a person wrote in an incident's thread, which button they
pressed and what the platform calls them, read by the web application and the
intent agent; and what Argus says, posted by the Communicator. Only the adapter
knows an envelope, a header, a field or a method name, and only the
composition roots of those three build it.
"""

from chat_platform.platform import (
    ChatDeliveryUnverified,
    ChatPlatformReads,
    ChatPlatformWrites,
    Delivery,
    Handshake,
    Irrelevant,
    Line,
    Link,
    Offer,
    Posted,
    Pressed,
    Written,
)

__all__ = [
    "ChatDeliveryUnverified",
    "ChatPlatformReads",
    "ChatPlatformWrites",
    "Delivery",
    "Handshake",
    "Irrelevant",
    "Line",
    "Link",
    "Offer",
    "Posted",
    "Pressed",
    "Written"
]
