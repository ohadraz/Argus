"""What the shop took over a window, as the payment provider reports it.

Revenue is what was taken *and kept*: charges that succeeded, less what was
refunded. A refund issued while the shop was failing is part of what the
failure cost, and a charge that failed was never revenue at all.

Answered per currency, because a payment provider holds no cross-currency
total and inventing one here would hide the rate it rested on from the
document that has to disclose it.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from datetime import datetime
from decimal import Decimal

from argus_core import SettingsSlice
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class RevenueSettings(SettingsSlice):
    """What it takes to read the payment provider, and nothing else.

    Declared in this package rather than in the kernel because this is the only
    package that reads either field: a slice with one consumer belongs to that
    consumer, the way `Charge` does. What travels upwards is money with a
    currency, and a caller that never learns the credential's name cannot leak
    it into a postmortem.

    Here rather than beside the adapter that uses it, because naming what a
    source needs must not cost the SDK that source talks to. A composition root
    builds this slice to decide whether it can read the provider at all, and
    importing it out of `stripe_adapter` would import `stripe` to ask.
    """

    stripe_api_key: str
    stripe_base_url: str


class Charge(BaseModel):
    """One charge, in Argus's own terms rather than a provider's.

    Whether the money arrived is a fact, not a status string: `succeeded` is
    false for a charge that failed and for one still pending alike, because
    neither is money the shop has. Amounts are money - major units - rather
    than the minor units a provider counts in, and `refunded` is what went
    back off this charge.

    An object rather than the mapping a provider answers with, so that a field
    a listing failed to report is refused where the listing is read, not found
    missing three modules later by whatever was about to add it up.
    """

    succeeded: bool
    currency: str
    amount: Decimal
    refunded: Decimal = Decimal(0)


# One window's charges. The port: whatever reads a provider satisfies this,
# and does so in Argus's vocabulary - no vendor's object, and no mapping of
# its field names, reaches anything above the adapter that built it.
type Charges = Callable[[datetime, datetime], Iterable[Charge]]


class RevenueUnavailable(Exception):
    """The payment provider could not be read.

    Raised by whatever fetches the listing, which is where a vendor's failures
    are known by their own names. Everything above the fetch answers in this
    vocabulary instead, so a provider's SDK stops at the one function that
    imports it.

    An exception rather than an empty listing, because the whole purpose of
    this port is that "nothing was taken" and "nobody could say" are different
    answers - and an empty listing already means the first.
    """


class Takings(BaseModel):
    """What was taken over a window, per currency.

    A mapping rather than an amount, because a shop paid in two currencies has
    two amounts and no total. Empty means nothing was taken - a quiet window,
    which is a fact - and is not the same as the source being unreadable,
    which is `None` from the call that would have produced this.
    """

    amounts: dict[str, Decimal]


def taken_between(started_at: datetime,
                  ended_at: datetime,
                  charges: Charges) -> Takings | None:
    """What the shop took between two instants, per currency.

    `None` where the provider could not be read at all. That distinction is
    the port's whole purpose: a payment provider that is down must not become
    a postmortem reporting that the incident cost nothing.
    """
    taken: dict[str, Decimal] = {}

    # Folded as it arrives rather than collected first. What a listing costs to
    # hold is the window's size, and the window here is the incident's - a busy
    # shop's whole week of takings, to produce this handful of sums. The order
    # it arrives in does not matter, because every charge in the window is
    # summed: this is the consumer that lets the listing state its order rather
    # than guarantee one. The fold is inside the try because a drawn listing
    # fails where it is drawn: the provider going unreadable half way through
    # arrives here, not at the call above it. A part-summed window is still no
    # answer, so it leaves as `None` however far it got.
    #
    # **Do not wrap this in `list(...)`.** It reads as harmless and no test can
    # catch it: what it costs is peak memory, and this function exposes only a
    # total, so collecting the listing first and folding it as it arrives are
    # indistinguishable through the public API. The adapter's own laziness is
    # tested; this half is held by nothing but this comment, and undoing it
    # puts a week of a shop's charges back in memory with every suite green.
    try:
        for charge in charges(started_at, ended_at):
            if not charge.succeeded:
                continue

            kept = charge.amount - charge.refunded
            taken[charge.currency] = taken.get(charge.currency, Decimal(0)) + kept
    except RevenueUnavailable:
        logger.warning("revenue provider unreadable", exc_info=True)
        return None

    return Takings(amounts=taken)
