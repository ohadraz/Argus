"""Each responding title's pay band, in the currency the incident is reported in.

A response priced in two currencies has no total, so a band in another currency
is converted at the day's rates before it prices anything, and a band no rate
converts is left out rather than counted at par. The rates are read only when a
band needs them, so a response paid wholly in the reporting currency is priced
whatever the rate source is doing.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from argus_testkit import Assertion, Kept, Scenario, all_of
from incident_cost.bands_reported import BandsReported, bands_reported
from incident_cost.sources import PayBand, Rates, RateTable

from incident_cost_test.framework.builders import (
    DONT_CARE_RATE_DATE,
    SOME_CURRENCY,
    SOME_OTHER_CURRENCY,
    Share,
    rates_published,
    rates_recording_each_read_into,
    rates_that_cannot_be_read,
)

SOME_TITLE = "Senior Kuki"
SOME_OTHER_TITLE = "Junior Buki"
DONT_CARE_MINUTES = 30

A_BAND = PayBand(minimum=Decimal(60_000), midpoint=Decimal(120_000),
                 maximum=Decimal(240_000), currency=SOME_CURRENCY)
# The same figures, paid in another currency: what a conversion makes of them
# is then the rate's doing alone.
A_FOREIGN_BAND = A_BAND.model_copy(update={"currency": SOME_OTHER_CURRENCY})
# Two of the other currency to one of the reporting one, so a conversion that
# multiplied would double the band where the right one halves it.
SOME_RATE = Decimal(2)


@pytest.mark.unit
def test_a_band_in_the_reporting_currency_is_kept_as_published_and_reads_no_rates() -> None:
    reads: Kept[RateTable] = Kept()

    Scenario() \
        .given(
            some_rates := rates_recording_each_read_into(reads, base=SOME_CURRENCY)
        ) \
        .when(
            lambda: bands_reported([Share(title=SOME_TITLE, minutes=DONT_CARE_MINUTES)],
                                   {SOME_TITLE: A_BAND}, SOME_CURRENCY, some_rates)
        ) \
        .then(
            all_of(
                _reported_as({SOME_TITLE: A_BAND}),
                _nothing_converted(),
                _the_rates_were_read_times(reads, 0)
            )
        )


@pytest.mark.unit
def test_a_band_in_another_currency_is_converted_at_its_rate() -> None:
    converted = PayBand(minimum=A_BAND.minimum / SOME_RATE,
                        midpoint=A_BAND.midpoint / SOME_RATE,
                        maximum=A_BAND.maximum / SOME_RATE,
                        currency=SOME_CURRENCY)

    Scenario() \
        .given(
            some_rates := rates_published(on=DONT_CARE_RATE_DATE,
                                          per_unit={SOME_OTHER_CURRENCY: SOME_RATE},
                                          base=SOME_CURRENCY)
        ) \
        .when(
            lambda: bands_reported([Share(title=SOME_TITLE, minutes=DONT_CARE_MINUTES)],
                                   {SOME_TITLE: A_FOREIGN_BAND}, SOME_CURRENCY, some_rates)
        ) \
        .then(
            all_of(
                _reported_as({SOME_TITLE: converted}),
                _converted([SOME_OTHER_CURRENCY]),
                _left_unconverted({})
            )
        )


@pytest.mark.unit
@pytest.mark.parametrize("some_rates", [
    pytest.param(rates_published(on=DONT_CARE_RATE_DATE, per_unit={}, base=SOME_CURRENCY),
                 id="no rate published for it"),
    pytest.param(rates_that_cannot_be_read(), id="the rates could not be read")
])
def test_a_band_no_rate_converts_is_left_out_with_its_currency(some_rates: Rates) -> None:
    # Counted at par, it would publish a figure that looks measured and is not.
    Scenario() \
        .when(
            lambda: bands_reported([Share(title=SOME_TITLE, minutes=DONT_CARE_MINUTES),
                                    Share(title=SOME_OTHER_TITLE, minutes=DONT_CARE_MINUTES)],
                                   {SOME_TITLE: A_FOREIGN_BAND, SOME_OTHER_TITLE: A_BAND},
                                   SOME_CURRENCY, some_rates)
        ) \
        .then(
            all_of(
                _reported_as({SOME_OTHER_TITLE: A_BAND}),
                _left_unconverted({SOME_TITLE: SOME_OTHER_CURRENCY}),
                _converted([])
            )
        )


@pytest.mark.unit
def test_a_band_nobody_responded_under_is_neither_converted_nor_reported() -> None:
    # Its conversion would be disclosed for a figure it never entered.
    reads: Kept[RateTable] = Kept()

    Scenario() \
        .given(
            some_rates := rates_recording_each_read_into(reads, base=SOME_CURRENCY)
        ) \
        .when(
            lambda: bands_reported([Share(title=SOME_TITLE, minutes=DONT_CARE_MINUTES)],
                                   {SOME_TITLE: A_BAND, SOME_OTHER_TITLE: A_FOREIGN_BAND},
                                   SOME_CURRENCY, some_rates)
        ) \
        .then(
            all_of(
                _reported_as({SOME_TITLE: A_BAND}),
                _nothing_converted(),
                _the_rates_were_read_times(reads, 0)
            )
        )


def _reported_as(expected: dict[str, PayBand]) -> Assertion[BandsReported]:
    def assertion(reported: BandsReported) -> bool:
        if reported.bands != expected:
            raise AssertionError(f"Expected the bands reported as {expected}, "
                                 f"got {reported.bands}.")

        return True

    return assertion


def _converted(expected: list[str]) -> Assertion[BandsReported]:
    def assertion(reported: BandsReported) -> bool:
        if reported.converted != expected:
            raise AssertionError(f"Expected {expected} converted, got {reported.converted}.")

        return True

    return assertion


def _left_unconverted(expected: dict[str, str]) -> Assertion[BandsReported]:
    def assertion(reported: BandsReported) -> bool:
        if reported.unconverted != expected:
            raise AssertionError(f"Expected {expected} left unconverted, "
                                 f"got {reported.unconverted}.")

        return True

    return assertion


def _nothing_converted() -> Assertion[BandsReported]:
    def assertion(reported: BandsReported) -> bool:
        if reported.converted or reported.unconverted or reported.rates is not None:
            raise AssertionError(
                f"Expected no conversion and no rates, got {reported.converted} converted, "
                f"{reported.unconverted} left unconverted and rates {reported.rates}.")

        return True

    return assertion


def _the_rates_were_read_times(reads: Kept[RateTable],
                               expected: int) -> Assertion[BandsReported]:
    def assertion(_: BandsReported) -> bool:
        if len(reads.taken) != expected:
            raise AssertionError(f"Expected the rates read {expected} times, "
                                 f"got {len(reads.taken)}.")

        return True

    return assertion
