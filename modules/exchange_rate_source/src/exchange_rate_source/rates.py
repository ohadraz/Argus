"""What a day's exchange rates are, before anybody says where they came from.

One table per base currency per day: how many units of each other currency one
unit of the base buys. Rates move, so the day is part of the answer rather than
metadata about it - a figure converted at Tuesday's rate and published as
Wednesday's is a figure nobody can check.

Nothing here reaches a provider. The vocabulary lives apart from the fetching
so that a cached table and a freshly fetched one are the same kind of thing,
which is what lets yesterday's rates stand in for today's when nobody answers.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel


class RatesUnavailable(Exception):
    """No rates could be had - neither fetched now nor held from an earlier day.

    Raised by whatever tried to obtain them, which is where a provider's own
    failures are known by their names. Everything above answers in this
    vocabulary instead, so an HTTP client stops at the module that imports it.

    An exception rather than an empty table, because an empty table would read
    as "every currency is worth nothing" - and a conversion at that rate is
    the kind of silent wrong figure this whole channel exists to avoid.
    """


class PublishedRates(BaseModel):
    """One day's rates against one base currency.

    `on` is the day the provider published them, not the day they were asked
    for. The two differ whenever the answer came from a cache or from a
    weekend, and the document discloses the day the number actually belongs
    to.
    """

    base: str
    on: date
    # How many units of each currency one unit of `base` buys. The base itself
    # is absent: it is always one of itself, and a row saying so is a rate
    # somebody could get wrong.
    per_unit: dict[str, Decimal]
