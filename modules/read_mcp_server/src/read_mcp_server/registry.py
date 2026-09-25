"""What a service calls, read from the organisation's own register (spec §12.1).

The read tier's view of the service register, and the only place in Argus that
knows its wire shape. Everything above sees `ServiceDependency`.

Two layers, both public, because they fail for different reasons:
`fetch_registered_service` makes the HTTP request and is where a URL and an
outage live, while `what_a_service_depends_on` maps the answer onto the type its
callers reason about.

The register is worth a channel of its own because of one field. What a service
calls, where, and what for are all recoverable from its source and its failures;
whether the thing on the other end belongs to the same organisation is not, and
it is what decides the response to a propagation incident. A neighbour's process
can be restarted. Another company's outage can only be named and handed over.

Nothing here infers that. A host that looks internal looks that way because
somebody chose the spelling, and the owning team does not settle it either -
somebody here owns the *integration* with a vendor. It is recorded by a person
and looked up, which is also why the register is a channel that can be wrong in
ways this module has to survive rather than resolve.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Final, Protocol

import httpx
from argus_core import SettingsSlice
from argus_core.models import ServiceDependency

__all__ = [
    "FetchRegisteredService",
    "RegistryUnavailable",
    "ServiceRegistrySettings",
    "fetch_registered_service",
    "what_a_service_depends_on"
]

# The register's own field names. Named rather than spelled at the point of use,
# for the reason every other external vocabulary in this package is: the
# register is somebody else's document, and a literal buried in a comprehension
# is a literal nobody finds when that document changes.
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


class ServiceRegistrySettings(SettingsSlice):
    """Where the register answers, and under what path.

    A template path rather than a fixed route, as the deploy reader's is: the
    demo's `/registry/services/{service}` and whatever a real register spells it
    is are the same setting with different values.

    No credential. A register of what calls what is not secret inside the
    organisation that keeps it, and a field for one here would be a field the
    read tier could be handed a mutating credential in - see `flags`, which makes
    the same argument about a type that cannot name what it must not hold.
    """

    service_registry_base_url: str
    service_registry_service_path: str


HttpGet = Callable[..., httpx.Response]


class FetchRegisteredService(Protocol):
    """What `what_a_service_depends_on` needs from whatever asks the register.

    A `Protocol` rather than a `Callable` alias so a test can stand it in with
    `create_autospec`, which needs something introspectable. Specing against the
    concrete fetcher would be specing against a different shape: that one takes
    the settings it reads under, and what maps its answer holds none.
    """

    def __call__(self, service: str) -> dict[str, Any]: ...


class RegistryUnavailable(Exception):
    """The register could not be asked what a service depends on.

    Deliberately not an empty list, and the consequence here is worse than the
    flag reader's. "The register was down" read as "it calls nothing" leaves the
    estate looking empty - and an estate with nothing in it is one where every
    address is outside what Argus may touch, so an outage would quietly forbid
    every mitigation instead of reporting itself.
    """


def fetch_registered_service(
    service: str,
    settings: ServiceRegistrySettings,
    get: HttpGet = httpx.get
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


def _service_path(settings: ServiceRegistrySettings, service: str) -> str:
    """The path with the service named in it.

    A path naming no service formats to itself, exactly as the deploy reader's
    does, so a register with one route and no parameter is configurable without a
    second setting saying which kind it is.
    """
    return settings.service_registry_service_path.format(service=service)
