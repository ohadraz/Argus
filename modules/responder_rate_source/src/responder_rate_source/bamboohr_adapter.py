"""The one place the HR system is known by name.

Everything the vendor decides lives here: what the endpoint is called, how it
authenticates, what its fields are spelled, and which direction it answers in.
What leaves is Argus's own - a title against a band - so nothing above this
module changes when the HR system does, and nothing above it sees a transport
error: a source that cannot be read leaves as `PayBandsUnavailable`.

The provider answers levels carrying their titles - "this rung is worth this
much, and these titles sit on it" - and every caller wants that sentence the
other way round. Inverting it is part of reading the vendor, so it happens
here.

One fetch, because the endpoint takes no parameters and cannot be asked about a
single title. A lookup per title would be this same call, made once per
responder, answering the same thing every time.

Plain HTTP through `httpx` rather than the vendor's SDK, unlike the on-call and
revenue adapters. What is read is one unparameterised GET returning one
document, so an SDK would contribute a credential header and nothing else - and
its bindings are not documented anywhere this repo can check them, which is a
poor reason to guess at method names in production code. If this ever reads a
second resource, that trade turns the other way.
"""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from typing import Any, Final

import httpx
from argus_core.config import Settings, get_settings

from responder_rate_source.bands import (
    PayBand,
    PayBandsByTitle,
    PayBandsUnavailable,
)

# How the request is made. Injected rather than called outright so a test can
# answer it without a network, and without monkeypatching a name this module
# imported. The seam sits at the request rather than at the shape of the
# answer: what comes back is a real `httpx.Response`, so the parsing under test
# is the parsing a live call would get.
type AskHrSource = Callable[..., httpx.Response]

# The resource this reads. A path rather than a URL: the client joins it to
# whichever base address it was built with, which is the whole point of aiming
# that address at the demo.
_THE_PAY_BANDS: Final = "/api/v1/pay-grades-and-bands/job-titles"

# BambooHR authenticates an API key as the username of a basic-auth pair, with
# any password at all. The password is not a secret and is not read - it is
# there because the scheme requires a second field.
_ANY_PASSWORD: Final = "x"

# The provider's own wire vocabulary. A typo in one of these is a title that
# silently has no band rather than an error, which is why they are named once
# and read nowhere else.
_GROUPS: Final = "groups"
_LEVELS: Final = "levels"
_JOB_TITLES: Final = "jobTitles"
_JOB_TITLE: Final = "jobTitle"
_MINIMUM: Final = "min"
_MIDPOINT: Final = "mid"
_MAXIMUM: Final = "max"
_CURRENCY_CODE: Final = "currencyCode"


def pay_bands(settings: Settings | None = None,
              asking: AskHrSource = httpx.get) -> PayBandsByTitle:
    """Every job title the HR source prices, against its own level's band.

    Raises `PayBandsUnavailable` for anything the source fails to answer, and
    for a deployment holding no credential at all. The distinction the caller
    needs is between "no bands are configured" and "nobody could say", and an
    exception is the only way a reading can say the second.

    A title appearing on two levels takes the first the source lists. That is a
    misconfiguration at the source rather than something to resolve here, and
    picking silently beats raising: an incident's cost should not fail on a
    duplicate that does not involve its responders.
    """
    settings = settings or get_settings()

    if not settings.hr_api_key:
        raise PayBandsUnavailable(
            "no HR credential is configured, so what a title is worth cannot "
            "be read"
        )

    return _as_bands_by_title(_read(settings, asking))


def _read(settings: Settings, asking: AskHrSource) -> dict[str, Any]:
    try:
        answer = asking(f"{settings.hr_base_url}{_THE_PAY_BANDS}",
                        auth=(settings.hr_api_key, _ANY_PASSWORD),
                        timeout=settings.hr_timeout_seconds)
        answer.raise_for_status()

        return dict(answer.json())
    except (httpx.HTTPError, ValueError) as error:
        raise PayBandsUnavailable(
            f"the HR source could not be read: {error}"
        ) from error


def _as_bands_by_title(document: dict[str, Any]) -> PayBandsByTitle:
    return {
        title: _a_band(level)
        for group in document.get(_GROUPS, [])
        for level in group.get(_LEVELS, [])
        for title in _titles_on(level)
    }


def _titles_on(level: dict[str, Any]) -> list[str]:
    return [
        title[_JOB_TITLE]
        for title in level.get(_JOB_TITLES, [])
        if title.get(_JOB_TITLE)
    ]


def _a_band(level: dict[str, Any]) -> PayBand:
    return PayBand(
        minimum=Decimal(str(level[_MINIMUM])),
        midpoint=Decimal(str(level[_MIDPOINT])),
        maximum=Decimal(str(level[_MAXIMUM])),
        currency=level[_CURRENCY_CODE]
    )
