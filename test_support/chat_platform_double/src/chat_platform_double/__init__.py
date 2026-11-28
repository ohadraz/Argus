"""The chat platform, held in memory: a double of its ports, for suites.

A second adapter of `chat_platform`'s ports, and never one a process runs: a
post that succeeds in memory would have Argus report a war room nobody was told
in, so it lives where nothing that ships can install it. It is held to the
ports by their own suite, which runs it beside the vendor's adapter over one
seed and asks both the same questions.

`ChatState` is the seed - the platform's name, the people it can name as
`Person`s, and the refusals queued for its next writes as `Refusal`s - and
`InMemoryChat` answers both ports from it, keeping what it was asked to say as
`Said`. `a_delivery_of` writes a delivery as this platform sends one, signed;
`headers_signing` signs any bytes.
"""

from __future__ import annotations

from chat_platform_double.deliveries import a_delivery_of, headers_signing
from chat_platform_double.in_memory import InMemoryChat, Said
from chat_platform_double.state import ChatState, Person, Refusal

__all__ = [
    "ChatState",
    "InMemoryChat",
    "Person",
    "Refusal",
    "Said",
    "a_delivery_of",
    "headers_signing"
]
