"""The money an incident is costed from, as the questions asked of it.

Each is stated as the question the costing has, not as anything a provider
offers - *what did the service take between these two times*, *what is a
title's time worth* - and none of them names a payment processor, a rate
provider, an HR system or any other vendor, nor does anything above them.

They are ports rather than clients, so that the question is Argus's and the
answer is a vendor's: each is answered by an adapter in a package of its own,
wired in by the process that writes the document, and nothing here knows which
one answered.

`None` from any of them is "could not be read", never "there was nothing". The
difference is the whole point of the type: a revenue source that is down must
not become a postmortem reporting that the incident cost nothing.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel

# What the service took between two instants, per currency, or `None` if
# nobody could say. A mapping rather than an amount because a shop paid in two
# currencies has two figures and no total: producing one needs a rate, a rate
# has a date, and both are disclosures this document has to make rather than
# something a source may fold in on the way past.
type Revenue = Callable[[datetime, datetime], Mapping[str, Decimal] | None]


class RateTable(BaseModel):
    """One day's exchange rates, and the currency they are quoted against.

    `base` is what the document reports in. It lives here rather than beside
    the reporting-currency setting because a rate only means anything against
    the currency it was quoted for, and holding the two apart would let a
    figure be converted at one anchor and published as another.

    `on` is the day the rates were published, never the day the incident
    happened: rates move, an estimate is written afterwards, and a reader
    checking the arithmetic needs to know which day's number was used.
    """

    base: str
    on: date
    # How many units of each currency one unit of `base` buys.
    per_unit: Mapping[str, Decimal]


# The rates to convert with, or `None` if none could be had - neither fetched
# now nor held from an earlier day.
type Rates = Callable[[], RateTable | None]


class PayBand(BaseModel):
    """What one job title's time is worth a year, as an HR source states it.

    Three figures rather than one: a band is a range, and a midpoint published
    alone claims a precision the source does not have. The currency travels
    with them because a figure without one is not a figure.

    Argus's own type rather than a vendor's: the costing states what it needs,
    and whichever HR system answers is mapped into this by its own adapter -
    the same arrangement `RateTable` has with the rate provider.
    """

    minimum: Decimal
    midpoint: Decimal
    maximum: Decimal
    currency: str


# What every job title an HR source prices is worth, or `None` if nobody could
# say. The whole table at once, because a source publishes it that way and an
# incident prices several titles from one read.
type PayBands = Callable[[], Mapping[str, PayBand] | None]


@dataclass(frozen=True)
class MoneySources:
    """Every source of money an incident is costed from, and the two settings
    read with them.

    One value rather than three ports and two settings, because a deployment
    configures them once and they are the same for every incident it costs.

    `working_hours_a_year` belongs with them despite being a number rather than
    a port. It is what the annual bands are divided by, so it is read from the
    same configuration at the same moment as the source that publishes them,
    and a figure computed under one working year and disclosed under another is
    the failure this keeps impossible.

    `reporting_currency` is here on the same terms, and for a second reason: it
    is what the rate source was asked to quote against, so a table that arrives
    and the currency it was wanted in cannot be configured apart. It is also the
    only thing left saying which money a figure is when no table arrives at all.
    """

    revenue: Revenue
    rates: Rates
    bands: PayBands
    working_hours_a_year: float
    reporting_currency: str
