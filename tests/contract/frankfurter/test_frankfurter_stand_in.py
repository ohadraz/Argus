"""Whether the stand-in still answers as Frankfurter does.

Every suite that converts a loss into another currency reads its rates from the
Target Service's stand-in at `/frankfurter`. What none of them can say is
whether Frankfurter itself answers the adapter's question the way the stand-in
does - the path, the parameter the base travels in, the fields a table is kept
under, the status a base it does not know comes back with. That is checked
here against the real service, which costs nothing and needs no key: the same
question asked of both through the adapter, and the two answers required to
read the same.

Read the same rather than equal. The stand-in's rates are a fixture's and
Frankfurter's are the European Central Bank's for the last working day; the
figures will never agree and nothing depends on their agreeing. What everything
depends on is that a table comes back keyed as Argus keys currencies, without
a row for its own base, and quoting nothing Frankfurter does not - a stand-in
quoting a currency the ECB never publishes would let a conversion succeed in
every suite and find no rate in production.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from argus_core import get_settings
from argus_core.models import PublishedRates, RatesUnavailable
from argus_testkit import (
    Assertion,
    Scenario,
    all_of,
    an_error_was_raised,
    attempting,
)
from exchange_rate_source import rates_published_for
from exchange_rate_source.frankfurter import ExchangeRateSettings

# Where each half answers. The real one is the public service; the stand-in is
# wherever Argus itself is configured to read rates from.
FRANKFURTER_ITSELF = "https://api.frankfurter.dev"
THE_STAND_IN = get_settings().exchange_rate_base_url

# The shop's own currency, and so the base a postmortem converts from.
A_BASE_BOTH_QUOTE = "usd"

# A code shaped like a currency's and belonging to none - ISO 4217 reserves
# `XXX` for "no currency", so no table will ever be quoted against it.
NO_SUCH_CURRENCY = "xxx"


@pytest.mark.contract
def test_a_table_frankfurter_publishes_reads_as_the_stand_in_reads_one() -> None:
    # The whole of the happy path, and the one a postmortem takes whenever a
    # shop was paid in more than one currency.
    Scenario() \
        .given(A_BASE_BOTH_QUOTE) \
        .when(lambda: rates_published_for(A_BASE_BOTH_QUOTE, _settings_for(FRANKFURTER_ITSELF))) \
        .then(all_of(
            _it_was_published_by_today(),
            _it_reads_as(rates_published_for(A_BASE_BOTH_QUOTE, _settings_for(THE_STAND_IN)))
        ))


@pytest.mark.contract
def test_a_base_frankfurter_does_not_quote_is_refused_as_the_stand_in_refuses_it() -> None:
    # The refusal the adapter reads: a postmortem whose rates could not be had
    # falls back to an earlier day's, and it can only do that if this comes
    # back as `RatesUnavailable` rather than as a table of nothing.
    Scenario() \
        .given(NO_SUCH_CURRENCY) \
        .when(attempting(
            lambda: rates_published_for(NO_SUCH_CURRENCY, _settings_for(FRANKFURTER_ITSELF))
        )) \
        .then(all_of(
            an_error_was_raised(RatesUnavailable),
            _it_was_refused_as(attempting(
                lambda: rates_published_for(NO_SUCH_CURRENCY, _settings_for(THE_STAND_IN))
            )())
        ))


def _settings_for(base_url: str) -> ExchangeRateSettings:
    """Refuses a stand-in configured as the real one - which is the code's own
    default - since the two halves would then be one service compared with
    itself, which passes and proves nothing."""
    if base_url == THE_STAND_IN == FRANKFURTER_ITSELF:
        raise AssertionError(
            f"Expected EXCHANGE_RATE_BASE_URL to name the stand-in, it names "
            f"Frankfurter itself [{FRANKFURTER_ITSELF}]."
        )

    return ExchangeRateSettings(exchange_rate_base_url=base_url)


def _it_was_published_by_today() -> Assertion[PublishedRates]:
    """The day a table belongs to is the day it was published, which is never
    a day still to come."""
    def assertion(rates: PublishedRates) -> bool:
        today = datetime.now(UTC).date()

        if rates.on > today:
            raise AssertionError(
                f"Expected a table published by [{today}], it was dated [{rates.on}]."
            )

        return True

    return assertion


def _it_reads_as(at_the_stand_in: PublishedRates) -> Assertion[PublishedRates]:
    """The two tables, as the adapter reads them.

    The same base, no row for it on either side, and no currency the stand-in
    quotes that Frankfurter does not. Not the same rates, and not the same
    set: the stand-in quotes what the shop is paid in, and Frankfurter quotes
    everything the ECB publishes.
    """
    def assertion(from_frankfurter: PublishedRates) -> bool:
        if from_frankfurter.base != at_the_stand_in.base:
            raise AssertionError(
                f"Expected the stand-in's base read as Frankfurter's [{from_frankfurter.base}], "
                f"it was read as [{at_the_stand_in.base}]."
            )

        for table, said_by in ((from_frankfurter, "Frankfurter"),
                               (at_the_stand_in, "the stand-in")):
            if table.base in table.per_unit:
                raise AssertionError(
                    f"Expected no rate for the base [{table.base}] itself, "
                    f"{said_by} quoted one."
                )

        never_published = set(at_the_stand_in.per_unit) - set(from_frankfurter.per_unit)

        if never_published:
            raise AssertionError(
                f"Expected the stand-in to quote only what Frankfurter does, "
                f"it quoted {sorted(never_published)} as well."
            )

        return True

    return assertion


def _it_was_refused_as(at_the_stand_in: Exception | None) -> Assertion[Exception | None]:
    """The two refusals, as the adapter reads them: the same error. Not the
    same sentence - the status line inside it is whoever refused's own."""
    def assertion(from_frankfurter: Exception | None) -> bool:
        real = type(from_frankfurter).__name__
        stood_in = type(at_the_stand_in).__name__

        if real != stood_in:
            raise AssertionError(
                f"Expected the stand-in to refuse as Frankfurter did [{real}], "
                f"it refused [{stood_in}]: [{at_the_stand_in}]."
            )

        return True

    return assertion
