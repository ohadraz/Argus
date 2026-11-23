"""What the response cost, priced for the synopsis from the postmortem's
minutes by title.

The arithmetic is `incident_cost`'s and is tested there; what is under test
here is that the synopsis reads the bands once, keeps every row the postmortem
held, and leaves the totals absent wherever a row went unpriced.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from argus_testkit import Assertion, Kept, Scenario, all_of
from core.models import PricedResponse, TitleCost, TitleMinutes
from executive_synopsis.synopsis_pricing import the_response_priced
from incident_cost import (
    PAY_BAND_ASSUMPTION_LABEL,
    PAY_BANDS_UNAVAILABLE_ASSUMPTION,
    UNPRICED_TITLE_ASSUMPTION_LABEL,
    PayBand,
    Rates,
)

from executive_synopsis_test.framework.builders import (
    SOME_CURRENCY,
    SOME_OTHER_CURRENCY,
    a_band_source_counting_reads_into,
    a_band_source_pricing,
    a_band_source_that_cannot_answer,
    rates_published,
    some_money,
)

SOME_TITLE = "Senior Kuki"
SOME_OTHER_TITLE = "Junior Buki"
SOME_TITLE_NO_BAND_COVERS = "Principal Buki"

# A working year of 2,000 hours is 120,000 minutes, so a band whose midpoint
# is that many prices a minute at one - at half that at its bottom, and twice
# at its top.
WORKING_YEAR = 2000.0
MINUTES_A_WORKING_YEAR = Decimal(WORKING_YEAR) * 60
A_BAND = PayBand(minimum=MINUTES_A_WORKING_YEAR / 2, midpoint=MINUTES_A_WORKING_YEAR,
                 maximum=MINUTES_A_WORKING_YEAR * 2, currency=SOME_CURRENCY)
# Twice the first at every point, so one band applied to both titles is a
# different total rather than a coincidence.
ANOTHER_BAND = PayBand(minimum=MINUTES_A_WORKING_YEAR, midpoint=MINUTES_A_WORKING_YEAR * 2,
                       maximum=MINUTES_A_WORKING_YEAR * 4, currency=SOME_CURRENCY)
# The first band's figures, paid in another currency at two to one of the
# reporting currency - so a conversion that multiplied would double the price
# where the right one halves it.
A_FOREIGN_BAND = A_BAND.model_copy(update={"currency": SOME_OTHER_CURRENCY})
A_RATE = Decimal(2)

TWO_SENIORS = TitleMinutes(title=SOME_TITLE, responders=2, minutes=30)
ONE_JUNIOR = TitleMinutes(title=SOME_OTHER_TITLE, responders=1, minutes=15)


@pytest.mark.unit
def test_each_title_is_priced_at_its_band_and_the_response_in_all() -> None:
    seniors = Decimal(TWO_SENIORS.minutes)
    junior = Decimal(ONE_JUNIOR.minutes)
    seniors_priced = TitleCost(**TWO_SENIORS.model_dump(),
                               midpoint=seniors, minimum=seniors / 2, maximum=seniors * 2)
    junior_priced = TitleCost(**ONE_JUNIOR.model_dump(),
                              midpoint=junior * 2, minimum=junior, maximum=junior * 4)

    Scenario() \
        .given(
            some_bands := some_money(
                bands=a_band_source_pricing({SOME_TITLE: A_BAND, SOME_OTHER_TITLE: ANOTHER_BAND}),
                working_hours_a_year=WORKING_YEAR)
        ) \
        .when(
            lambda: the_response_priced([TWO_SENIORS, ONE_JUNIOR], some_bands)
        ) \
        .then(
            all_of(
                _priced_by_title_as([seniors_priced, junior_priced]),
                _priced_in_all_at(seniors + junior * 2, seniors / 2 + junior,
                                  seniors * 2 + junior * 4),
                _priced_in(SOME_CURRENCY),
                _based_on_a_line_mentioning(PAY_BAND_ASSUMPTION_LABEL, SOME_TITLE)
            )
        )


@pytest.mark.unit
def test_a_title_no_band_covers_keeps_its_row_unpriced_and_leaves_no_total() -> None:
    # Its people and minutes are still known, and the priced title still says
    # what it cost - but a total missing one of them would be wrong in the
    # flattering direction.
    some_unpriced_title = TitleMinutes(title=SOME_TITLE_NO_BAND_COVERS, responders=1,
                                       minutes=15)
    seniors = Decimal(TWO_SENIORS.minutes)
    seniors_priced = TitleCost(**TWO_SENIORS.model_dump(),
                               midpoint=seniors, minimum=seniors / 2, maximum=seniors * 2)
    left_unpriced = TitleCost(**some_unpriced_title.model_dump(),
                              midpoint=None, minimum=None, maximum=None)

    Scenario() \
        .given(
            some_bands := some_money(bands=a_band_source_pricing({SOME_TITLE: A_BAND}),
                                     working_hours_a_year=WORKING_YEAR)
        ) \
        .when(
            lambda: the_response_priced([TWO_SENIORS, some_unpriced_title], some_bands)
        ) \
        .then(
            all_of(
                _priced_by_title_as([seniors_priced, left_unpriced]),
                _priced_in_all_at(None, None, None),
                _based_on_a_line_mentioning(UNPRICED_TITLE_ASSUMPTION_LABEL,
                                            SOME_TITLE_NO_BAND_COVERS)
            )
        )


@pytest.mark.unit
@pytest.mark.parametrize(("band", "rates", "expected_total"), [
    # Read with no rates at all, so a price here owes the rate source nothing.
    pytest.param(A_BAND, None, Decimal(TWO_SENIORS.minutes),
                 id="a band in the reporting currency"),
    pytest.param(A_FOREIGN_BAND, rates_published({SOME_OTHER_CURRENCY: A_RATE}),
                 Decimal(TWO_SENIORS.minutes) / A_RATE,
                 id="a band in another currency, with a rate"),
    pytest.param(A_FOREIGN_BAND, rates_published({}), None,
                 id="a band in another currency, with no rate")
])
def test_the_response_is_priced_in_all_only_where_every_band_reaches_the_reporting_currency(
        band: PayBand, rates: Rates | None, expected_total: Decimal | None) -> None:
    # What decides whether the overview may name the response's cost at all.
    Scenario() \
        .given(
            some_money_paid := some_money(bands=a_band_source_pricing({SOME_TITLE: band}),
                                          rates=rates,
                                          working_hours_a_year=WORKING_YEAR)
        ) \
        .when(
            lambda: the_response_priced([TWO_SENIORS], some_money_paid)
        ) \
        .then(
            _estimated_at(expected_total)
        )


@pytest.mark.unit
def test_bands_that_cannot_be_read_leave_every_row_unpriced_and_say_so() -> None:
    left_unpriced = TitleCost(**TWO_SENIORS.model_dump(),
                              midpoint=None, minimum=None, maximum=None)

    Scenario() \
        .given(
            no_bands := some_money(bands=a_band_source_that_cannot_answer())
        ) \
        .when(
            lambda: the_response_priced([TWO_SENIORS], no_bands)
        ) \
        .then(
            all_of(
                _priced_by_title_as([left_unpriced]),
                _priced_in_all_at(None, None, None),
                _based_on([PAY_BANDS_UNAVAILABLE_ASSUMPTION])
            )
        )


@pytest.mark.unit
def test_a_response_nobody_made_reads_no_band_and_prices_nothing() -> None:
    # Nobody responded, or nobody could say who did: the postmortem holds no
    # minutes by title, and there is nothing to price or to say of pricing.
    reads: Kept[None] = Kept()

    Scenario() \
        .given(
            some_bands := some_money(bands=a_band_source_counting_reads_into(reads))
        ) \
        .when(
            lambda: the_response_priced([], some_bands)
        ) \
        .then(
            all_of(
                _priced_as(PricedResponse()),
                _the_bands_were_read_times(reads, 0)
            )
        )


@pytest.mark.unit
def test_the_bands_are_read_once_for_every_title() -> None:
    reads: Kept[None] = Kept()

    Scenario() \
        .given(
            some_bands := some_money(bands=a_band_source_counting_reads_into(reads))
        ) \
        .when(
            lambda: the_response_priced([TWO_SENIORS, ONE_JUNIOR], some_bands)
        ) \
        .then(
            _the_bands_were_read_times(reads, 1)
        )


def _priced_by_title_as(expected: list[TitleCost]) -> Assertion[PricedResponse]:
    def assertion(priced: PricedResponse) -> bool:
        if priced.cost_by_title != expected:
            raise AssertionError(
                f"Expected the response priced by title as {expected}, "
                f"got {priced.cost_by_title}.")

        return True

    return assertion


def _priced_in_all_at(midpoint: Decimal | None,
                      minimum: Decimal | None,
                      maximum: Decimal | None) -> Assertion[PricedResponse]:
    def assertion(priced: PricedResponse) -> bool:
        got = (priced.responder_cost_estimate, priced.responder_cost_minimum,
               priced.responder_cost_maximum)
        if got != (midpoint, minimum, maximum):
            raise AssertionError(
                f"Expected the response priced in all at [{midpoint}] from [{minimum}] "
                f"to [{maximum}], got [{got[0]}] from [{got[1]}] to [{got[2]}].")

        return True

    return assertion


def _estimated_at(expected: Decimal | None) -> Assertion[PricedResponse]:
    def assertion(priced: PricedResponse) -> bool:
        if priced.responder_cost_estimate != expected:
            raise AssertionError(
                f"Expected the response estimated at [{expected}], "
                f"got [{priced.responder_cost_estimate}].")

        return True

    return assertion


def _priced_in(expected: str) -> Assertion[PricedResponse]:
    def assertion(priced: PricedResponse) -> bool:
        if priced.responder_cost_currency != expected:
            raise AssertionError(
                f"Expected the response priced in [{expected}], "
                f"got [{priced.responder_cost_currency}].")

        return True

    return assertion


def _based_on_a_line_mentioning(label: str, detail: str) -> Assertion[PricedResponse]:
    def assertion(priced: PricedResponse) -> bool:
        if not any(label in line and detail in line for line in priced.response_cost_basis):
            raise AssertionError(
                f"Expected a line of the basis mentioning [{label}] and [{detail}], "
                f"got {priced.response_cost_basis}.")

        return True

    return assertion


def _based_on(expected: list[str]) -> Assertion[PricedResponse]:
    def assertion(priced: PricedResponse) -> bool:
        if priced.response_cost_basis != expected:
            raise AssertionError(f"Expected the basis {expected}, "
                                 f"got {priced.response_cost_basis}.")

        return True

    return assertion


def _priced_as(expected: PricedResponse) -> Assertion[PricedResponse]:
    def assertion(priced: PricedResponse) -> bool:
        if priced != expected:
            raise AssertionError(f"Expected the response priced as [{expected}], "
                                 f"got [{priced}].")

        return True

    return assertion


def _the_bands_were_read_times(reads: Kept[None], expected: int) -> Assertion[PricedResponse]:
    def assertion(_: PricedResponse) -> bool:
        if len(reads.taken) != expected:
            raise AssertionError(f"Expected the bands read {expected} times, "
                                 f"got {len(reads.taken)}.")

        return True

    return assertion
