"""Flag state, read from the provider's evaluation API (spec §12.1).

The read tier's view of the feature-flag provider, and the only place in Argus
that knows the provider's wire shape for evaluation. Everything above sees flag
names.

Two layers, both public, because they fail for different reasons:
`fetch_evaluated_toggles` makes the HTTP request and is where the credential, a
URL and an outage live, while `enabled_flags` maps the response onto the names
its callers reason about.

The credential this module sends can evaluate flags and cannot change one. That
is what makes `argus-read-mcp` incapable of mutation rather than merely
disinclined (§13) - the admin credential is issued to `argus-write-mcp` alone
and is not readable from here.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

import httpx
from argus_core import SettingsSlice


class FlagReadSettings(SettingsSlice):
    """What it takes to ask the provider which flags are on.

    The evaluation credential and where to send it, and deliberately nothing
    more. The admin credential is absent because there is no field here to put
    it in: the read tier is incapable of mutation rather than disinclined
    (§13), and a type that cannot name that credential is how it stays true on
    the day somebody puts one in the environment.

    Named by description rather than by its setting, so that grepping this
    package for the write tier's credentials answers nothing - a check whose
    one permanent hit is a comment about not having them is not a check.
    """

    unleash_base_url: str
    unleash_frontend_token: str


HttpGet = Callable[..., httpx.Response]


class FetchToggles(Protocol):
    """What `enabled_flags` needs from whatever asks the provider.

    A `Protocol` rather than a `Callable` alias so that a test can stand it in
    with `create_autospec`, which needs something introspectable and an alias
    is not. Specing against the concrete fetcher below would be specing against
    a different shape: it takes the credential it sends, and what reads its
    answer has no business holding one.
    """

    def __call__(self) -> list[dict[str, Any]]: ...

REQUEST_TIMEOUT_SECONDS = 10.0

EVALUATION_PATH = "/api/frontend"


class FlagProviderUnavailable(Exception):
    """The flag provider could not be asked what is enabled.

    Deliberately not an empty list. "The provider was down" and "no flag is on"
    are opposite facts, and a reader that reports the first as the second hands
    Mitigation an environment that appears to have nothing to revert - so an
    outage would end an incident by making its cause invisible.
    """


def fetch_evaluated_toggles(
    settings: FlagReadSettings,
    get: HttpGet = httpx.get,
) -> list[dict[str, Any]]:
    """Asks the provider which flags evaluate true for this credential.

    The evaluation credential is environment-scoped, so the environment is the
    token's rather than a parameter: a caller cannot ask about an environment
    the read tier was not given access to.

    Any failure to get an answer - unreachable host, error status, unreadable
    body - becomes `FlagProviderUnavailable`. None of them may become "nothing
    is enabled".
    """
    url = f"{settings.unleash_base_url}{EVALUATION_PATH}"

    try:
        response = get(
            url,
            headers={"Authorization": settings.unleash_frontend_token},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        body: dict[str, Any] = response.json()
    except Exception as error:
        raise FlagProviderUnavailable(
            f"could not read flag state from [{url}]: {error}"
        ) from error

    toggles: list[dict[str, Any]] = body.get("toggles", [])

    return toggles


def enabled_flags(fetch: FetchToggles) -> list[str]:
    """The names of the flags currently on, in the order the provider lists them.

    A flag that is off is *absent* from the provider's answer rather than
    present and false, so presence is the signal. The `enabled` field is still
    honoured where it appears - a provider that starts reporting disabled
    toggles explicitly would otherwise have every one of them read as on, which
    is the failure that turns a healthy environment into a flag Mitigation
    reverts.
    """
    return [
        toggle["name"] for toggle in fetch() if toggle.get("enabled", True)
    ]
