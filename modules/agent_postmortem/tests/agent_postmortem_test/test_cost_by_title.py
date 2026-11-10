"""The response's cost one title at a time, for the executive synopsis.

The same arithmetic as `responder_cost`, kept apart by title rather than added
into one figure - so the rows and the postmortem's total are the same minutes at
the same bands, and add up to it.

The numbers divide exactly, as in `test_responder_cost`: a band whose midpoint
is the working year in minutes is one unit a minute at its midpoint.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from agent_postmortem.cost_by_title import cost_by_title
from agent_postmortem.responder_cost import responder_cost
from agent_postmortem.sources import EngagedResponder, PayBand
from argus_core.models import TitleCost
from argus_testkit import Assertion, Scenario

A_CENT = Decimal("0.01")
MINUTES_PER_HOUR = 60
SOME_WORKING_YEAR_IN_HOURS = 2000.0
SOME_WORKING_YEAR_IN_MINUTES = Decimal(SOME_WORKING_YEAR_IN_HOURS) * MINUTES_PER_HOUR

SOME_TITLE = "Senior Kuki"
SOME_OTHER_TITLE = "Junior Buki"
SOME_TITLE_NO_BAND_COVERS = "Principal Buki"

DONT_CARE_CURRENCY = "USD"

SOME_BAND = PayBand(
    minimum=SOME_WORKING_YEAR_IN_MINUTES / 2,
    midpoint=SOME_WORKING_YEAR_IN_MINUTES,
    maximum=SOME_WORKING_YEAR_IN_MINUTES * 2,
    currency=DONT_CARE_CURRENCY
)

SOME_OTHER_BAND = PayBand(
    minimum=SOME_BAND.minimum * 2,
    midpoint=SOME_BAND.midpoint * 2,
    maximum=SOME_BAND.maximum * 2,
    currency=DONT_CARE_CURRENCY
)


@pytest.mark.unit
def test_two_people_on_one_title_are_one_row() -> None:
    # One band, so one row: the synopsis prices a title, never a person.
    some_responders = [EngagedResponder(minutes=30, job_title=SOME_TITLE),
                       EngagedResponder(minutes=12, job_title=SOME_TITLE)]

    Scenario() \
        .given(
            some_responders
        ) \
        .when(
            lambda: cost_by_title(some_responders, {SOME_TITLE: SOME_BAND},
                                  SOME_WORKING_YEAR_IN_HOURS)
        ) \
        .then(
            _the_rows_were([_a_row_priced_at(SOME_TITLE, SOME_BAND, held_by=some_responders)])
        )


@pytest.mark.unit
def test_each_title_is_a_row_in_the_order_it_first_responded() -> None:
    # The order a reader matching the rows against the timeline reads them in.
    some_first_responder = EngagedResponder(minutes=10, job_title=SOME_OTHER_TITLE)
    some_second_responder = EngagedResponder(minutes=20, job_title=SOME_TITLE)
    some_third_responder = EngagedResponder(minutes=5, job_title=SOME_OTHER_TITLE)
    some_responders = [some_first_responder, some_second_responder, some_third_responder]

    Scenario() \
        .given(
            some_responders
        ) \
        .when(
            lambda: cost_by_title(some_responders,
                                  {SOME_TITLE: SOME_BAND, SOME_OTHER_TITLE: SOME_OTHER_BAND},
                                  SOME_WORKING_YEAR_IN_HOURS)
        ) \
        .then(
            _the_rows_were([
                _a_row_priced_at(SOME_OTHER_TITLE, SOME_OTHER_BAND,
                                 held_by=[some_first_responder, some_third_responder]),
                _a_row_priced_at(SOME_TITLE, SOME_BAND, held_by=[some_second_responder])
            ])
        )


@pytest.mark.unit
def test_a_responder_with_no_title_is_a_row_of_their_own_and_unpriced() -> None:
    # Left out, the rows would no longer add up to everyone who responded.
    some_titled_responder = EngagedResponder(minutes=20, job_title=SOME_TITLE)
    some_untitled_responder = EngagedResponder(minutes=7, job_title=None)
    some_responders = [some_titled_responder, some_untitled_responder]

    Scenario() \
        .given(
            some_responders
        ) \
        .when(
            lambda: cost_by_title(some_responders, {SOME_TITLE: SOME_BAND},
                                  SOME_WORKING_YEAR_IN_HOURS)
        ) \
        .then(
            _the_rows_were([
                _a_row_priced_at(SOME_TITLE, SOME_BAND, held_by=[some_titled_responder]),
                _an_unpriced_row(None, held_by=[some_untitled_responder])
            ])
        )


@pytest.mark.unit
def test_a_title_no_band_covers_keeps_its_people_and_minutes_and_no_cost() -> None:
    # Unpriced is not free: no amount, never zero.
    some_responders = [EngagedResponder(minutes=9, job_title=SOME_TITLE_NO_BAND_COVERS)]

    Scenario() \
        .given(
            some_responders
        ) \
        .when(
            lambda: cost_by_title(some_responders, {SOME_TITLE: SOME_BAND},
                                  SOME_WORKING_YEAR_IN_HOURS)
        ) \
        .then(
            _the_rows_were([
                _an_unpriced_row(SOME_TITLE_NO_BAND_COVERS, held_by=some_responders)
            ])
        )


@pytest.mark.unit
def test_the_rows_add_up_to_the_postmortems_cost() -> None:
    # The minutes and bands are odd on purpose, so the amounts do not divide
    # exactly. Compared to the cent: grouping adds the same terms in another
    # order, and 28 digits of Decimal can differ in the last one.
    some_responders = [EngagedResponder(minutes=7, job_title=SOME_TITLE),
                       EngagedResponder(minutes=13, job_title=SOME_OTHER_TITLE),
                       EngagedResponder(minutes=11, job_title=SOME_TITLE)]
    some_bands = {
        SOME_TITLE: PayBand(minimum=Decimal(70_001), midpoint=Decimal(93_337),
                            maximum=Decimal(116_673), currency=DONT_CARE_CURRENCY),
        SOME_OTHER_TITLE: PayBand(minimum=Decimal(110_003), midpoint=Decimal(140_009),
                                  maximum=Decimal(170_017), currency=DONT_CARE_CURRENCY)
    }
    the_postmortems_cost = responder_cost(some_responders, some_bands,
                                          SOME_WORKING_YEAR_IN_HOURS)

    Scenario() \
        .given(
            some_responders
        ) \
        .when(
            lambda: cost_by_title(some_responders, some_bands, SOME_WORKING_YEAR_IN_HOURS)
        ) \
        .then(
            _the_rows_add_up_to(
                the_postmortems_cost.midpoint if the_postmortems_cost else None,
                the_postmortems_cost.minimum if the_postmortems_cost else None,
                the_postmortems_cost.maximum if the_postmortems_cost else None)
        )


@pytest.mark.unit
def test_nobody_responding_is_no_rows() -> None:
    Scenario() \
        .when(
            lambda: cost_by_title([], {SOME_TITLE: SOME_BAND}, SOME_WORKING_YEAR_IN_HOURS)
        ) \
        .then(
            _the_rows_were([])
        )


def _a_row_priced_at(title: str,
                     band: PayBand,
                     *,
                     held_by: list[EngagedResponder]) -> TitleCost:
    """The row of `title`, counting the people in `held_by` and their minutes,
    priced at `band`."""
    minutes = sum(responder.minutes for responder in held_by)

    return TitleCost(
        title=title,
        responders=len(held_by),
        minutes=minutes,
        midpoint=band.midpoint * minutes / SOME_WORKING_YEAR_IN_MINUTES,
        minimum=band.minimum * minutes / SOME_WORKING_YEAR_IN_MINUTES,
        maximum=band.maximum * minutes / SOME_WORKING_YEAR_IN_MINUTES
    )


def _an_unpriced_row(title: str | None, *, held_by: list[EngagedResponder]) -> TitleCost:
    """The row of `title`, counting the people in `held_by` and their minutes,
    with nothing to price them at."""
    return TitleCost(title=title,
                     responders=len(held_by),
                     minutes=sum(responder.minutes for responder in held_by),
                     midpoint=None,
                     minimum=None,
                     maximum=None)


def _the_rows_were(expected: list[TitleCost]) -> Assertion[list[TitleCost]]:
    def assertion(rows: list[TitleCost]) -> bool:
        if rows != expected:
            raise AssertionError(f"Expected the rows {expected}, got {rows}.")

        return True

    return assertion


def _the_rows_add_up_to(midpoint: Decimal | None,
                        minimum: Decimal | None,
                        maximum: Decimal | None) -> Assertion[list[TitleCost]]:
    def assertion(rows: list[TitleCost]) -> bool:
        summed = tuple(sum((getattr(row, amount) for row in rows), start=Decimal(0))
                       .quantize(A_CENT)
                       for amount in ("midpoint", "minimum", "maximum"))
        expected = tuple(amount.quantize(A_CENT) if amount is not None else None
                         for amount in (midpoint, minimum, maximum))

        if summed != expected:
            raise AssertionError(
                f"Expected the rows to add up to the postmortem's midpoint, minimum and "
                f"maximum {expected} to the cent, got {summed}.")

        return True

    return assertion
