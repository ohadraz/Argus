"""Whoever sends Argus alerts, as the web application hears them.

Named for the role - a sender of alerts - and answered by one adapter per
sender, each named for its vendor. Senders are open-ended rather than a set
Argus chooses, which is the reason for a port rather than against one: every
one of them is one more adapter behind the same question, and the route that
receives it names which.

What crosses is Argus's own `Alert`, already translated, or the news that the
delivery says only that rules stopped firing - never the sender's payload.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from core.models import Alert


@dataclass(frozen=True)
class OnlyResolved:
    """A delivery saying only that rules stopped firing.

    Never the start of an incident, and never read as one ending either:
    whether a rule has stopped firing is read from the rule, not from a
    notification that can be batched or lost.
    """


class AlertSource(Protocol):
    """A sender of alerts, for the one question the web application asks it."""

    def parse_delivery(self, body: bytes, headers: Mapping[str, str], /) -> Alert | OnlyResolved:
        """What one delivery says: the alert that fired, or that only
        resolutions were sent.

        The bytes that arrived and the headers they came with, so a sender
        that signs its deliveries is verified over what it sent. Raises
        `AlertUnreadable` for a delivery this sender's shape does not fit.
        """
        ...
