"""An amount of money in the one spelling every reader says it in.

The page, the brief and the narration all state the customer loss, and three
spellings of one figure read as three figures - worse where they round it
differently, and disagree in the last cent.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from argus_core.models import said_as_money
from argus_testkit import Scenario, the_answer_was


@pytest.mark.unit
def test_money_is_said_to_two_places_with_its_thousands_grouped_and_its_currency_after() -> None:
    Scenario() \
        .given(
            some_loss := Decimal("1736.68485900091116011163646")
        ) \
        .when(
            lambda: said_as_money(some_loss, "usd")
        ) \
        .then(
            the_answer_was("1,736.68 USD")
        )


@pytest.mark.unit
def test_half_a_cent_rounds_up() -> None:
    # As a till rounds, not as a statistician does: a reader checking the
    # figure by hand rounds half up, and a figure rounding half to even would
    # disagree with them whenever the cent below is even.
    Scenario() \
        .given(
            some_amount := Decimal("1297.325")
        ) \
        .when(
            lambda: said_as_money(some_amount, "usd")
        ) \
        .then(
            the_answer_was("1,297.33 USD")
        )


@pytest.mark.unit
def test_a_whole_amount_still_says_its_cents() -> None:
    Scenario() \
        .given(
            some_amount := Decimal("500")
        ) \
        .when(
            lambda: said_as_money(some_amount, "usd")
        ) \
        .then(
            the_answer_was("500.00 USD")
        )


@pytest.mark.unit
def test_an_amount_nobody_said_the_currency_of_is_said_alone() -> None:
    # Unlabelled rather than labelled with a guess: a currency invented for it
    # is a figure in somebody else's money.
    Scenario() \
        .given(
            some_amount := Decimal("500")
        ) \
        .when(
            lambda: said_as_money(some_amount, None)
        ) \
        .then(
            the_answer_was("500.00")
        )
