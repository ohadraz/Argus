"""What the outage cost the business, read off the takings and converted at
the day's rates.

The loss is a subtraction between sums a payment provider reported - the
incident's own hours against the same hours whole weeks earlier, beyond how far
those differ from the same hours as far back again - and every case here is
arithmetic over money. Nothing asks a model anything: a figure a model could be
talked out of is not a measurement.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from argus_testkit import Assertion, Kept, Scenario, all_of
from incident_cost.loss import LossEstimate, beyond_the_variation, estimate_loss
from incident_cost.sources import RateTable, Revenue

from incident_cost_test.framework.builders import (
    ENDED_AT,
    ONSET,
    SOME_CURRENCY,
    SOME_OTHER_CURRENCY,
    SOME_UNPRICED_CURRENCY,
    a_revenue_source_that_cannot_answer,
    hours_between,
    rates_published,
    rates_recording_each_read_into,
    rates_that_cannot_be_read,
    revenue_recording_the_windows_into,
    revenue_that_was,
    some_money,
)

SOME_CALM_HOURLY_REVENUE = 1_200
SOME_REVENUE_DURING_THE_INCIDENT = Decimal("100.00")

A_WEEK = timedelta(weeks=1)


@pytest.mark.unit
def test_a_shop_that_took_more_than_before_lost_nothing_rather_than_less_than_nothing() -> None:
    # A quiet stretch before a busy incident. The subtraction goes negative and
    # the answer does not: a negative loss is not a small loss, it is a
    # category error, and zero here is a measurement rather than an absence.
    some_busier_incident_s_shortfall = Decimal("-800")
    some_shop_that_never_varies = Decimal(0)

    Scenario() \
        .when(
            lambda: beyond_the_variation(some_busier_incident_s_shortfall,
                                         some_shop_that_never_varies)
        ) \
        .then(
            _estimates(Decimal(0))
        )


@pytest.mark.unit
def test_a_shortfall_no_larger_than_the_shop_s_own_variation_is_no_loss() -> None:
    # Two calm stretches back to back differ by some amount on their own. A
    # shortfall inside that is the shop being the shop - and scaled out over a
    # week it became six figures nobody lost.
    some_variation = Decimal("300")
    some_shortfall_within_it = Decimal("250")

    Scenario() \
        .when(
            lambda: beyond_the_variation(some_shortfall_within_it, some_variation)
        ) \
        .then(
            _estimates(Decimal(0))
        )


@pytest.mark.unit
def test_a_shortfall_beyond_the_shop_s_own_variation_is_lost_in_full() -> None:
    # Not less the variation: the variation says whether anything was lost,
    # and the shortfall says how much.
    some_variation = Decimal("300")
    some_shortfall_beyond_it = Decimal("4500")

    Scenario() \
        .when(
            lambda: beyond_the_variation(some_shortfall_beyond_it, some_variation)
        ) \
        .then(
            _estimates(some_shortfall_beyond_it)
        )


@pytest.mark.unit
def test_the_loss_is_what_the_calm_hour_predicted_less_what_came_in() -> None:
    # The whole estimate, and the only arithmetic in it: the rate the shop was
    # trading at before the onset, scaled to the length of the incident, less
    # what it actually took while it was broken. Both terms are money the
    # payment provider reported.
    expected_loss = (
        Decimal(SOME_CALM_HOURLY_REVENUE)
        * Decimal(str(hours_between(ONSET, ENDED_AT)))
        - SOME_REVENUE_DURING_THE_INCIDENT
    )

    Scenario() \
        .given(
            money := some_money(revenue=revenue_that_was(
                per_hour={SOME_CURRENCY: SOME_CALM_HOURLY_REVENUE},
                until=ONSET,
                and_then={SOME_CURRENCY: SOME_REVENUE_DURING_THE_INCIDENT}))
        ) \
        .when(
            lambda: estimate_loss(ONSET, ENDED_AT, money)
        ) \
        .then(
            all_of(
                _the_loss_was(expected_loss),
                _the_figure_is_in(SOME_CURRENCY)
            )
        )


@pytest.mark.unit
def test_a_shortfall_within_what_the_shop_varies_by_on_its_own_is_no_loss() -> None:
    # Like with like: the incident against as long a stretch just before its
    # onset, and that stretch against the one before it. Here the two calm
    # stretches differ by more than the incident fell short.
    Scenario() \
        .given(
            money := some_money(revenue=_a_shop_taking(earlier=Decimal("1000.00"),
                                                       just_before=Decimal("1300.00"),
                                                       during=Decimal("1100.00")))
        ) \
        .when(
            lambda: estimate_loss(ONSET, ENDED_AT, money)
        ) \
        .then(
            all_of(
                _the_loss_was(Decimal(0)),
                _the_shop_varies_by(Decimal("300.00"))
            )
        )


@pytest.mark.unit
def test_a_shortfall_beyond_what_the_shop_varies_by_is_the_loss() -> None:
    Scenario() \
        .given(
            money := some_money(revenue=_a_shop_taking(earlier=Decimal("1000.00"),
                                                       just_before=Decimal("1100.00"),
                                                       during=Decimal("100.00")))
        ) \
        .when(
            lambda: estimate_loss(ONSET, ENDED_AT, money)
        ) \
        .then(
            _the_loss_was(Decimal("1000.00"))
        )


@pytest.mark.unit
def test_an_incident_with_no_onset_reads_no_takings() -> None:
    # No loss is counted from the alert, so there is nothing to read the takings
    # or the rates for - and takings read for nothing were disclosed as
    # converted at a rate no figure was converted at.
    windows_asked_for: Kept[tuple[datetime, datetime]] = Kept()
    rate_tables_read: Kept[RateTable] = Kept()

    Scenario() \
        .given(
            money := some_money(
                revenue=revenue_recording_the_windows_into(windows_asked_for),
                rates=rates_recording_each_read_into(rate_tables_read, SOME_CURRENCY))
        ) \
        .when(
            lambda: estimate_loss(None, ENDED_AT, money)
        ) \
        .then(all_of(
            _asked_for_the_takings_over([], windows_asked_for),
            _asked_for_no_rate_table(rate_tables_read),
            _read_no_rates()
        ))


@pytest.mark.unit
def test_a_revenue_source_that_cannot_be_read_costs_nothing_rather_than_zero() -> None:
    # Zero here would become a postmortem telling an executive the outage cost
    # them nothing, on the strength of a service Argus failed to reach. Both
    # windows are needed, because a loss is the difference between them - one
    # alone is half a subtraction.
    Scenario() \
        .given(
            money := some_money(revenue=a_revenue_source_that_cannot_answer())
        ) \
        .when(
            lambda: estimate_loss(ONSET, ENDED_AT, money)
        ) \
        .then(
            all_of(
                _nothing_was_costed(),
                _read_no_baseline()
            )
        )


@pytest.mark.unit
def test_takings_abroad_are_converted_at_the_published_rate() -> None:
    # The shop sells abroad, so the baseline hour is partly money that is not
    # in the currency the estimate is reported in. The rates say how many units
    # of a currency one unit of the base buys, so money taken abroad is divided
    # by its rate rather than multiplied - the direction that turns eighty
    # euros into a hundred dollars rather than sixty-four.
    some_calm_hourly_revenue_abroad = 800
    some_revenue_abroad_during_the_incident = Decimal("200.00")
    some_rate = Decimal("0.80")
    expected_loss = (
        Decimal(some_calm_hourly_revenue_abroad) / some_rate
        * Decimal(str(hours_between(ONSET, ENDED_AT)))
        - some_revenue_abroad_during_the_incident / some_rate
    )

    Scenario() \
        .given(
            money := some_money(
                revenue=revenue_that_was(
                    per_hour={
                        SOME_OTHER_CURRENCY: some_calm_hourly_revenue_abroad
                    },
                    until=ONSET,
                    and_then={
                        SOME_OTHER_CURRENCY: some_revenue_abroad_during_the_incident
                    }),
                rates=rates_published(on=ONSET.date(),
                                      per_unit={SOME_OTHER_CURRENCY: some_rate},
                                      base=SOME_CURRENCY))
        ) \
        .when(
            lambda: estimate_loss(ONSET, ENDED_AT, money)
        ) \
        .then(
            all_of(
                _the_loss_was(expected_loss),
                _the_figure_is_in(SOME_CURRENCY)
            )
        )


@pytest.mark.unit
def test_a_currency_the_table_has_no_rate_for_is_left_out_and_named() -> None:
    # The rate provider publishes thirty-odd currencies and a shop may take one
    # it does not cover. Losing the whole figure over the part that cannot be
    # converted would throw away the part that can - and silently dropping it
    # would publish a figure that looks like all the money and is not. So the
    # figure covers what could be converted, and the currency that stopped it
    # is named for whoever writes the disclosure.
    some_calm_hourly_revenue = 1_000
    dont_care_hourly_revenue_that_cannot_be_priced = 400
    dont_care_revenue_that_cannot_be_priced = Decimal("50.00")
    expected_loss = (
        Decimal(some_calm_hourly_revenue)
        * Decimal(str(hours_between(ONSET, ENDED_AT)))
        - SOME_REVENUE_DURING_THE_INCIDENT
    )

    Scenario() \
        .given(
            money := some_money(revenue=revenue_that_was(
                per_hour={
                    SOME_CURRENCY: some_calm_hourly_revenue,
                    SOME_UNPRICED_CURRENCY:
                        dont_care_hourly_revenue_that_cannot_be_priced
                },
                until=ONSET,
                and_then={
                    SOME_CURRENCY: SOME_REVENUE_DURING_THE_INCIDENT,
                    SOME_UNPRICED_CURRENCY: dont_care_revenue_that_cannot_be_priced
                }))
        ) \
        .when(
            lambda: estimate_loss(ONSET, ENDED_AT, money)
        ) \
        .then(
            all_of(
                _the_loss_was(expected_loss),
                _left_out(SOME_UNPRICED_CURRENCY)
            )
        )


@pytest.mark.unit
def test_rates_that_cannot_be_read_still_leave_the_takings_that_needed_no_rate() -> None:
    # A table nobody could read is a table with no rates in it, and the currency
    # the document reports in is configured rather than derived from one. So the
    # figure covers the money that needed no conversion and names every currency
    # that did - the same answer the arithmetic already gives for a single
    # currency the table does not cover. Losing the whole estimate over the part
    # that cannot be converted throws away the part that can.
    some_calm_hourly_revenue = 1_000
    dont_care_hourly_revenue_abroad = 400
    dont_care_revenue_abroad = Decimal("50.00")
    expected_loss = (
        Decimal(some_calm_hourly_revenue)
        * Decimal(str(hours_between(ONSET, ENDED_AT)))
        - SOME_REVENUE_DURING_THE_INCIDENT
    )

    Scenario() \
        .given(
            money := some_money(
                revenue=revenue_that_was(
                    per_hour={
                        SOME_CURRENCY: some_calm_hourly_revenue,
                        SOME_OTHER_CURRENCY: dont_care_hourly_revenue_abroad
                    },
                    until=ONSET,
                    and_then={
                        SOME_CURRENCY: SOME_REVENUE_DURING_THE_INCIDENT,
                        SOME_OTHER_CURRENCY: dont_care_revenue_abroad
                    }),
                rates=rates_that_cannot_be_read())
        ) \
        .when(
            lambda: estimate_loss(ONSET, ENDED_AT, money)
        ) \
        .then(
            all_of(
                _the_loss_was(expected_loss),
                _the_figure_is_in(SOME_CURRENCY),
                _left_out(SOME_OTHER_CURRENCY)
            )
        )


def _estimates(expected: Decimal) -> Assertion[Decimal]:
    def assertion(estimate: Decimal) -> bool:
        if estimate != expected:
            raise AssertionError(f"Expected a loss of [{expected}], got [{estimate}].")

        return True

    return assertion


def _a_shop_taking(earlier: Decimal, just_before: Decimal, during: Decimal) -> Revenue:
    """Three stretches as long as an incident shorter than a week: the incident
    itself, the same hours a week before it, and the same hours a week before
    that - told apart by where each window starts."""
    def revenue_between(window_start: datetime,
                        dont_care_end: datetime) -> Mapping[str, Decimal] | None:
        if window_start >= ONSET:
            return {SOME_CURRENCY: during}

        return {SOME_CURRENCY: just_before if window_start >= ONSET - A_WEEK else earlier}

    return revenue_between


def _left_out(expected: str) -> Assertion[LossEstimate]:
    def assertion(estimated: LossEstimate) -> bool:
        if expected not in estimated.currencies_left_out:
            raise AssertionError(
                f"Expected [{expected}] to be named as left out of the figure, got "
                f"{estimated.currencies_left_out}.")

        return True

    return assertion


def _read_no_baseline() -> Assertion[LossEstimate]:
    def assertion(estimated: LossEstimate) -> bool:
        if estimated.baseline_revenue is not None:
            raise AssertionError(
                f"Expected no baseline where the source could not answer, got "
                f"[{estimated.baseline_revenue}].")

        return True

    return assertion


def _asked_for_no_rate_table(reads: Kept[RateTable]) -> Assertion[LossEstimate]:
    def assertion(dont_care_estimated: LossEstimate) -> bool:
        if reads.taken:
            raise AssertionError(
                f"Expected the rate source not to be asked where no loss is counted, "
                f"got {len(reads.taken)} read(s).")

        return True

    return assertion


def _read_no_rates() -> Assertion[LossEstimate]:
    def assertion(estimated: LossEstimate) -> bool:
        if estimated.rates is not None:
            raise AssertionError(
                f"Expected no rate table read where no loss is counted, got "
                f"[{estimated.rates}].")

        return True

    return assertion


def _the_figure_is_in(expected: str | None) -> Assertion[LossEstimate]:
    def assertion(estimated: LossEstimate) -> bool:
        if estimated.currency != expected:
            raise AssertionError(
                f"Expected a figure in [{expected}], got [{estimated.currency}].")

        return True

    return assertion


def _the_loss_was(expected: Decimal) -> Assertion[LossEstimate]:
    def assertion(estimated: LossEstimate) -> bool:
        if estimated.loss != expected:
            raise AssertionError(
                f"Expected a loss of [{expected}], got [{estimated.loss}].")

        return True

    return assertion


def _the_shop_varies_by(expected: Decimal) -> Assertion[LossEstimate]:
    def assertion(estimated: LossEstimate) -> bool:
        if estimated.variation != expected:
            raise AssertionError(
                f"Expected the two calm stretches to differ by [{expected}], got "
                f"[{estimated.variation}].")

        return True

    return assertion


def _nothing_was_costed() -> Assertion[LossEstimate]:
    def assertion(estimated: LossEstimate) -> bool:
        if estimated.loss is not None:
            raise AssertionError(
                f"Expected no loss where a term of it could not be read, got "
                f"[{estimated.loss}].")

        return True

    return assertion


def _asked_for_the_takings_over(
        expected: list[tuple[datetime, datetime]],
        windows: Kept[tuple[datetime, datetime]]) -> Assertion[LossEstimate]:
    def assertion(dont_care_estimated: LossEstimate) -> bool:
        if sorted(windows.taken) != sorted(expected):
            raise AssertionError(
                f"Expected the takings read over {sorted(expected)}, got "
                f"{sorted(windows.taken)}.")

        return True

    return assertion
