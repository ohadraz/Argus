"""The register as the demo Target Service keeps one, and the only place in
Argus that knows its wire shape. Everything above the port sees
`ServiceDependency`.

Two layers, both public, because they fail for different reasons:
`fetch_registered_service` makes the HTTP request and is where a URL and an
outage live, while `what_a_service_depends_on` maps the answer onto the type its
callers reason about. `TargetServiceRegister` is the two composed, behind the
port.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Final, Protocol

import httpx2
from core import AdapterSettings
from core.models import ServiceDependency

from service_register.port import RegistryUnavailable

__all__ = [
    "FetchRegisteredService",
    "TargetServiceRegister",
    "TargetServiceRegisterSettings",
    "fetch_registered_service",
    "what_a_service_depends_on"
]

# The register's own field names. Named rather than spelled at the point of use,
# for the reason every other external vocabulary in Argus is: the register is
# somebody else's document, and a literal buried in a comprehension is a literal
# nobody finds when that document changes.
#
# Internal to this module, not exported. This is the one place that knows the
# register's wire shape, and a caller holding one of these names would be a
# second place to change when the register changes its own.
DEPENDENCIES_FIELD: Final = "dependencies"
NAME_FIELD: Final = "name"
PURPOSE_FIELD: Final = "purpose"
HOST_FIELD: Final = "host"
OWNER_FIELD: Final = "owner"
OWNERSHIP_FIELD: Final = "ownership"

REQUEST_TIMEOUT_SECONDS = 10.0


class TargetServiceRegisterSettings(AdapterSettings):
    """Where the register answers, and under what path.

    A template path rather than a fixed route, as the deploy reader's is: the
    demo's `/registry/services/{service}` and whatever a real register spells it
    is are the same setting with different values.

    No credential. A register of what calls what is not secret inside the
    organisation that keeps it, and a field for one here would be a field the
    read tier could be handed a mutating credential in - the flag provider's
    read settings make the same argument about a type that cannot name what it
    must not hold.
    """

    # Where the organisation's service register answers. The demo Target Service
    # stands in for one, so the default points at it.
    service_registry_base_url: str = "http://localhost:8080"
    # A template, as the deploy reader's paths are, so a register with one route
    # per service and one with a single route are the same setting at different
    # values. A path carrying no placeholder formats to itself.
    service_registry_service_path: str = "/registry/services/{service}"


HttpGet = Callable[..., httpx2.Response]


class FetchRegisteredService(Protocol):
    """What `what_a_service_depends_on` needs from whatever asks the register.

    A `Protocol` rather than a `Callable` alias so a test can stand it in with
    `create_autospec`, which needs something introspectable. Specing against the
    concrete fetcher would be specing against a different shape: that one takes
    the settings it reads under, and what maps its answer holds none.
    """

    # Positional-only: the service is the whole question, and a stand-in that
    # ignores it should be free to say so in the parameter's name.
    def __call__(self, service: str, /) -> dict[str, Any]: ...


class TargetServiceRegister:
    """The demo Target Service's register, behind the port.

    Holds where the register is and nothing else. Built where the read server
    is wired, and handed on typed as `ServiceRegister`.
    """

    def __init__(self,
                 settings: TargetServiceRegisterSettings,
                 get: HttpGet = httpx2.get) -> None:
        self._settings = settings
        self._get = get

    def dependencies_of(self, service: str, /) -> list[ServiceDependency]:
        """What the register holds for `service`, asked and then mapped - see
        `what_a_service_depends_on` for what an entry becomes."""
        return what_a_service_depends_on(service, fetch=self._registered)

    def _registered(self, service: str, /) -> dict[str, Any]:
        return fetch_registered_service(service, self._settings, get=self._get)


def fetch_registered_service(
    service: str,
    settings: TargetServiceRegisterSettings,
    get: HttpGet = httpx2.get
) -> dict[str, Any]:
    """Asks the register what it holds about one service.

    Any failure to get an answer - unreachable host, error status, unreadable
    body - becomes `RegistryUnavailable`. None of them may become "it calls
    nothing".
    """
    url = f"{settings.service_registry_base_url}{_service_path(settings, service)}"

    try:
        response = get(url, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        body: dict[str, Any] = response.json()
    except Exception as error:
        raise RegistryUnavailable(
            f"could not read the service register at [{url}]: {error}"
        ) from error

    return body


def what_a_service_depends_on(service: str,
                              fetch: FetchRegisteredService) -> list[ServiceDependency]:
    """The dependencies the register holds for this service, in its own order.

    An empty list for a service the register has no entry for, which is a real
    answer rather than a failure: the register holds nothing, and that is a fact
    about the register. What it must never be is the answer to an outage, which
    is what `RegistryUnavailable` exists to keep separate - and that exception
    passes through here untouched rather than being softened into an empty list.

    An ownership this system has never heard of comes through as written. Not
    refused, because one new word anywhere in the register would then stop Argus
    reading any of it and every incident would escalate over an entry that is
    not even wrong; and not corrected, because the word itself is the only thing
    that would explain afterwards why a service of the organisation's own was out
    of reach. `ServiceDependency.is_ours` is what makes that safe: it tests for
    the word that means ours, so anything unfamiliar withholds authority rather
    than granting it.

    An entry missing a field it should have is the one thing that does fail. A
    dependency with no name is not a dependency - nothing can be addressed to it
    and nothing can be looked up by it - and reading it as an entry with an empty
    name would put a nameless row in front of the model as though the register
    had described something.
    """
    listed = fetch(service).get(DEPENDENCIES_FIELD, [])

    return [_a_dependency_from(entry, service) for entry in listed]


def _a_dependency_from(entry: dict[str, Any], service: str) -> ServiceDependency:
    """One register entry as the type Mitigation weighs.

    Raises `RegistryUnavailable` for an entry that is missing what an entry has
    to have. The exception says the register could not be read rather than that
    one row was odd, because that is what is true from a caller's point of view:
    what it asked for was the estate, and an estate it has been given part of is
    not one it can decide reachability from.
    """
    try:
        return ServiceDependency(
            name=entry[NAME_FIELD],
            purpose=entry[PURPOSE_FIELD],
            host=entry[HOST_FIELD],
            owner=entry[OWNER_FIELD],
            ownership=entry[OWNERSHIP_FIELD]
        )
    except (KeyError, TypeError) as error:
        raise RegistryUnavailable(
            f"the service register's entry for [{service}] is missing "
            f"{error}: {entry!r}"
        ) from error


def _service_path(settings: TargetServiceRegisterSettings, service: str) -> str:
    """The path with the service named in it.

    A path naming no service formats to itself, exactly as the deploy reader's
    does, so a register with one route and no parameter is configurable without a
    second setting saying which kind it is.
    """
    return settings.service_registry_service_path.format(service=service)
