"""How a conversion into the reporting currency is said.

The takings and the pay bands are both converted at the day's rates, and a
reader checking either figure needs the same three things beside it: the
currency, the rate, and the day the rate was published.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from argus_testkit import Assertion, Scenario, all_of
from incident_cost.conversion_said import EXCHANGE_RATE_ASSUMPTION_LABEL, a_conversion_said
from incident_cost.sources import RateTable

from incident_cost_test.framework.builders import SOME_CURRENCY, SOME_OTHER_CURRENCY

SOME_RATE = Decimal("0.92")
SOME_DAY = date(2026, 9, 1)


@pytest.mark.unit
def test_a_conversion_says_its_currency_its_rate_and_the_day_the_rate_was_published() -> None:
    Scenario() \
        .given(
            some_rates := RateTable(base=SOME_CURRENCY, on=SOME_DAY,
                                    per_unit={SOME_OTHER_CURRENCY: SOME_RATE})
        ) \
        .when(
            lambda: a_conversion_said(SOME_OTHER_CURRENCY, some_rates)
        ) \
        .then(
            all_of(
                _mentions(EXCHANGE_RATE_ASSUMPTION_LABEL),
                _mentions(SOME_OTHER_CURRENCY.upper()),
                _mentions(f"{SOME_RATE} per {SOME_CURRENCY.upper()}"),
                _mentions(SOME_DAY.isoformat())
            )
        )


def _mentions(expected: str) -> Assertion[str]:
    def assertion(said: str) -> bool:
        if expected not in said:
            raise AssertionError(f"Expected the conversion to mention [{expected}], "
                                 f"got [{said}].")

        return True

    return assertion
