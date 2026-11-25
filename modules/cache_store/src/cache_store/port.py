"""Wherever a service caches what it worked out, as the write tier asks it to
let go of some of it.

Named for the role, and answered by one adapter named for the vendor. What
crosses is a list of keys going in and a count coming back - the keys are
addresses, arriving from the evidence that named them, and nothing on either
side of the port composes one.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol


class StoreNotReached(Exception):
    """The store did not answer before anything was asked of it.

    The port's own word for it, because only the adapter can tell: a failure
    before the discard left the entries where they were, and one after it may
    not have.
    """


class CacheStore(Protocol):
    """A service's cache, for the one thing the write tier asks of it.

    Nothing held open between actions: a walk takes at most a handful of
    these, minutes apart, and a pooled client would be a connection kept alive
    for an incident's duration to save a handshake.
    """

    @property
    def endpoint(self) -> str:
        """Where the store is dialled - the address a failure to reach it is
        explained by."""
        ...

    def discard(self, keys: Sequence[str], /) -> int:
        """Removes `keys`, answering how many of them existed and are gone.

        Raises `StoreNotReached` where the store was not there before the
        discard was asked of it, and whatever the client raises once it had
        been.
        """
        ...
