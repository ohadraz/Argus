"""The one place a rate provider is known by name.

Frankfurter publishes the European Central Bank's daily reference rates: no
key, no account, and one request answers the whole table for a base currency -
thirty-odd rates in under a kilobyte. Asking per currency would be thirty
requests for the same answer.

The rates are the ECB's, which means they are published once on a working day
and do not move again. That is exactly the shape a cache wants, and the reason
the day a table was published is part of the table rather than a detail of the
request.

Nothing above this module imports `httpx`, and nothing above it sees a
transport error: a provider that cannot be read leaves here as
`RatesUnavailable`.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from decimal import Decimal
from typing import Any, Final

import httpx
from argus_core.config import Settings, get_settings

from exchange_rate_source.rates import PublishedRates, RatesUnavailable

# How the request is made. Injected rather than called outright so a test can
# answer with a real `httpx.Response` - the provider's own body, parsed by the
# same code that parses the live one - without a network and without
# monkeypatching a name this module imported.
type Asking = Callable[..., httpx.Response]

# The provider's own query and response vocabulary.
_BASE: Final = "base"
_RATES: Final = "rates"
_PUBLISHED_ON: Final = "date"

# The path that answers with the most recent working day's rates. Not a date of
# our own: asking for "today" on a Sunday answers nothing, where asking for the
# latest answers Friday's - which is what the ECB means by the current rate.
_THE_LATEST_RATES: Final = "/v1/latest"

# Long enough for a provider having a slow morning, short enough that a
# postmortem is not held open by one. A table that does not arrive is not a
# failure to write the document: the rates held from an earlier day stand in.
_A_PATIENT_WAIT: Final = 10.0


def rates_published_for(base: str,
                        settings: Settings | None = None,
                        asking: Asking = httpx.get) -> PublishedRates:
    """The most recent table the provider has, quoted against `base`.

    The whole table, because it is one request either way and a postmortem
    cannot know in advance which currencies a shop was paid in.

    Raises `RatesUnavailable` for anything the provider fails to answer -
    unreachable, slow, or answering in a shape this does not recognise. The
    caller's fallback is an earlier day's rates, and it can only reach for
    them if this says plainly that today's could not be had.
    """
    settings = settings or get_settings()

    try:
        answered = asking(
            f"{settings.exchange_rate_base_url}{_THE_LATEST_RATES}",
            params={_BASE: base.upper()},
            timeout=_A_PATIENT_WAIT
        )
        answered.raise_for_status()

        return _the_table_in(answered.json(), asked_for=base)
    except httpx.HTTPError as error:
        raise RatesUnavailable(
            f"the exchange rate provider could not be read: {error}"
        ) from error


def _the_table_in(answered: dict[str, Any], asked_for: str) -> PublishedRates:
    """The provider's body, read as a table.

    The base comes back as it was asked for rather than as the provider spells
    it: everything above this reads currencies in the payment provider's
    lower case, and a table keyed one way holding a base named the other is a
    conversion that silently finds no rate.

    A body missing either field is a provider answering in a shape this does
    not know, which is the same predicament as one that did not answer.
    """
    try:
        return PublishedRates(
            base=asked_for.lower(),
            on=date.fromisoformat(answered[_PUBLISHED_ON]),
            per_unit={
                currency.lower(): Decimal(str(rate))
                for currency, rate in answered[_RATES].items()
            }
        )
    except (KeyError, TypeError, ValueError) as error:
        raise RatesUnavailable(
            f"the exchange rate provider answered in a shape this cannot "
            f"read: {error}"
        ) from error
