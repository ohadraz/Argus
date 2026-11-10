"""Whether the cost by title, read again for the synopsis, agrees with the
postmortem's stored totals.

The synopsis reads the minutes and bands a second time rather than changing the
postmortem to hand them over, so a source that moved in between would give rows
that disagree with the totals beside them. Rows that disagree are not shown.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, NamedTuple

import pytest
from agent_postmortem.breakdown import agreeing_breakdown
from argus_core.models import PostmortemDocument, TitleCost
from argus_testkit import Assertion, Scenario

SOME_CURRENCY = "USD"
SOME_OTHER_CURRENCY = "EUR"

SOME_ROWS = [
    TitleCost(title="Senior Kuki", responders=2, minutes=30, midpoint=Decimal("25.00"),
              minimum=Decimal("12.50"), maximum=Decimal("50.00")),
    TitleCost(title="Junior Buki", responders=1, minutes=12, midpoint=Decimal("6.00"),
              minimum=Decimal("3.00"), maximum=Decimal("12.00"))
]

A_CENT = Decimal("0.01")
A_TENTH = Decimal("0.10")


@pytest.mark.unit
def test_rows_that_add_up_to_the_totals_are_shown() -> None:
    a_postmortem = _a_postmortem_costing(_the_totals_of(SOME_ROWS))

    Scenario() \
        .when(
            lambda: agreeing_breakdown(SOME_ROWS, SOME_CURRENCY, a_postmortem)
        ) \
        .then(
            _the_breakdown_was(SOME_ROWS)
        )


@pytest.mark.unit
def test_a_difference_below_a_cent_is_agreement() -> None:
    # Grouping adds the same terms in another order; the last of 28 digits is
    # not a disagreement.
    far_below_a_cent = Decimal("1e-24")
    the_totals = _the_totals_of(SOME_ROWS)
    a_postmortem = _a_postmortem_costing(
        the_totals._replace(midpoint=_moved(the_totals.midpoint, far_below_a_cent)))

    Scenario() \
        .when(
            lambda: agreeing_breakdown(SOME_ROWS, SOME_CURRENCY, a_postmortem)
        ) \
        .then(
            _the_breakdown_was(SOME_ROWS)
        )


@pytest.mark.unit
@pytest.mark.parametrize("total, moved_by", [
    ("responders", 1),
    ("minutes", 1),
    ("midpoint", A_CENT),
    ("minimum", -A_TENTH),
    ("maximum", A_TENTH)
], ids=["people", "minutes", "midpoint", "minimum", "maximum"])
def test_rows_that_disagree_with_any_total_are_not_shown(total: str,
                                                         moved_by: int | Decimal) -> None:
    # A band whose top moved, or a responder who acknowledged after the
    # postmortem was written, gives rows the totals beside them contradict.
    the_totals = _the_totals_of(SOME_ROWS)
    moved: dict[str, Any] = {total: getattr(the_totals, total) + moved_by}
    a_postmortem = _a_postmortem_costing(the_totals._replace(**moved))

    Scenario() \
        .when(
            lambda: agreeing_breakdown(SOME_ROWS, SOME_CURRENCY, a_postmortem)
        ) \
        .then(
            _no_breakdown()
        )


@pytest.mark.unit
def test_rows_in_another_currency_are_not_shown() -> None:
    a_postmortem = _a_postmortem_costing(_the_totals_of(SOME_ROWS))

    Scenario() \
        .when(
            lambda: agreeing_breakdown(SOME_ROWS, SOME_OTHER_CURRENCY, a_postmortem)
        ) \
        .then(
            _no_breakdown()
        )


@pytest.mark.unit
def test_an_unpriced_response_agrees_on_people_and_minutes() -> None:
    # The postmortem published no cost because a title has no band; the rows
    # say which, with the people and minutes still counted.
    some_rows = [SOME_ROWS[0], _unpriced(SOME_ROWS[1])]
    an_unpriced_postmortem = _a_postmortem_costing(_the_totals_of(some_rows))

    Scenario() \
        .when(
            lambda: agreeing_breakdown(some_rows, SOME_CURRENCY, an_unpriced_postmortem)
        ) \
        .then(
            _the_breakdown_was(some_rows)
        )


@pytest.mark.unit
def test_an_unpriced_row_beside_a_priced_total_is_not_shown() -> None:
    # The postmortem priced everyone, so a row nothing could price now means a
    # band went away since.
    some_rows = [SOME_ROWS[0], _unpriced(SOME_ROWS[1])]
    a_postmortem = _a_postmortem_costing(_the_totals_of(SOME_ROWS))

    Scenario() \
        .when(
            lambda: agreeing_breakdown(some_rows, SOME_CURRENCY, a_postmortem)
        ) \
        .then(
            _no_breakdown()
        )


class _Totals(NamedTuple):
    """The response totals a postmortem stores, which the rows must add up to."""

    responders: int
    minutes: int
    midpoint: Decimal | None
    minimum: Decimal | None
    maximum: Decimal | None


def _the_totals_of(rows: list[TitleCost]) -> _Totals:
    """What `rows` add up to - no amount at all where any row is unpriced, as
    the postmortem publishes no cost missing a responder."""
    priced = all(row.midpoint is not None for row in rows)

    def summed(amount: str) -> Decimal | None:
        return sum((getattr(row, amount) for row in rows), start=Decimal(0)) if priced else None

    return _Totals(responders=sum(row.responders for row in rows),
                   minutes=sum(row.minutes for row in rows),
                   midpoint=summed("midpoint"),
                   minimum=summed("minimum"),
                   maximum=summed("maximum"))


def _moved(amount: Decimal | None, by: Decimal) -> Decimal | None:
    return amount + by if amount is not None else None


def _unpriced(row: TitleCost) -> TitleCost:
    """The same people and minutes, with no band to price them at."""
    return row.model_copy(update={"midpoint": None, "minimum": None, "maximum": None})


def _a_postmortem_costing(totals: _Totals) -> PostmortemDocument:
    """A postmortem whose only interesting fields are its response totals."""
    return PostmortemDocument(
        root_cause="dont care",
        executive_summary="dont care",
        customer_loss_estimate=None,
        estimate_currency=None,
        engineer_minutes=totals.minutes,
        responders=totals.responders,
        responder_cost_estimate=totals.midpoint,
        responder_cost_minimum=totals.minimum,
        responder_cost_maximum=totals.maximum,
        responder_cost_currency=SOME_CURRENCY if totals.midpoint is not None else None,
        tokens_spent=None,
        assumptions=[]
    )


def _the_breakdown_was(expected: list[TitleCost]) -> Assertion[list[TitleCost] | None]:
    def assertion(breakdown: list[TitleCost] | None) -> bool:
        if breakdown != expected:
            raise AssertionError(f"Expected the breakdown {expected}, got {breakdown}.")

        return True

    return assertion


def _no_breakdown() -> Assertion[list[TitleCost] | None]:
    def assertion(breakdown: list[TitleCost] | None) -> bool:
        if breakdown is not None:
            raise AssertionError(
                f"Expected no breakdown, since it disagrees with the totals, got {breakdown}.")

        return True

    return assertion
