from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from argus_testkit import Assertion, Scenario, all_of
from revenue_source import Charge, RevenueUnavailable, taken_between

"""What the shop took over a window, as the payment provider reports it.

What this suite injects is the listing itself rather than a hand-built client,
in the vocabulary the port is written in: `Charge` is Argus's word for one, so
a charge written here is the same object a real provider's adapter produces.
The request path - pagination, the base address, the credential - and the
reading of Stripe's own status strings and minor units are exercised where the
adapter answers for them, not here.
"""

SOME_CURRENCY = "usd"
SOME_OTHER_CURRENCY = "eur"


@pytest.mark.unit
def test_what_was_taken_is_the_succeeded_charges_less_what_was_refunded() -> None:
    # A refund issued while the shop was failing is part of what the failure
    # cost, so it comes off the figure rather than being counted separately or
    # ignored. Two charges rather than one, because a sum of a single item
    # would pass on an implementation that returns the first thing it sees.
    some_window_start = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)
    some_window_end = some_window_start + timedelta(hours=1)
    some_charge = Decimal("30.00")
    some_larger_charge = Decimal("12.50")
    some_refund_of_the_larger_charge = Decimal("2.50")


    Scenario() \
        .given(
            charges := [
                _a_charge(of=some_charge),
                _a_charge(of=some_larger_charge,
                          refunded=some_refund_of_the_larger_charge)
            ]
        ) \
        .when(
            lambda: taken_between(some_window_start, some_window_end,
                                  charges=_a_listing_of(*charges))
        ) \
        .then(
            all_of(
                _the_takings_were(
                    some_charge + some_larger_charge
                    - some_refund_of_the_larger_charge,
                    in_currency=SOME_CURRENCY,
                ),
                _no_other_currency_was_reported()
            )
        )


@pytest.mark.unit
def test_money_the_shop_never_kept_is_not_revenue() -> None:
    # A charge that did not succeed was never taken - it failed, or it is still
    # pending and may never arrive; which of the two is the provider's word for
    # it, and the adapter's to read. It sits in the same listing as the money
    # that did arrive, so summing the window would report takings the shop
    # never had, and every figure resting on it would be high by that much.
    some_window_start = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)
    some_window_end = some_window_start + timedelta(hours=1)
    some_charge_that_went_through = Decimal("40.00")
    dont_care_amount = Decimal("99.00")

    Scenario() \
        .given(
            charges := [
                _a_charge(of=some_charge_that_went_through),
                _a_charge(of=dont_care_amount, succeeded=False)
            ]
        ) \
        .when(
            lambda: taken_between(some_window_start, some_window_end,
                                  charges=_a_listing_of(*charges))
        ) \
        .then(
            _the_takings_were(some_charge_that_went_through,
                              in_currency=SOME_CURRENCY)
        )


@pytest.mark.unit
def test_a_window_in_which_nothing_sold_is_not_the_same_as_no_answer() -> None:
    # A quiet hour is a fact about the shop; an unreadable provider is a fact
    # about Argus. The estimate that rests on this treats them differently -
    # one is a real zero, the other is a figure that must not be published -
    # so the difference has to survive the adapter.
    some_window_start = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)
    some_window_end = some_window_start + timedelta(hours=1)
    no_charges: list[Charge] = []

    Scenario() \
        .given(
            no_charges
        ) \
        .when(
            lambda: taken_between(some_window_start, some_window_end,
                                  charges=_a_listing_of(*no_charges))
        ) \
        .then(
            _nothing_was_taken()
        )


@pytest.mark.unit
def test_a_provider_that_cannot_be_reached_answers_that_it_could_not_say() -> None:
    # Not the vendor's error: the fetch that imports the SDK turns it into this
    # module's own, so nothing above the port has to know which library failed.
    some_window_start = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)
    some_window_end = some_window_start + timedelta(hours=1)

    Scenario() \
        .given(
            a_provider_that_is_down := _a_listing_that_fails
        ) \
        .when(
            lambda: taken_between(some_window_start, some_window_end,
                                  charges=a_provider_that_is_down())
        ) \
        .then(
            _could_not_be_read()
        )


