"""How a conversion into the reporting currency is said, made or not.

The loss converts takings and the response's price converts pay bands, both at
the day's rates, and a reader checking either figure needs the same three
things: which currency, at what rate, and which day's table. Said once, here,
so the postmortem's assumptions and the synopsis's basis say a conversion in
the same words, and whatever reads a line back finds it by the same label. A
conversion that could not be made is said once too, for the same reason.
"""

from __future__ import annotations

from incident_cost.sources import RateTable

# How a conversion announces itself, one line per currency converted. Money
# reaches a figure through a rate, and a figure converted at a rate nobody can
# see is a figure nobody can check.
EXCHANGE_RATE_ASSUMPTION_LABEL = "Exchange rate"

# Why a currency could not be converted. Two reasons rather than one, because
# they send a reader to two different places: a provider that publishes no rate
# for a currency is a fact about the currency, and a table nobody could fetch is
# a fact about the read. Told the first when the second happened, a reader goes
# hunting for a currency the provider covers perfectly well.
NO_RATE_PUBLISHED_REASON = "no rate was published for it"
RATES_UNAVAILABLE_REASON = "the exchange rate source could not be read"


def a_conversion_said(currency: str, rates: RateTable) -> str:
    """`currency`'s conversion at `rates`, which must hold a rate for it."""
    return (f"{EXCHANGE_RATE_ASSUMPTION_LABEL}: {currency.upper()} converted at "
            f"{rates.per_unit[currency]} per {rates.base.upper()}, published "
            f"{rates.on.isoformat()}")
