"""One incident's window, and the money sources it is costed from.

Every case that costs an incident needs three sources answering and two
settings before it reaches anything it is about. So the window is fixed here,
and each builder is written to be asked for the one thing its test cares
about: what a test does not name, it does not care about - which is what makes
the thing it does name visible.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from argus_testkit import Kept
from incident_cost import MoneySources, PayBand, PayBands, Rates, RateTable, Revenue

# One incident, from its onset to the minute it was measured until.
ONSET = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)
ENDED_AT = ONSET + timedelta(minutes=30)

AN_HOUR = timedelta(hours=1)

SOME_CURRENCY = "usd"
SOME_OTHER_CURRENCY = "eur"
SOME_UNPRICED_CURRENCY = "kuki"

DONT_CARE_HOURLY_REVENUE = 4_800
DONT_CARE_REVENUE_DURING_THE_INCIDENT = Decimal("100.00")
DONT_CARE_WORKING_YEAR = 2080.0
DONT_CARE_RATE_DATE = date(2026, 9, 2)


def some_money(revenue: Revenue | None = None,
               rates: Rates | None = None,
               bands: PayBands | None = None,
               working_hours_a_year: float = DONT_CARE_WORKING_YEAR,
               reporting_currency: str = SOME_CURRENCY) -> MoneySources:
    """Every source of money, with each answering plainly.

    A test names only the source it is about and leaves the others alone, which
    is what makes the failure it describes attributable to the source it named.
    """
    return MoneySources(
        revenue=revenue if revenue is not None
                else revenue_that_was(
                    per_hour={SOME_CURRENCY: DONT_CARE_HOURLY_REVENUE},
                    until=ONSET,
                    and_then={SOME_CURRENCY: DONT_CARE_REVENUE_DURING_THE_INCIDENT}),
        rates=rates if rates is not None else rates_in(SOME_CURRENCY),
        bands=bands if bands is not None else a_band_source_pricing({}),
        working_hours_a_year=working_hours_a_year,
        reporting_currency=reporting_currency
    )


def revenue_that_was(per_hour: Mapping[str, float],
                     until: datetime,
                     and_then: Mapping[str, Decimal]) -> Revenue:
    """A service with two different afternoons.

    Before `until` it takes a steady rate, so any window asked for answers in
    proportion to its length - which is what lets a baseline window go
    unnamed by any test. From `until` onwards it takes one fixed sum, because
    that window is the incident and the incident happened once.
    """
    def revenue_between(window_start: datetime,
                        window_end: datetime) -> Mapping[str, Decimal] | None:
        if window_start >= until:
            return dict(and_then)

        return {
            currency: Decimal(rate * (window_end - window_start) / AN_HOUR)
            for currency, rate in per_hour.items()
        }

    return revenue_between


def a_revenue_source_that_cannot_answer() -> Revenue:
    """A source that is reachable in the type and not in fact - `None` rather
    than an exception, since an unreadable source is an ordinary outcome."""
    def revenue_between(dont_care_start: datetime,
                        dont_care_end: datetime) -> Mapping[str, Decimal] | None:
        return None

    return revenue_between


def revenue_recording_the_windows_into(windows: Kept[tuple[datetime, datetime]]) -> Revenue:
    """A revenue source noting each window it was asked for, and answering
    that nothing was taken - what is asked of it is the question."""
    def revenue_between(window_start: datetime,
                        window_end: datetime) -> Mapping[str, Decimal] | None:
        windows.take((window_start, window_end))

        return {}

    return revenue_between


def rates_in(base: str) -> Rates:
    """A rate table in the currency the revenue is already in, and no rate for
    anything else: the table is here only to say which currency is reported."""
    return rates_published(on=DONT_CARE_RATE_DATE, per_unit={}, base=base)


def rates_published(on: date, per_unit: Mapping[str, Decimal], base: str) -> Rates:
    """A rate table as the source would hand one over."""
    def rates() -> RateTable | None:
        return RateTable(base=base, on=on, per_unit=per_unit)

    return rates


def rates_recording_each_read_into(reads: Kept[RateTable], base: str) -> Rates:
    """A rate table in `base` with no rates in it, noting each time it is
    handed over - whether it was asked for is the question."""
    table = RateTable(base=base, on=DONT_CARE_RATE_DATE, per_unit={})

    def rates() -> RateTable | None:
        reads.take(table)

        return table

    return rates


def rates_that_cannot_be_read() -> Rates:
    """No table at all, which is not the same as a table with no rates in it."""
    def rates() -> RateTable | None:
        return None

    return rates


def a_band_source_pricing(bands: Mapping[str, PayBand]) -> PayBands:
    def pay_bands() -> Mapping[str, PayBand] | None:
        return bands

    return pay_bands


def hours_between(start: datetime, end: datetime) -> float:
    """The span, worked out here rather than asked of the code under test.

    A test computing its expectation the way the code does would agree with it
    however wrong both were.
    """
    return (end - start) / timedelta(hours=1)
