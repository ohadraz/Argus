"""What a job title is worth, in Argus's own terms.

A band and the failure to read one. No vendor's field names, no wire shapes,
nothing that changes when the HR system does - a title, three figures and a
currency are what the rest of Argus asks about, and they are all that lives
here.

Translating some vendor's document into these is an adapter's work, and the
adapter is the only thing that ever knows which vendor it was.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from decimal import Decimal

from pydantic import BaseModel


class PayBandsUnavailable(Exception):
    """The HR source could not be read.

    Raised by the adapter, which is where a vendor's failures are known by
    their own names. Everything above answers in this vocabulary instead, so
    the vendor's client stops at the module that imports it.

    An exception rather than an empty mapping, because "no bands are
    configured" and "nobody could say" are different answers, and only the
    first is a fact about the organisation.
    """


class PayBand(BaseModel):
    """What one compensation level pays.

    Three figures rather than one: a band is a range, and a midpoint published
    alone claims a precision the source does not have. The currency travels
    with them because a figure without one is not a figure.

    `Decimal`, because these are money and they are added up.
    """

    minimum: Decimal
    midpoint: Decimal
    maximum: Decimal
    currency: str


# What every adapter here answers: each job title the source prices, against
# the band of the level it sits on. A mapping rather than a lookup function,
# because the sources publish their whole structure at once and the caller
# prices several titles from one read.
type PayBandsByTitle = Mapping[str, PayBand]

# How the bands are read. Named as a type so the postmortem can hold one
# without importing an adapter, and so a caller can be handed a reading that
# came from somewhere else entirely.
type ReadPayBands = Callable[[], PayBandsByTitle]
