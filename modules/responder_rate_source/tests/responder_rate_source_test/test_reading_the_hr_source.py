from __future__ import annotations

from decimal import Decimal
from typing import Any, NamedTuple

import httpx
import pytest
from argus_core.config import Settings
from argus_testkit import Assertion, Scenario, all_of, attempting
from argus_testkit.collecting import Kept
from responder_rate_source import PayBand, pay_bands
from responder_rate_source.bamboohr_adapter import AskHrSource
from responder_rate_source.bands import PayBandsByTitle, PayBandsUnavailable

"""Reading the HR source - one fetch of every level, inverted into titles.

The endpoint takes no parameters and answers levels carrying their titles, so
turning that into "what is this title worth" is this module's whole job. It is
also the reason nothing here asks about a person: a band belongs to a level,
and a level is a rung, not a payroll record.

What is injected is the fetch, so the shape being read is the provider's own
and only the answer is written.
"""

# The provider's own field names, spelled out here rather than shared with the
# module under test: the assertion is that Argus reads *these*, and a constant
# imported from the reader would agree with itself whatever it was renamed to.
GROUPS = "groups"
LEVELS = "levels"
JOB_TITLES = "jobTitles"
JOB_TITLE = "jobTitle"
MIN = "min"
MID = "mid"
MAX = "max"
CURRENCY_CODE = "currencyCode"

SOME_TITLE = "Junior Kuki"
SOME_OTHER_TITLE_ON_THE_SAME_LEVEL = "Senior Kuki"
SOME_OTHER_TITLE = "Junior Buki"
SOME_TITLE_NOBODY_ASSIGNED = "Senior Buki"

SOME_CURRENCY = "USD"
SOME_KEY = "some-hr-key"

DONT_CARE_URL = "http://hr.example"


@pytest.mark.unit
def test_a_title_carries_the_band_of_the_level_it_is_assigned_to() -> None:
    # The inversion this module exists for. The provider says "this level is
    # worth this much, and these titles sit on it"; everything above wants the
    # sentence the other way round.
    some_minimum_pay_band = Decimal(150_000)
    some_midpoint_pay_band = Decimal(175_000)
    some_maximum_pay_band = Decimal(200_000)
    some_other_minimum_pay_band = Decimal(190_000)
    some_other_midpoint_pay_band = Decimal(220_000)
    some_other_maximum_pay_band = Decimal(250_000)
    some_band = _a_pay_band(some_minimum_pay_band, some_midpoint_pay_band, some_maximum_pay_band)
    some_other_band = _a_pay_band(
        some_other_minimum_pay_band, some_other_midpoint_pay_band, some_other_maximum_pay_band)
    some_level = _a_level(some_band, SOME_TITLE, SOME_OTHER_TITLE_ON_THE_SAME_LEVEL)
    some_other_level = _a_level(some_other_band, SOME_OTHER_TITLE)
    a_source_answering = _a_source_answering(_a_group(some_level, some_other_level))

    Scenario() \
        .when(
            lambda: pay_bands(settings=_settings_with(SOME_KEY),
                              asking=a_source_answering)
        ) \
        .then(all_of(
            _the_band_for(SOME_TITLE, is_=some_band),
            _the_band_for(SOME_OTHER_TITLE, is_=some_other_band)
        ))


@pytest.mark.unit
def test_every_title_on_a_level_carries_that_level_s_band() -> None:
    # A level lists more than one title, and each of them is worth the level.
    # Reading only the first is the bug this exists to catch, because it fails
    # silently: the titles that survive are priced correctly.
    some_minimum_pay_band = Decimal(150_000)
    some_midpoint_pay_band = Decimal(175_000)
    some_maximum_pay_band = Decimal(200_000)
    some_band = _a_pay_band(
        some_minimum_pay_band, some_midpoint_pay_band, some_maximum_pay_band)
    some_level = _a_level(
        some_band, SOME_TITLE, SOME_OTHER_TITLE_ON_THE_SAME_LEVEL)
    a_source_answering = _a_source_answering(_a_group(some_level))

    Scenario() \
        .when(
            lambda: pay_bands(settings=_settings_with(SOME_KEY),
                              asking=a_source_answering)
        ) \
        .then(all_of(
            _the_band_for(SOME_TITLE, is_=some_band),
            _the_band_for(SOME_OTHER_TITLE_ON_THE_SAME_LEVEL, is_=some_band)
        ))


@pytest.mark.unit
def test_a_title_no_level_lists_has_no_band() -> None:
    # Absent, not zero and not somebody else's band. A title nobody assigned to
    # a level is a gap in the HR configuration, and the only honest answer is
    # that this source cannot price it.
    dont_care_minimum_pay_band = Decimal(150_000)
    dont_care_midpoint_pay_band = Decimal(175_000)
    dont_care_maximum_pay_band = Decimal(200_000)
    some_band = _a_pay_band(
        dont_care_minimum_pay_band, dont_care_midpoint_pay_band, dont_care_maximum_pay_band)
    some_level = _a_level(some_band, SOME_TITLE)
    a_source_answering = _a_source_answering(_a_group(some_level))

    Scenario() \
        .when(
            lambda: pay_bands(settings=_settings_with(SOME_KEY),
                              asking=a_source_answering)
        ) \
        .then(all_of(
            _no_band_was_priced_for(SOME_TITLE_NOBODY_ASSIGNED)
        ))


