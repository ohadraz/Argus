from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

import httpx
import pytest
from argus_core.config import Settings
from argus_testkit import Assertion, Scenario, all_of, attempting
from argus_testkit.collecting import Kept
from exchange_rate_source import PublishedRates, RatesUnavailable, rates_published_for

"""Reading a day's rates from the provider that publishes them.

The provider's body is answered as a real `httpx.Response`, so the parsing
under test is the same parsing a live call would get - the seam sits at the
request, not at the shape of the answer. What is asserted is only what Argus
depends on: the rates, the day they were published, and the currencies named
the way every other source in Argus names them.

A base currency arrives here lower-cased, because that is how a payment
provider reports what it took. The rate provider spells currencies upper-case.
Somewhere that has to be reconciled, and here is the only place that knows
both spellings.
"""

SOME_BASE_CURRENCY = "usd"
SOME_OTHER_CURRENCY = "eur"

DONT_CARE_BASE_URL = "http://rates.invalid"


@pytest.mark.unit
def test_one_call_answers_the_whole_table_for_a_base_currency() -> None:
    # One request, every rate. A shop's takings can arrive in any currency it
    # accepts, and a postmortem written after the fact cannot go back and ask
    # for the one it turned out to need - so the table is fetched whole or the
    # conversion is a second round trip per currency for the same answer.
    some_published_day = date(2026, 9, 3)
    some_rate = Decimal("0.85")
    some_other_rate = Decimal("155.20")
    some_third_currency = "jpy"

    Scenario() \
        .given(
            answered := _the_provider_publishing(
                on=some_published_day,
                rates={SOME_OTHER_CURRENCY.upper(): float(some_rate),
                       some_third_currency.upper(): float(some_other_rate)}
            )
        ) \
        .when(
            lambda: rates_published_for(SOME_BASE_CURRENCY,
                                        settings=_pointed_at(DONT_CARE_BASE_URL),
                                        asking=answered)
        ) \
        .then(
            all_of(
                _the_base_was(SOME_BASE_CURRENCY),
                _the_rates_were_published_on(some_published_day),
                _the_rate_for(SOME_OTHER_CURRENCY, was=some_rate),
                _the_rate_for(some_third_currency, was=some_other_rate)
            )
        )


@pytest.mark.unit
def test_the_provider_is_asked_for_the_base_currency_it_spells_upper_case() -> None:
    # The one thing this module exists to reconcile. Argus names currencies as
    # its payment provider does, in lower case; this provider answers a
    # request for "usd" with rates against the euro, silently, because an
    # unrecognised base falls back to its own default. A table converted
    # against the wrong base is wrong by a factor nobody would notice.
    dont_care_published_day = date(2026, 9, 3)

    Scenario() \
        .given(
            asked_for := Kept[dict[str, Any]]()
        ) \
        .when(
            lambda: rates_published_for(
                SOME_BASE_CURRENCY,
                settings=_pointed_at(DONT_CARE_BASE_URL),
                asking=_the_provider_recording_the_request_into(
                    asked_for, on=dont_care_published_day))
        ) \
        .then(
            _the_base_asked_for_was(SOME_BASE_CURRENCY.upper(), asked_for)
        )


@pytest.mark.unit
def test_a_provider_that_cannot_be_reached_says_no_rates_could_be_had() -> None:
    # An unreachable provider is an ordinary event, and the caller has an
    # answer for it - the rates held from an earlier day. It can only reach
    # for them if this says plainly that today's could not be had, so the
    # transport's own error must not escape as itself.
    Scenario() \
        .given(
            refusing := _a_provider_that_refuses
        ) \
        .when(
            attempting(lambda: rates_published_for(
                SOME_BASE_CURRENCY,
                settings=_pointed_at(DONT_CARE_BASE_URL),
                asking=refusing()))
        ) \
        .then(
            _it_was_reported_as_no_rates_at_all()
        )


