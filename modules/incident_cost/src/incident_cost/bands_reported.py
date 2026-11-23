"""Each responding title's pay band, in the currency the incident is reported in.

A band is published in whatever its holders are paid in, and a response priced
in two currencies has no total: adding a euro to a dollar needs a rate, a rate
has a date, and both are disclosures. So every band a response is priced at is
converted into the reporting currency first, at the day's rates, as the
takings are (`loss`). A band no rate converts is left out, and its title goes
unpriced: counted at par, it would publish a figure that looks measured and is
not.

The rates are read only when a band needs them. A response whose responders
are all paid in the reporting currency asks the rate source nothing, so a rate
source that cannot be read leaves its price as it was.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal

from pydantic import BaseModel

from incident_cost.responder_cost import TitleShare
from incident_cost.sources import PayBand, Rates, RateTable


class BandsReported(BaseModel):
    """The bands a response is priced at, and what became of each on the way.

    `bands` holds each responding title a band covers and a conversion reached,
    in the reporting currency. `unconverted` holds each responding title whose
    band is in another currency that no rate converted, with that currency.

    `rates` is the table the conversions were read from: `None` where no band
    needed one, or where one was needed and none could be read - `unconverted`
    tells the two apart. `converted` names each currency converted, in the
    order the titles responded, so each conversion is said once.
    """

    bands: dict[str, PayBand]
    unconverted: dict[str, str]
    rates: RateTable | None
    converted: list[str]


def bands_reported(shares: Sequence[TitleShare],
                   bands: Mapping[str, PayBand],
                   reporting_currency: str,
                   rates: Rates) -> BandsReported:
    """The bands `shares` are priced at, in `reporting_currency`.

    Only the responding titles' bands, because only theirs are used: a band in
    another currency nobody responded under needs no rate, and its conversion
    would be disclosed for a figure it never entered.
    """
    used = {share.title: bands[share.title] for share in shares
            if share.title is not None and share.title in bands}
    needs_a_rate = any(band.currency != reporting_currency for band in used.values())
    table = rates() if needs_a_rate else None

    reported: dict[str, PayBand] = {}
    unconverted: dict[str, str] = {}
    converted: list[str] = []
    for title, band in used.items():
        if band.currency == reporting_currency:
            reported[title] = band
        elif table is not None and band.currency in table.per_unit:
            reported[title] = _converted(band, table.per_unit[band.currency], reporting_currency)
            if band.currency not in converted:
                converted.append(band.currency)
        else:
            unconverted[title] = band.currency

    return BandsReported(bands=reported, unconverted=unconverted, rates=table,
                         converted=converted)


def _converted(band: PayBand, per_unit: Decimal, reporting_currency: str) -> PayBand:
    # Divided, not multiplied: the rate is how many of the band's currency one
    # unit of the reporting currency buys.
    return PayBand(minimum=band.minimum / per_unit,
                   midpoint=band.midpoint / per_unit,
                   maximum=band.maximum / per_unit,
                   currency=reporting_currency)
