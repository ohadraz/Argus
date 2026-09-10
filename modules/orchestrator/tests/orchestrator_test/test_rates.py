from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from agent_postmortem.sources import RateTable
from argus_testkit import Assertion, Scenario, all_of
from argus_testkit.collecting import Kept
from exchange_rate_source import PublishedRates, RatesUnavailable
from orchestrator.rates import HeldRates, Published, todays_rates

"""The day's rates: fetched once, held, and stood in for when nobody answers.

Five situations, and the difference between them is the whole point. Rates are
published once a working day and do not move again, so a second postmortem
written the same afternoon must not cost a second request - and an incident
written up while the provider is down must not lose its estimate over a number
that was already known yesterday.

What is never acceptable is a converted figure resting on a rate whose day the
document cannot state, so every path that answers here answers with a day
attached, and the one path that cannot answers nothing at all.

Where those rates are kept is not this module's subject. The table belongs to
`argus_incidents`, and what it does with a row is tested there; here it is two
injected collaborators, so these are the decisions and nothing else.
"""

SOME_BASE_CURRENCY = "usd"
SOME_OTHER_CURRENCY = "eur"


@pytest.mark.unit
def test_rates_held_from_today_answer_without_asking_anybody() -> None:
    # The reason the rates are kept at all. The ECB publishes once a working
    # day, so a second request the same afternoon would spend a round trip to
    # be told what is already known - and would answer differently only if the
    # provider had gone down in between, which is the one moment the held copy
    # is worth most.
    some_day = date.today()
    some_rate_held = Decimal("0.85")
    asked: Kept[str] = Kept()
    held: Kept[PublishedRates] = Kept()

    Scenario() \
        .given(
            rates_held_today := _rates_on(some_day, {SOME_OTHER_CURRENCY: some_rate_held})
        ) \
        .when(lambda: todays_rates(
            SOME_BASE_CURRENCY,
            published=_a_provider_publishing(_rates_on(some_day, {}), asked),
            today=lambda: some_day,
            held_rates=_rates_already_held(rates_held_today),
            hold_rates=held.take)
        ) \
        .then(all_of(
            _the_rate_for(SOME_OTHER_CURRENCY, was=some_rate_held),
            _the_rates_were_published_on(some_day),
            _nobody_was_asked(asked),
            _nothing_was_kept(held)))


@pytest.mark.unit
def test_the_first_rates_of_the_day_are_fetched_and_kept() -> None:
    # Fetch on first use rather than on a schedule: rates are wanted only when
    # a postmortem is written, and a nightly job would keep asking on the days
    # nothing broke.
    some_day = date.today()
    some_rate_published = Decimal("0.85")
    asked: Kept[str] = Kept()
    held: Kept[PublishedRates] = Kept()

    Scenario() \
        .given(
            what_the_provider_publishes := _rates_on(
                some_day, {SOME_OTHER_CURRENCY: some_rate_published}
            )
        ) \
        .when(lambda: todays_rates(
            SOME_BASE_CURRENCY,
            published=_a_provider_publishing(what_the_provider_publishes, asked),
            today=lambda: some_day,
            held_rates=_nothing_is_held(),
            hold_rates=held.take)
        ) \
        .then(all_of(
            _the_rate_for(SOME_OTHER_CURRENCY, was=some_rate_published),
            _the_rates_were_published_on(some_day),
            _the_provider_was_asked_about(SOME_BASE_CURRENCY, asked),
            _the_rates_kept_were(what_the_provider_publishes, held)))


@pytest.mark.unit
def test_rates_from_an_earlier_day_are_replaced_by_todays() -> None:
    # Anything older than today is a reason to ask, and what comes back
    # replaces what was held - otherwise the first day Argus ran would fix the
    # rate it converts by forever.
    some_day = date.today()
    some_earlier_day = some_day - timedelta(days=1)
    some_rate_today = Decimal("0.87")
    some_stale_rates = Decimal("0.83")
    held: Kept[PublishedRates] = Kept()

    Scenario() \
        .given(
            what_the_provider_publishes := _rates_on(
                some_day, {SOME_OTHER_CURRENCY: some_rate_today}
            )
        ) \
        .when(lambda: todays_rates(
            SOME_BASE_CURRENCY,
            published=_a_provider_publishing(what_the_provider_publishes, Kept()),
            today=lambda: some_day,
            held_rates=_rates_already_held(
                _rates_on(some_earlier_day, {SOME_OTHER_CURRENCY: some_stale_rates})),
            hold_rates=held.take)) \
        .then(all_of(_the_rate_for(SOME_OTHER_CURRENCY, was=some_rate_today),
                     _the_rates_were_published_on(some_day),
                     _the_rates_kept_were(what_the_provider_publishes, held)))