@pytest.mark.unit
def test_a_body_in_a_shape_argus_cannot_read_is_no_rates_either() -> None:
    # A provider answering 200 with something else - a proxy's error page, an
    # API that changed - is exactly as useless as one that did not answer, and
    # the caller has the same fallback either way. What it must never be is a
    # table missing the currencies whose absence would silently drop money.
    Scenario() \
        .given(
            answering_nonsense := _a_provider_answering_nonsense
        ) \
        .when(
            attempting(lambda: rates_published_for(SOME_BASE_CURRENCY,
                                                   settings=_pointed_at(DONT_CARE_BASE_URL),
                                                   asking=answering_nonsense()))
        ) \
        .then(
            _it_was_reported_as_no_rates_at_all()
        )


def _pointed_at(base_url: str) -> Settings:
    return Settings(exchange_rate_base_url=base_url)


def _the_provider_publishing(on: date,
                             rates: dict[str, float]) -> Any:
    """The provider answering as it really does - upper-cased currency codes,
    an ISO day, and the base echoed back."""
    def answering(*dont_care_args: Any, **dont_care_kwargs: Any) -> httpx.Response:
        return httpx.Response(
            200,
            request=httpx.Request("GET", DONT_CARE_BASE_URL),
            json={"amount": 1.0,
                  "base": SOME_BASE_CURRENCY.upper(),
                  "date": on.isoformat(),
                  "rates": rates}
        )

    return answering


def _a_provider_that_refuses() -> Any:
    def answering(*dont_care_args: Any, **dont_care_kwargs: Any) -> httpx.Response:
        raise httpx.ConnectError("nothing is listening")

    return answering


def _a_provider_answering_nonsense() -> Any:
    def answering(*dont_care_args: Any, **dont_care_kwargs: Any) -> httpx.Response:
        return httpx.Response(200,
                              request=httpx.Request("GET", DONT_CARE_BASE_URL),
                              json={"detail": "not what you asked for"})

    return answering


def _the_provider_recording_the_request_into(asked_for: Kept[dict[str, Any]],
                                             on: date) -> Any:
    def answering(*dont_care_args: Any, **kwargs: Any) -> httpx.Response:
        asked_for.take(kwargs.get("params", {}))

        return httpx.Response(
            200,
            request=httpx.Request("GET", DONT_CARE_BASE_URL),
            json={"amount": 1.0,
                  "base": SOME_BASE_CURRENCY.upper(),
                  "date": on.isoformat(),
                  "rates": {SOME_OTHER_CURRENCY.upper(): 0.85}}
        )

    return answering


def _the_base_was(expected: str) -> Assertion[PublishedRates]:
    def assertion(published: PublishedRates) -> bool:
        if published.base != expected:
            raise AssertionError(
                f"Expected rates against [{expected}], but they came back "
                f"against [{published.base}].")

        return True

    return assertion


def _the_rates_were_published_on(expected: date) -> Assertion[PublishedRates]:
    def assertion(published: PublishedRates) -> bool:
        if published.on != expected:
            raise AssertionError(
                f"Expected rates published on [{expected}], but they came back "
                f"published on [{published.on}].")

        return True

    return assertion


def _the_rate_for(currency: str, was: Decimal) -> Assertion[PublishedRates]:
    def assertion(published: PublishedRates) -> bool:
        if published.per_unit.get(currency) != was:
            raise AssertionError(
                f"Expected [{was}] {currency} per {published.base}, but the "
                f"table says {published.per_unit}.")

        return True

    return assertion


def _the_base_asked_for_was(expected: str,
                            asked_for: Kept[dict[str, Any]]) -> Assertion[Any]:
    def assertion(dont_care_result: Any) -> bool:
        if asked_for.only().get("base") != expected:
            raise AssertionError(
                f"Expected the provider to be asked for base [{expected}], but "
                f"it was asked {asked_for.taken}.")

        return True

    return assertion


def _it_was_reported_as_no_rates_at_all() -> Assertion[Exception | None]:
    def assertion(raised: Exception | None) -> bool:
        if not isinstance(raised, RatesUnavailable):
            raise AssertionError(
                f"Expected the provider's failure to be reported as "
                f"RatesUnavailable, but what came back was [{raised!r}].")

        return True

    return assertion
