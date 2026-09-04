from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import psycopg
import pytest
from agent_postmortem.sources import RateTable
from argus_testkit import Assertion, Scenario, all_of
from argus_testkit.collecting import Kept
from exchange_rate_source import PublishedRates, RatesUnavailable
from orchestrator.rates import todays_rates
from orchestrator.repository import exchange_rates

"""The day's rates: fetched once, held, and stood in for when nobody answers.

Three situations, and the difference between them is the whole point. Rates
are published once a working day and do not move again, so a second postmortem
written the same afternoon must not cost a second request - and an incident
written up while the provider is down must not lose its estimate over a number
that was already known yesterday.

What is never acceptable is a converted figure resting on a rate whose day the
document cannot state, so every path that answers here answers with a day
attached, and the one path that cannot answers nothing at all.
"""

DATABASE_URL = "postgresql://argus:argus@localhost:5432/argus"

SOME_BASE_CURRENCY = "usd"
SOME_OTHER_CURRENCY = "eur"


@pytest.mark.integration
def test_the_first_rates_of_the_day_are_fetched_and_answered() -> None:
    # Fetch on first use rather than on a schedule: rates are wanted only when
    # a postmortem is written, and a nightly job would keep asking on the days
    # nothing broke.
    some_day = date.today()
    some_rate = Decimal("0.85")

    with psycopg.connect(DATABASE_URL) as conn:
        Scenario() \
            .given(
                asked := Kept[str]()
            ) \
            .when(
                lambda: todays_rates(
                    conn,
                    SOME_BASE_CURRENCY,
                    published=_a_provider_publishing(
                        on=some_day,
                        per_unit={SOME_OTHER_CURRENCY: some_rate},
                        recording_into=asked))
            ) \
            .then(
                all_of(
                    _the_rate_for(SOME_OTHER_CURRENCY, was=some_rate),
                    _the_rates_were_published_on(some_day),
                    _the_provider_was_asked(times=1, asked=asked)
                )
            )


@pytest.mark.integration
def test_a_second_reading_the_same_day_asks_nobody() -> None:
    # The reason the table exists. The ECB publishes once a working day, so a
    # second request the same afternoon would spend a round trip to be told
    # what is already known - and would answer differently only if the
    # provider had gone down in between, which is the one moment the held
    # copy is worth most.
    some_day = date.today()
    dont_care_rate = Decimal("0.85")

    with psycopg.connect(DATABASE_URL) as conn:
        provider = _a_provider_publishing(on=some_day,
                                          per_unit={SOME_OTHER_CURRENCY: dont_care_rate},
                                          recording_into=(asked := Kept[str]()))

        Scenario() \
            .given(
                todays_rates(conn, SOME_BASE_CURRENCY, published=provider)
            ) \
            .when(
                lambda: todays_rates(conn, SOME_BASE_CURRENCY, published=provider)
            ) \
            .then(
                all_of(
                    _the_rate_for(SOME_OTHER_CURRENCY, was=dont_care_rate),
                    _the_provider_was_asked(times=1, asked=asked)
                )
            )


@pytest.mark.integration
def test_an_unreachable_provider_falls_back_to_the_rates_already_held() -> None:
    # Yesterday's rate is a worse answer than today's and a far better one than
    # no estimate at all - a day's drift on a reference rate is small beside
    # the difference between a figure and a blank. What must not happen is the
    # document reporting it as today's, so what comes back carries the day it
    # was actually published.
    some_earlier_day = date.today() - timedelta(days=1)
    some_rate_that_day = Decimal("0.83")

    with psycopg.connect(DATABASE_URL) as conn:
        Scenario() \
            .given(
                _rates_already_held(conn,
                                    on=some_earlier_day,
                                    per_unit={SOME_OTHER_CURRENCY: some_rate_that_day})
            ) \
            .when(
                lambda: todays_rates(conn,
                                     SOME_BASE_CURRENCY,
                                     published=_a_provider_that_cannot_be_read())
            ) \
            .then(
                all_of(
                    _the_rate_for(SOME_OTHER_CURRENCY, was=some_rate_that_day),
                    _the_rates_were_published_on(some_earlier_day)
                )
            )


@pytest.mark.integration
def test_an_unreachable_provider_with_nothing_held_answers_no_rates() -> None:
    # Nothing to fall back on, so nothing is claimed. The document then
    # publishes no estimate and says why, which is the honest end of this
    # channel - a conversion at a guessed rate would be a figure that looks
    # measured and is not.
    with psycopg.connect(DATABASE_URL) as conn:
        Scenario() \
            .when(
                lambda: todays_rates(conn,
                                     SOME_BASE_CURRENCY,
                                     published=_a_provider_that_cannot_be_read())
            ) \
            .then(
                _no_rates_were_answered()
            )


def _a_provider_publishing(on: date,
                           per_unit: dict[str, Decimal],
                           recording_into: Kept[str] | None = None) -> Any:
    """A provider answering one fixed table, remembering that it was asked.

    The count is what two of these tests turn on, so the double records the
    base it was asked for rather than merely answering.
    """
    def published(base: str) -> PublishedRates:
        if recording_into is not None:
            recording_into.take(base)

        return PublishedRates(base=base, on=on, per_unit=per_unit)

    return published


def _a_provider_that_cannot_be_read() -> Any:
    def published(dont_care_base: str) -> PublishedRates:
        raise RatesUnavailable("nothing is listening")

    return published


def _rates_already_held(conn: psycopg.Connection,
                        on: date,
                        per_unit: dict[str, Decimal]) -> bool:
    """Rates in the table from an earlier day, put there the way the code puts
    them - through the repository, so a test never states the schema twice."""
    exchange_rates.record(
        conn, PublishedRates(base=SOME_BASE_CURRENCY, on=on, per_unit=per_unit))

    return True


def _the_rate_for(currency: str, was: Decimal) -> Assertion[RateTable | None]:
    def assertion(answered: RateTable | None) -> bool:
        if answered is None:
            raise AssertionError(
                f"Expected [{was}] {currency} per {SOME_BASE_CURRENCY}, but no "
                f"rates were answered at all.")

        if answered.per_unit.get(currency) != was:
            raise AssertionError(
                f"Expected [{was}] {currency} per {SOME_BASE_CURRENCY}, but the "
                f"table says {answered.per_unit}.")

        return True

    return assertion


def _the_rates_were_published_on(expected: date) -> Assertion[RateTable | None]:
    def assertion(answered: RateTable | None) -> bool:
        if answered is None:
            raise AssertionError(
                f"Expected rates published on [{expected}], but no rates were "
                f"answered at all.")

        if answered.on != expected:
            raise AssertionError(
                f"Expected rates published on [{expected}], but they came back "
                f"published on [{answered.on}].")

        return True

    return assertion


def _the_provider_was_asked(times: int, asked: Kept[str]) -> Assertion[Any]:
    def assertion(dont_care_result: Any) -> bool:
        if len(asked.taken) != times:
            raise AssertionError(
                f"Expected the provider to be asked [{times}] time(s), but it "
                f"was asked {len(asked.taken)}: {asked.taken}.")

        return True

    return assertion


def _no_rates_were_answered() -> Assertion[RateTable | None]:
    def assertion(answered: RateTable | None) -> bool:
        if answered is not None:
            raise AssertionError(
                f"Expected no rates, but [{answered}] came back - a converted "
                f"figure would rest on a rate nobody could produce.")

        return True

    return assertion
