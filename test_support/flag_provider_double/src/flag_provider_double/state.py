"""What a feature-flag provider holds before anybody asks it anything.

The seed both adapters in the port's suite are built from: the double reads it
directly, and the suite's Unleash stand-in serves it in Unleash's own shapes.
Every value is frozen and every collection a tuple, so a seed is the same seed
whoever holds it and however many providers are built from it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class RecordedToggle:
    """One flag switched on or off, as the provider's history records it: the
    state it was switched to, when, and by whom.

    `actor` is never absent: the provider always names an author for a change it
    records. A change recorded with none is a row of the vendor's wire, and the
    vendor's own suite pins how it is read.
    """

    flag: str
    enabled: bool
    occurred_at: datetime
    actor: str


@dataclass(frozen=True)
class ProviderState:
    """Everything the provider holds.

    `environment` is the one environment the provider is asked about - where
    every flag is held and every change recorded. `flags` is each flag and
    whether it is on there, in the order the provider lists them, and both what
    the provider holds and what evaluates until somebody sets one. `history` is
    every change recorded, oldest first.

    `signed_in_as` is the name of the credential Argus writes with, which the
    provider records as the author of Argus's own changes. A fact of the
    provider's, apart from whichever name Argus is configured to recognise as
    its own: the two drifting is what telling them apart is for.

    `evaluation_follows` is False for a provider that takes a write and never
    evaluates it: what it holds changes, and what evaluates does not.
    """

    environment: str
    flags: tuple[tuple[str, bool], ...]
    history: tuple[RecordedToggle, ...]
    signed_in_as: str
    evaluation_follows: bool = True
