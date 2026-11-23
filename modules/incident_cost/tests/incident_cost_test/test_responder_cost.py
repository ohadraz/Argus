"""What the response cost, title by title and in all, out of minutes already
measured by title and bands already published.

The headline is the midpoint, because that is the figure a reader puts beside
the customer loss. The range is beside it, because a band is a range: the same
incident with the same people costs meaningfully more at the top of it, and a
midpoint published alone claims a precision the source does not have.

The numbers here are chosen to divide exactly. A working year of 2000 hours is
120,000 minutes, so a band of 120,000 a year is worth one unit a minute - and
an arithmetic slip shows up as a different figure rather than as a rounding
argument.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from argus_testkit import Assertion, Scenario, all_of
from incident_cost.responder_cost import PricedMinutes, ResponderCost, responder_cost
from incident_cost.sources import PayBand

from incident_cost_test.framework.builders import Share

MINUTES_PER_HOUR = 60
SOME_WORKING_YEAR_IN_HOURS = 2000.0
SOME_WORKING_YEAR_IN_MINUTES = Decimal(SOME_WORKING_YEAR_IN_HOURS) * MINUTES_PER_HOUR

SOME_TITLE = "Senior Kuki"
SOME_OTHER_TITLE = "Junior Buki"
SOME_TITLE_NO_BAND_COVERS = "Principal Buki"


SOME_CURRENCY = "usd"

# 60,000 / 120,000 / 240,000 a year over a 120,000-minute year: half a unit, one
# unit and two units a minute.
SOME_BAND = PayBand(
    minimum=Decimal(60_000),
    midpoint=Decimal(120_000),
    maximum=Decimal(240_000),
    currency=SOME_CURRENCY
)

# Twice the first band at every point, so a figure built from one band applied
# to both titles is a different number rather than a coincidence.
SOME_OTHER_BAND = PayBand(
    minimum=Decimal(120_000),
    midpoint=Decimal(240_000),
    maximum=Decimal(480_000),
    currency=SOME_CURRENCY
)


@pytest.mark.unit
def test_a_titles_minutes_are_priced_at_its_band() -> None:
    # One title, one band, and the figures a synopsis carries: what it cost,
    # and how much that figure could move without anybody being wrong.
    some_minutes = 30
    priced = PricedMinutes(
        midpoint=SOME_BAND.midpoint * some_minutes / SOME_WORKING_YEAR_IN_MINUTES,
        minimum=SOME_BAND.minimum * some_minutes / SOME_WORKING_YEAR_IN_MINUTES,
        maximum=SOME_BAND.maximum * some_minutes / SOME_WORKING_YEAR_IN_MINUTES)

    Scenario() \
        .given(
            a_share := Share(title=SOME_TITLE, minutes=some_minutes)
        ) \
        .when(
            lambda: responder_cost([a_share],
                                   bands={SOME_TITLE: SOME_BAND},
                                   working_hours_a_year=SOME_WORKING_YEAR_IN_HOURS)
        ) \
        .then(all_of(
            _the_titles_were_priced_at([priced]),
            _the_total_was(priced),
            _the_currency_was(SOME_CURRENCY)
        ))


@pytest.mark.unit
def test_two_titles_on_different_bands_are_priced_separately_and_added_up() -> None:
    # The reason the minutes arrive by title. One rate over the total would
    # charge a junior's hour at a senior's band, or the other way round, and
    # the total is the same either way - so only two different bands can tell
    # the arithmetic apart.
    some_minutes = 30
    some_other_minutes = 45
    priced = PricedMinutes(
        midpoint=SOME_BAND.midpoint * some_minutes / SOME_WORKING_YEAR_IN_MINUTES,
        minimum=SOME_BAND.minimum * some_minutes / SOME_WORKING_YEAR_IN_MINUTES,
        maximum=SOME_BAND.maximum * some_minutes / SOME_WORKING_YEAR_IN_MINUTES)
    other_priced = PricedMinutes(
        midpoint=SOME_OTHER_BAND.midpoint * some_other_minutes / SOME_WORKING_YEAR_IN_MINUTES,
        minimum=SOME_OTHER_BAND.minimum * some_other_minutes / SOME_WORKING_YEAR_IN_MINUTES,
        maximum=SOME_OTHER_BAND.maximum * some_other_minutes / SOME_WORKING_YEAR_IN_MINUTES)
    added_up = PricedMinutes(midpoint=priced.midpoint + other_priced.midpoint,
                             minimum=priced.minimum + other_priced.minimum,
                             maximum=priced.maximum + other_priced.maximum)

    Scenario() \
        .given(
            a_share := Share(title=SOME_TITLE, minutes=some_minutes),
            another_share := Share(title=SOME_OTHER_TITLE, minutes=some_other_minutes)
        ) \
        .when(
            lambda: responder_cost([a_share, another_share],
                                   bands={SOME_TITLE: SOME_BAND,
                                          SOME_OTHER_TITLE: SOME_OTHER_BAND},
                                   working_hours_a_year=SOME_WORKING_YEAR_IN_HOURS)
        ) \
        .then(all_of(
            _the_titles_were_priced_at([priced, other_priced]),
            _the_total_was(added_up)
        ))


@pytest.mark.unit
def test_a_response_nobody_made_cost_nothing() -> None:
    # Zero, not absent. A response nobody made really did cost nothing in
    # people's time, and that is a measurement - the same distinction the loss
    # estimate makes between a window read and one that could not be.
    nothing = PricedMinutes(midpoint=Decimal(0), minimum=Decimal(0), maximum=Decimal(0))

    Scenario() \
        .when(
            lambda: responder_cost([],
                                   bands={SOME_TITLE: SOME_BAND},
                                   working_hours_a_year=SOME_WORKING_YEAR_IN_HOURS)
        ) \
        .then(all_of(
            _the_titles_were_priced_at([]),
            _the_total_was(nothing),
            _the_currency_was(None)
        ))


@pytest.mark.unit
def test_a_title_no_band_covers_is_unpriced_and_leaves_the_total_absent() -> None:
    # Not the priced title's share on its own. A cost covering one of two
    # titles is not a smaller cost, it is a wrong one - and it is wrong in the
    # direction that flatters the response, which is the one nobody questions.
    # The priced title's row still says what it cost, and the bands' currency
    # is still theirs.
    some_minutes = 30
    dont_care_minutes = 45
    priced = PricedMinutes(
        midpoint=SOME_BAND.midpoint * some_minutes / SOME_WORKING_YEAR_IN_MINUTES,
        minimum=SOME_BAND.minimum * some_minutes / SOME_WORKING_YEAR_IN_MINUTES,
        maximum=SOME_BAND.maximum * some_minutes / SOME_WORKING_YEAR_IN_MINUTES)

    Scenario() \
        .given(
            a_priced_share := Share(title=SOME_TITLE, minutes=some_minutes),
            a_share_no_band_covers := Share(title=SOME_TITLE_NO_BAND_COVERS,
                                            minutes=dont_care_minutes)
        ) \
        .when(
            lambda: responder_cost([a_priced_share, a_share_no_band_covers],
                                   bands={SOME_TITLE: SOME_BAND},
                                   working_hours_a_year=SOME_WORKING_YEAR_IN_HOURS)
        ) \
        .then(all_of(
            _the_titles_were_priced_at([priced, None]),
            _the_total_was(None),
            _the_currency_was(SOME_CURRENCY)
        ))


@pytest.mark.unit
def test_a_share_the_source_held_no_title_for_is_unpriced() -> None:
    # The case the on-call source really produces: a provider that would not
    # say what somebody was. They spent the minutes all the same, and no band
    # can match a title nobody knows - so the figure goes, exactly as it does
    # for a title no band covers.
    dont_care_minutes = 30

    Scenario() \
        .given(
            a_share_with_no_title := Share(title=None, minutes=dont_care_minutes)
        ) \
        .when(
            lambda: responder_cost([a_share_with_no_title],
                                   bands={SOME_TITLE: SOME_BAND},
                                   working_hours_a_year=SOME_WORKING_YEAR_IN_HOURS)
        ) \
        .then(all_of(
            _the_titles_were_priced_at([None]),
            _the_total_was(None),
            _the_currency_was(None)
        ))


@pytest.mark.unit
def test_the_working_year_a_band_is_divided_by_changes_the_figure() -> None:
    # The divisor is configuration, so it has to be honoured rather than
    # assumed. A shorter working year means each minute of it is worth more of
    # the same salary - and an implementation that hardcoded 2080 would pass
    # every other test in this file.
    some_minutes = 30
    some_shorter_working_year_in_hours = SOME_WORKING_YEAR_IN_HOURS / 2
    a_shorter_year_in_minutes = SOME_WORKING_YEAR_IN_MINUTES / 2
    priced = PricedMinutes(
        midpoint=SOME_BAND.midpoint * some_minutes / a_shorter_year_in_minutes,
        minimum=SOME_BAND.minimum * some_minutes / a_shorter_year_in_minutes,
        maximum=SOME_BAND.maximum * some_minutes / a_shorter_year_in_minutes)

    Scenario() \
        .given(
            a_share := Share(title=SOME_TITLE, minutes=some_minutes)
        ) \
        .when(
            lambda: responder_cost([a_share],
                                   bands={SOME_TITLE: SOME_BAND},
                                   working_hours_a_year=some_shorter_working_year_in_hours)
        ) \
        .then(all_of(
            _the_total_was(priced)
        ))


def _the_titles_were_priced_at(expected: list[PricedMinutes | None]) -> Assertion[ResponderCost]:
    def assertion(cost: ResponderCost) -> bool:
        if cost.by_title != expected:
            raise AssertionError(
                f"Expected the titles priced at {expected}, got {cost.by_title}.")

        return True

    return assertion


def _the_total_was(expected: PricedMinutes | None) -> Assertion[ResponderCost]:
    def assertion(cost: ResponderCost) -> bool:
        if cost.total != expected:
            raise AssertionError(
                f"Expected the response to cost [{expected}] in all, got [{cost.total}].")

        return True

    return assertion


def _the_currency_was(expected: str | None) -> Assertion[ResponderCost]:
    def assertion(cost: ResponderCost) -> bool:
        if cost.currency != expected:
            raise AssertionError(
                f"Expected the cost in [{expected}], got [{cost.currency}].")

        return True

    return assertion