@pytest.mark.unit
def test_a_source_that_prices_nothing_is_not_a_source_that_could_not_be_read() -> None:
    # The distinction the whole port exists for. An organisation that has
    # configured no bands prices nothing, and that is a fact about it; a source
    # that refused to answer is not a fact about anything, and reporting the
    # two the same way would publish "this response cost nothing" out of an
    # outage in Argus's own dependencies.
    a_source_answering_nothing = _a_source_answering(_a_group())

    Scenario() \
        .when(
            lambda: pay_bands(settings=_settings_with(SOME_KEY),
                              asking=a_source_answering_nothing)
        ) \
        .then(all_of(
            _nothing_was_priced()
        ))

    Scenario() \
        .when(
            attempting(lambda: pay_bands(settings=_settings_with(SOME_KEY),
                                         asking=_a_source_that_cannot_be_read()))
        ) \
        .then(all_of(
            _the_source_said_it_could_not_be_read()
        ))


@pytest.mark.unit
def test_the_bands_are_asked_for_at_the_providers_own_path_with_the_key() -> None:
    # What the seam swallows everywhere else in this file. A wrong path or a
    # key sent as something other than the basic-auth username fails only
    # against a real account - every test here would pass, because the fake
    # answers whatever it is asked.
    a_request: Kept[_AskedFor] = Kept()
    a_source = _a_source_recording_the_request_into(a_request)

    Scenario() \
        .when(
            lambda: pay_bands(settings=_settings_with(SOME_KEY), asking=a_source)
        ) \
        .then(all_of(
            _the_url_asked_for_was(
                f"{DONT_CARE_URL}/api/v1/pay-grades-and-bands/job-titles",
                a_request),
            _the_key_was_sent_as_the_username(SOME_KEY, a_request)
        ))


def _a_pay_band(minimum: Decimal, 
                midpoint: Decimal, 
                maximum: Decimal,
                currency: str = SOME_CURRENCY) -> PayBand:
    """A band as Argus holds it - three figures and what they are in."""
    return PayBand(
        minimum=Decimal(minimum),
        midpoint=Decimal(midpoint),
        maximum=Decimal(maximum),
        currency=currency
    )


def _a_level(band: PayBand, *titles: str) -> dict[str, Any]:
    """One level in the provider's own shape: a band, and the titles on it."""
    return {
        MIN: int(band.minimum),
        MID: int(band.midpoint),
        MAX: int(band.maximum),
        CURRENCY_CODE: band.currency,
        JOB_TITLES: [{JOB_TITLE: title} for title in titles]
    }


def _a_group(*levels: dict[str, Any]) -> dict[str, Any]:
    return {
        GROUPS: [
            {LEVELS: list(levels)}
        ]
    }


def _a_source_answering(document: dict[str, Any]) -> AskHrSource:
    def answering(dont_care_url: str, **dont_care_kwargs: Any) -> httpx.Response:
        return httpx.Response(200,
                              request=httpx.Request("GET", DONT_CARE_URL),
                              json=document)

    return answering


def _the_band_for(title: str, is_: PayBand) -> Assertion[PayBandsByTitle]:
    def assertion(bands: PayBandsByTitle) -> bool:
        if title not in bands:
            raise AssertionError(
                f"Expected a band for [{title}], but the titles priced were "
                f"{sorted(bands)}.")

        if bands[title] != is_:
            raise AssertionError(
                f"Expected [{title}] to be worth {is_}, got {bands[title]}.")

        return True

    return assertion


def _no_band_was_priced_for(title: str) -> Assertion[PayBandsByTitle]:
    def assertion(bands: PayBandsByTitle) -> bool:
        if title in bands:
            raise AssertionError(
                f"Expected no band for [{title}], because no level lists it, "
                f"but it was priced at {bands[title]}.")

        return True

    return assertion


def _a_source_that_cannot_be_read() -> AskHrSource:
    def answering(dont_care_url: str, **dont_care_kwargs: Any) -> httpx.Response:
        raise httpx.ConnectError("nothing is listening")

    return answering


def _nothing_was_priced() -> Assertion[PayBandsByTitle]:
    def assertion(bands: PayBandsByTitle) -> bool:
        if bands:
            raise AssertionError(
                f"Expected a source configuring no bands to price nothing, but "
                f"it priced {sorted(bands)}.")

        return True

    return assertion


def _the_source_said_it_could_not_be_read() -> Assertion[Exception | None]:
    def assertion(error: Exception | None) -> bool:
        if not isinstance(error, PayBandsUnavailable):
            raise AssertionError(
                f"Expected the source to report that it could not be read, got "
                f"[{error!r}].")

        return True

    return assertion


def _settings_with(api_key: str) -> Settings:
    return Settings(hr_api_key=api_key, hr_base_url=DONT_CARE_URL)


def _a_source_recording_the_request_into(request: Kept[_AskedFor]) -> AskHrSource:
    def answering(url: str,
                  auth: tuple[str, str] | None = None,
                  timeout: float | None = None) -> httpx.Response:
        request.take(_AskedFor(url=url, auth=auth))

        return httpx.Response(200,
                              request=httpx.Request("GET", DONT_CARE_URL),
                              json=_a_group())

    return answering


def _the_url_asked_for_was(expected: str,
                           request: Kept[_AskedFor]) -> Assertion[PayBandsByTitle]:
    def assertion(dont_care_bands: PayBandsByTitle) -> bool:
        if request.only().url != expected:
            raise AssertionError(
                f"Expected the bands to be asked for at [{expected}], got "
                f"[{request.only().url}].")

        return True

    return assertion


def _the_key_was_sent_as_the_username(expected: str, 
                                      request: Kept[_AskedFor]) -> Assertion[PayBandsByTitle]:
    def assertion(dont_care_bands: PayBandsByTitle) -> bool:
        sent = request.only().auth

        if not sent or sent[0] != expected:
            raise AssertionError(
                f"Expected the key [{expected}] to be sent as the basic-auth "
                f"username, got [{sent}].")

        return True

    return assertion


class _AskedFor(NamedTuple):
    url: str
    auth: tuple[str, str] | None