@pytest.mark.unit
def test_a_window_paid_in_two_currencies_reports_both_and_totals_neither() -> None:
    # The shop takes a minority of its orders in a second currency, so this is
    # the ordinary case rather than an edge one. Both figures are reported
    # under their own names and neither is folded into the other: adding them
    # needs a rate, a rate has a date, and both are disclosures belonging to
    # the document - not something an adapter may decide silently on its way
    # past. A sum here would be indistinguishable from a measurement.
    some_window_start = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)
    some_window_end = some_window_start + timedelta(hours=1)
    some_charge_at_home = Decimal("24.00")
    some_charge_abroad = Decimal("21.00")

    Scenario() \
        .given(
            charges := [
                _a_charge(of=some_charge_at_home, currency=SOME_CURRENCY),
                _a_charge(of=some_charge_abroad, currency=SOME_OTHER_CURRENCY)
            ]
        ) \
        .when(
            lambda: taken_between(some_window_start, some_window_end,
                                  charges=_a_listing_of(*charges))
        ) \
        .then(
            all_of(
                _the_takings_were(some_charge_at_home, in_currency=SOME_CURRENCY),
                _the_takings_were(some_charge_abroad,
                                  in_currency=SOME_OTHER_CURRENCY),
                _the_currencies_reported_were(SOME_CURRENCY, SOME_OTHER_CURRENCY)
            )
        )


def _the_currencies_reported_were(*expected: str) -> Assertion[Any]:
    """Exactly these, and nothing standing for their sum.

    The count is the assertion. A shop paid in two currencies whose takings
    come back as one figure has had a rate applied by something that never
    said which.
    """
    def assertion(taken: Any) -> bool:
        if taken is None:
            raise AssertionError(
                f"Expected takings in {sorted(expected)}, but nothing was reported.")

        if sorted(taken.amounts) != sorted(expected):
            raise AssertionError(
                f"Expected takings in {sorted(expected)}, but what was reported "
                f"was {sorted(taken.amounts)}.")

        return True

    return assertion


def _a_listing_that_fails() -> Callable[[datetime, datetime], Iterable[Charge]]:
    def listing(dont_care_from: datetime, dont_care_until: datetime) -> Iterable[Charge]:
        raise RevenueUnavailable("the payment provider could not be reached")

    return listing


def _nothing_was_taken() -> Assertion[Any]:
    def assertion(taken: Any) -> bool:
        if taken is None:
            raise AssertionError(
                "Expected an answer of nothing taken, but the source reported "
                "that it could not be read at all."
            )

        if taken.amounts:
            raise AssertionError(
                f"Expected nothing taken, but {dict(taken.amounts)} was reported."
            )

        return True

    return assertion


def _could_not_be_read() -> Assertion[Any]:
    def assertion(taken: Any) -> bool:
        if taken is not None:
            raise AssertionError(
                f"Expected the source to report that it could not be read, but "
                f"it answered {taken}."
            )

        return True

    return assertion


def _a_charge(of: Decimal,
              refunded: Decimal = Decimal(0),
              currency: str = SOME_CURRENCY,
              succeeded: bool = True) -> Charge:
    """One charge as the port carries it - money rather than minor units, and
    a refunded total on the charge itself rather than as a separate object."""
    return Charge(succeeded=succeeded,
                  currency=currency,
                  amount=of,
                  refunded=refunded)


def _a_listing_of(*charges: Charge) -> Callable[[datetime, datetime], Iterable[Charge]]:
    def listing(dont_care_from: datetime, dont_care_until: datetime) -> Iterable[Charge]:
        return charges

    return listing


def _the_takings_were(amount: Decimal, in_currency: str) -> Assertion[Any]:
    def assertion(taken: Any) -> bool:
        if taken is None:
            raise AssertionError(
                f"Expected [{amount}] {in_currency}, but nothing was reported "
                f"as taken at all."
            )

        if taken.amounts.get(in_currency) != amount:
            raise AssertionError(
                f"Expected [{amount}] {in_currency}, but what was reported was "
                f"{dict(taken.amounts)}."
            )

        return True

    return assertion


def _no_other_currency_was_reported() -> Assertion[Any]:
    def assertion(taken: Any) -> bool:
        others = [currency for currency in taken.amounts if currency != SOME_CURRENCY]

        if others:
            raise AssertionError(
                f"Expected only [{SOME_CURRENCY}], but {others} were reported too."
            )

        return True

    return assertion