@pytest.mark.unit
def test_an_unreachable_provider_leaves_yesterdays_table_standing() -> None:
    # Yesterday's rate is a worse answer than today's and a far better one than
    # no estimate at all - a day's drift on a reference rate is small beside
    # the difference between a figure and a blank. What must not happen is the
    # document reporting it as today's, so what comes back carries the day it
    # was actually published.
    some_day = date.today()
    some_earlier_day = some_day - timedelta(days=1)
    the_rate_that_day = Decimal("0.83")
    held: Kept[PublishedRates] = Kept()

    Scenario() \
        .given(
            rates_held_from_before := _rates_on(
                some_earlier_day, {SOME_OTHER_CURRENCY: the_rate_that_day}
            )
        ) \
        .when(lambda: todays_rates(
            SOME_BASE_CURRENCY,
            published=_a_provider_that_cannot_be_read(),
            today=lambda: some_day,
            held_rates=_rates_already_held(rates_held_from_before),
            hold_rates=held.take)) \
        .then(all_of(_the_rate_for(SOME_OTHER_CURRENCY, was=the_rate_that_day),
                     _the_rates_were_published_on(some_earlier_day),
                     _nothing_was_kept(held)))


@pytest.mark.unit
def test_an_unreachable_provider_with_nothing_held_answers_no_rates() -> None:
    # The honest end of this channel. A zero here would be a converted figure
    # resting on a rate nobody supplied, and the document is built to tell an
    # unanswered question from an answer of nothing.
    held: Kept[PublishedRates] = Kept()

    Scenario() \
        .given(nothing_was_ever_held := _nothing_is_held()) \
        .when(lambda: todays_rates(
            SOME_BASE_CURRENCY,
            published=_a_provider_that_cannot_be_read(),
            today=date.today,
            held_rates=nothing_was_ever_held,
            hold_rates=held.take)) \
        .then(all_of(_no_rates_were_answered(),
                     _nothing_was_kept(held)))


def _rates_on(day: date, per_unit: dict[str, Decimal]) -> PublishedRates:
    return PublishedRates(base=SOME_BASE_CURRENCY, on=day, per_unit=per_unit)


def _rates_already_held(rates: PublishedRates) -> HeldRates:
    def held_rates(dont_care_base: str) -> PublishedRates | None:
        return rates

    return held_rates


def _nothing_is_held() -> HeldRates:
    def held_rates(dont_care_base: str) -> PublishedRates | None:
        return None

    return held_rates


def _a_provider_publishing(rates: PublishedRates, asked: Kept[str]) -> Published:
    def published(base: str) -> PublishedRates:
        asked.take(base)

        return rates

    return published


def _a_provider_that_cannot_be_read() -> Published:
    def published(dont_care_base: str) -> PublishedRates:
        raise RatesUnavailable("dont care")

    return published


def _the_rate_for(currency: str, was: Decimal) -> Assertion[RateTable | None]:
    def assertion(table: RateTable | None) -> bool:
        if table is None:
            raise AssertionError(f"expected a rate for [{currency}], got no table")

        if table.per_unit.get(currency) != was:
            raise AssertionError(
                f"expected [{currency}] at {was}, got {table.per_unit.get(currency)}"
            )

        return True

    return assertion


def _the_rates_were_published_on(day: date) -> Assertion[RateTable | None]:
    """The day travels with the table rather than beside it: a figure resting
    on a rate whose day the document cannot state is the one thing this module
    must never answer."""
    def assertion(table: RateTable | None) -> bool:
        if table is None:
            raise AssertionError(f"expected a table published on {day}, got none")

        if table.on != day:
            raise AssertionError(
                f"expected rates published on {day}, they were published on {table.on}"
            )

        return True

    return assertion


def _no_rates_were_answered() -> Assertion[RateTable | None]:
    def assertion(table: RateTable | None) -> bool:
        if table is not None:
            raise AssertionError(f"expected no rates at all, got {table}")

        return True

    return assertion


def _nobody_was_asked(asked: Kept[str]) -> Assertion[RateTable | None]:
    def assertion(dont_care_table: RateTable | None) -> bool:
        if asked.taken:
            raise AssertionError(
                f"expected the provider not to be asked, it was asked for {asked.taken}"
            )

        return True

    return assertion


def _the_provider_was_asked_about(base: str,
                                  asked: Kept[str]) -> Assertion[RateTable | None]:
    def assertion(dont_care_table: RateTable | None) -> bool:
        if asked.only() != base:
            raise AssertionError(
                f"expected the provider to be asked about [{base}], it was asked "
                f"about [{asked.only()}]"
            )

        return True

    return assertion


def _nothing_was_kept(held: Kept[PublishedRates]) -> Assertion[RateTable | None]:
    def assertion(dont_care_table: RateTable | None) -> bool:
        if held.taken:
            raise AssertionError(
                f"expected nothing to be kept, {held.taken} was"
            )

        return True

    return assertion


def _the_rates_kept_were(expected: PublishedRates,
                         held: Kept[PublishedRates]) -> Assertion[RateTable | None]:
    def assertion(dont_care_table: RateTable | None) -> bool:
        if held.only() != expected:
            raise AssertionError(f"expected {expected} to be kept, {held.only()} was")

        return True

    return assertion
