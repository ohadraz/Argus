from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from argus_core.db import connect
from argus_incidents.repository import exchange_rates
from argus_testkit import Assertion, Scenario, all_of, calling
from exchange_rate_source import PublishedRates

"""Where a day's exchange rates are written down, and read back whole.

Not an incident's table: a rate belongs to a day rather than to an incident,
and every postmortem written that day converts at the same one. What the table
owes its readers is that a day's figures arrive together and come back
together - a partial table is a conversion that silently finds no rate for the
currency the service actually took, and two days mixed into one is a conversion
whose disclosed date is true of only some of its figures.

Rates are never updated, only inserted. A day's reference rate is published
once and does not move, so a second insert for the same day is the same numbers
arriving again - taken as already known rather than as a correction.
"""

SOME_BASE_CURRENCY = "usd"
ANOTHER_BASE_CURRENCY = "gbp"


@pytest.mark.integration
def test_a_days_rates_come_back_as_they_were_written() -> None:
    # Whole, or not at all. Thirty currencies arrive together from one request
    # and a reader converting one of them needs the rest to be there too.
    some_day = date.today()
    what_was_published = _rates(SOME_BASE_CURRENCY,
                                on=some_day,
                                per_unit={"eur": Decimal("0.85"),
                                          "gbp": Decimal("0.79"),
                                          "jpy": Decimal("147.20")})

    with connect() as conn:
        Scenario() \
            .given(calling(lambda: exchange_rates.record(conn, what_was_published))) \
            .when(lambda: exchange_rates.get_latest_for(conn, SOME_BASE_CURRENCY)) \
            .then(_the_rates_held_are(what_was_published))


@pytest.mark.integration
def test_a_base_nothing_was_ever_held_for_answers_nothing() -> None:
    # The caller's cue that there is nothing to fall back on, which is a
    # different answer from a table with no rates in it.
    with connect() as conn:
        Scenario() \
            .given(SOME_BASE_CURRENCY) \
            .when(lambda: exchange_rates.get_latest_for(conn, SOME_BASE_CURRENCY)) \
            .then(_no_rates_are_held())


@pytest.mark.integration
def test_only_the_newest_day_is_answered() -> None:
    # Rates from two days mixed into one table would be a conversion whose
    # disclosed date is true of some of its figures and not others.
    today = date.today()
    yesterday = today - timedelta(days=1)
    todays_rate = Decimal("0.87")

    with connect() as conn:
        Scenario() \
            .given(
                calling(lambda: exchange_rates.record(
                    conn, _rates(SOME_BASE_CURRENCY,
                                 on=yesterday,
                                 per_unit={"eur": Decimal("0.83"),
                                           "jpy": Decimal("146.00")}))),
                calling(lambda: exchange_rates.record(
                    conn, _rates(SOME_BASE_CURRENCY,
                                 on=today,
                                 per_unit={"eur": todays_rate})))
            ) \
            .when(lambda: exchange_rates.get_latest_for(conn, SOME_BASE_CURRENCY)) \
            .then(all_of(
                _the_rates_held_are(_rates(SOME_BASE_CURRENCY,
                                           on=today,
                                           per_unit={"eur": todays_rate})),
                _no_rate_is_held_for("jpy")))


@pytest.mark.integration
def test_the_same_day_arriving_twice_is_taken_as_already_known() -> None:
    # A day's reference rate is published once and does not move, so a second
    # insert is the same numbers arriving again rather than a correction. What
    # must not happen is the write failing on the row already there.
    some_day = date.today()
    the_rate_published_that_day = Decimal("0.85")
    what_was_published = _rates(SOME_BASE_CURRENCY,
                                on=some_day,
                                per_unit={"eur": the_rate_published_that_day})

    with connect() as conn:
        Scenario() \
            .given(
                calling(lambda: exchange_rates.record(conn, what_was_published)),
                calling(lambda: exchange_rates.record(
                    conn, _rates(SOME_BASE_CURRENCY,
                                 on=some_day,
                                 per_unit={"eur": Decimal("0.99")})))
            ) \
            .when(lambda: exchange_rates.get_latest_for(conn, SOME_BASE_CURRENCY)) \
            .then(_the_rates_held_are(what_was_published))


@pytest.mark.integration
def test_rates_held_for_one_base_are_not_answered_for_another() -> None:
    # Two bases are two tables that happen to share rows. A reader asking what
    # a dollar buys must never be told what a pound does.
    some_day = date.today()
    what_a_pound_buys = _rates(ANOTHER_BASE_CURRENCY,
                               on=some_day,
                               per_unit={"eur": Decimal("1.17")})

    with connect() as conn:
        Scenario() \
            .given(
                calling(lambda: exchange_rates.record(
                    conn, _rates(SOME_BASE_CURRENCY,
                                 on=some_day,
                                 per_unit={"eur": Decimal("0.85")}))),
                calling(lambda: exchange_rates.record(conn, what_a_pound_buys))
            ) \
            .when(lambda: exchange_rates.get_latest_for(conn, ANOTHER_BASE_CURRENCY)) \
            .then(_the_rates_held_are(what_a_pound_buys))


def _rates(base: str, on: date, per_unit: dict[str, Decimal]) -> PublishedRates:
    return PublishedRates(base=base, on=on, per_unit=per_unit)


def _the_rates_held_are(expected: PublishedRates) -> Assertion[PublishedRates | None]:
    def assertion(held: PublishedRates | None) -> bool:
        if held is None:
            raise AssertionError(f"expected {expected}, nothing was held at all")

        if (held.base, held.on) != (expected.base, expected.on):
            raise AssertionError(
                f"expected [{expected.base}] published on {expected.on}, got "
                f"[{held.base}] published on {held.on}"
            )

        if held.per_unit != expected.per_unit:
            raise AssertionError(
                f"expected {expected.per_unit}, got {held.per_unit}"
            )

        return True

    return assertion


def _no_rates_are_held() -> Assertion[PublishedRates | None]:
    def assertion(held: PublishedRates | None) -> bool:
        if held is not None:
            raise AssertionError(f"expected nothing to be held, got {held}")

        return True

    return assertion


def _no_rate_is_held_for(currency: str) -> Assertion[PublishedRates | None]:
    """The half a whole-table comparison would already have caught, said out
    loud: a currency priced only on the older day must not survive into the
    newer day's answer."""
    def assertion(held: PublishedRates | None) -> bool:
        if held is not None and currency in held.per_unit:
            raise AssertionError(
                f"expected no rate for [{currency}] from an earlier day, got "
                f"{held.per_unit[currency]}"
            )

        return True

    return assertion
