"""The register of what calls what, and whose each one is.

Two layers, as the flag reader has them and for the same reason: one makes the
request and is where a URL and an outage live, and the other maps the answer onto
the type Mitigation weighs.

The mapping is where the work is, and all of it is about the one field a caller
cannot check for itself. An outage must not read as a service that calls nothing,
because an estate that looks empty is one where every address is out of reach. A
word this system has never heard must not read as permission, and must not stop
the register being read either - it comes through as a dependency Argus may not
touch, keeping the word, so the incident can say which of those two happened.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import create_autospec

import httpx2
import pytest
from argus_core import Settings
from argus_core.models import Ownership, ServiceDependency
from argus_testkit import raising, returning
from argus_testkit.assertions import Assertion, all_of, an_error_was_raised
from argus_testkit.scenario import Scenario, attempting, calling
from read_mcp_server.registry import (
    RegistryUnavailable,
    ServiceRegistrySettings,
    fetch_registered_service,
    what_a_service_depends_on,
)

SOME_SERVICE = "io-shop"


@pytest.mark.unit
def test_a_registered_dependency_becomes_one_argus_can_weigh() -> None:
    registry = a_mock_registry()

    Scenario() \
        .given(
            calling(returning(registry, a_register_listing(
                _an_entry(name="io-pricing", ownership="internal")
            )))
        ) \
        .when(
            lambda: what_a_service_depends_on(SOME_SERVICE, fetch=registry)
        ) \
        .then(all_of(
            _the_dependencies_are("io-pricing"),
            _the_first_one_is_ours(True)
        ))


@pytest.mark.unit
def test_a_third_partys_entry_comes_back_as_somebody_elses() -> None:
    # The single fact this channel exists to carry. Read the wrong way round,
    # Argus either escalates an incident it could have ended or addresses a
    # mitigation to a company that does not run the service.
    registry = a_mock_registry()

    Scenario() \
        .given(
            calling(returning(registry, a_register_listing(
                _an_entry(name="io-pay", ownership="third-party")
            )))
        ) \
        .when(
            lambda: what_a_service_depends_on(SOME_SERVICE, fetch=registry)
        ) \
        .then(_the_first_one_is_ours(False))


@pytest.mark.unit
def test_a_dependency_carries_what_it_is_for() -> None:
    # A responder who has just learned the failing page calls something wants to
    # know what for, and so does the model: an incident is diagnosed from what
    # the dependency was doing on the request path, not from its name.
    some_purpose = "prices a basket while the account page renders"
    registry = a_mock_registry()

    Scenario() \
        .given(
            calling(returning(registry, a_register_listing(
                _an_entry(name="io-pricing", purpose=some_purpose)
            )))
        ) \
        .when(
            lambda: what_a_service_depends_on(SOME_SERVICE, fetch=registry)
        ) \
        .then(_the_first_ones_purpose_is(some_purpose))


@pytest.mark.unit
def test_a_service_nobody_registered_depends_on_nothing() -> None:
    # A real answer rather than a failure: the register holds no entry, which is
    # a fact about the register. What it must not be is indistinguishable from
    # an outage, which is what the case below is about.
    registry = a_mock_registry()

    Scenario() \
        .given(
            calling(returning(registry, a_register_listing()))
        ) \
        .when(
            lambda: what_a_service_depends_on("io-billing", fetch=registry)
        ) \
        .then(_there_are_no_dependencies())


@pytest.mark.unit
def test_an_unreadable_ownership_survives_as_a_dependency_argus_may_not_touch() -> None:
    # The register belongs to the organisation and will grow words this system
    # has never heard. Neither shortcut is acceptable: read as ours it sends a
    # restart into an estate nobody authorised, and refused outright it would
    # have one new word anywhere in the register stop Argus reading any of it, so
    # every incident would escalate over an entry that is not even wrong.
    #
    # So the entry comes through, says it is not ours, and keeps the word - which
    # is what lets the account of the incident say the register answered
    # something Argus does not recognise, rather than reporting a service of the
    # organisation's own as somebody else's.
    registry = a_mock_registry()

    Scenario() \
        .given(
            calling(returning(registry, a_register_listing(
                _an_entry(name="io-pricing", ownership="shared-with-a-partner")
            )))
        ) \
        .when(
            lambda: what_a_service_depends_on(SOME_SERVICE, fetch=registry)
        ) \
        .then(all_of(
            _the_dependencies_are("io-pricing"),
            _the_first_one_is_ours(False),
            _the_first_one_is_recognised(False)
        ))


@pytest.mark.unit
def test_a_register_that_cannot_be_reached_is_not_a_service_with_no_dependencies() -> None:
    # The same rule the flag reader keeps, and it matters more here: "the
    # register was down" read as "it calls nothing" would leave the estate
    # looking empty, and an empty estate is one where every address is outside
    # what Argus may touch - so an outage would silently forbid every
    # mitigation rather than reporting itself.
    registry = a_mock_registry()

    Scenario() \
        .given(
            calling(raising(registry, RegistryUnavailable("nobody answered")))
        ) \
        .when(
            attempting(
                lambda: what_a_service_depends_on(SOME_SERVICE, fetch=registry)
            )
        ) \
        .then(an_error_was_raised(RegistryUnavailable))


@pytest.mark.unit
def test_the_request_goes_to_the_service_it_was_asked_about() -> None:
    # The path is a template, as the deploy reader's is, so the demo's route and
    # a real register's are the same setting with different values.
    get = a_mock_http_get()
    get.return_value = _a_response(a_register_listing())

    Scenario() \
        .given(
            some_settings := _some_registry_settings(
                base_url="http://registry.invalid",
                service_path="/registry/services/{service}"
            )
        ) \
        .when(
            lambda: fetch_registered_service(SOME_SERVICE, some_settings, get=get)
        ) \
        .then(_the_url_asked_for(
            get, "http://registry.invalid/registry/services/io-shop"
        ))


@pytest.mark.unit
def test_a_register_answering_an_error_status_is_an_outage() -> None:
    get = a_mock_http_get()
    get.side_effect = httpx2.HTTPError("500 Server Error")

    Scenario() \
        .given(
            some_settings := _some_registry_settings()
        ) \
        .when(
            attempting(
                lambda: fetch_registered_service(SOME_SERVICE, some_settings, get=get)
            )
        ) \
        .then(an_error_was_raised(RegistryUnavailable))


@pytest.mark.unit
def test_the_register_is_configurable_from_the_environment_argus_runs_under() -> None:
    # A slice only narrows if `Settings` actually holds every field it names,
    # and nothing else here would find out: the narrowing happens once, where
    # the server is composed, and a missing field fails there - at start-up, in a
    # process nobody is watching - rather than where it was going to be read.
    #
    # It carries exactly two, and the absence is as deliberate as the presence:
    # no credential. A register of what calls what is not secret inside the
    # organisation keeping it, and a field for one here would be a field the read
    # tier could be handed a mutating token in.
    Scenario() \
        .given(the_environment := Settings()) \
        .when(lambda: ServiceRegistrySettings.of(the_environment)) \
        .then(all_of(
            _it_carries_exactly({
                "service_registry_base_url",
                "service_registry_service_path"
            }),
            _the_path_names_the_service_it_is_asked_about()
        ))


def _it_carries_exactly(field_names: set[str]) -> Assertion[ServiceRegistrySettings]:
    def assertion(narrowed: ServiceRegistrySettings) -> bool:
        carried = set(type(narrowed).model_fields)

        if carried != field_names:
            raise AssertionError(
                f"Expected the slice to carry exactly {sorted(field_names)}, and "
                f"it carries {sorted(carried)}."
            )

        return True

    return assertion


def _the_path_names_the_service_it_is_asked_about() -> Assertion[ServiceRegistrySettings]:
    """That the configured path has somewhere to put a service name.

    A path with no placeholder formats to itself, which is deliberate - a
    register with one route stays configurable - but the deployment default is
    the demo's, and that one is per service. A default that quietly asked the
    same URL for every service would have every incident read one service's
    dependencies.
    """
    def assertion(narrowed: ServiceRegistrySettings) -> bool:
        if "{service}" not in narrowed.service_registry_service_path:
            raise AssertionError(
                f"The configured register path "
                f"[{narrowed.service_registry_service_path}] names no service, "
                f"so every service would be looked up at the same URL."
            )

        return True

    return assertion


def a_mock_registry() -> Any:
    """A stand-in for whatever asks the register, spec'd against the port.

    Not against `fetch_registered_service`: that takes the settings it reads
    under, and what maps the answer only names a service.
    """
    from read_mcp_server.registry import FetchRegisteredService

    return create_autospec(FetchRegisteredService, instance=True)


def a_mock_http_get() -> Any:
    return create_autospec(httpx2.get)


def a_register_listing(*entries: dict[str, Any]) -> dict[str, Any]:
    return {"service": SOME_SERVICE, "dependencies": list(entries)}


def _an_entry(name: str = "some-service",
              purpose: str = "something the caller needs",
              host: str = "some-service.example",
              owner: str = "some-team",
              ownership: str = Ownership.INTERNAL) -> dict[str, Any]:
    return {
        "name": name,
        "purpose": purpose,
        "host": host,
        "owner": owner,
        "ownership": ownership
    }


def _a_response(body: dict[str, Any]) -> Any:
    response = create_autospec(httpx2.Response, instance=True)
    response.json.return_value = body

    return response


def _some_registry_settings(
    base_url: str = "http://registry.invalid",
    service_path: str = "/registry/services/{service}"
) -> ServiceRegistrySettings:
    return ServiceRegistrySettings(
        service_registry_base_url=base_url,
        service_registry_service_path=service_path
    )


def _the_dependencies_are(*expected: str) -> Assertion[list[ServiceDependency]]:
    def assertion(found: list[ServiceDependency]) -> bool:
        named = [dependency.name for dependency in found]

        if named != list(expected):
            raise AssertionError(
                f"Expected the register to report {list(expected)}, got {named}."
            )

        return True

    return assertion


def _the_first_one_is_ours(expected: bool) -> Assertion[list[ServiceDependency]]:
    def assertion(found: list[ServiceDependency]) -> bool:
        if not found:
            raise AssertionError(
                "Expected one dependency to weigh ownership of, and the "
                "register reported none at all."
            )

        if found[0].is_ours is not expected:
            raise AssertionError(
                f"Expected [{found[0].name}] to report is_ours as [{expected}], "
                f"and it reported [{found[0].is_ours}] from an ownership of "
                f"[{found[0].ownership}]."
            )

        return True

    return assertion


def _the_first_ones_purpose_is(expected: str) -> Assertion[list[ServiceDependency]]:
    def assertion(found: list[ServiceDependency]) -> bool:
        if not found or found[0].purpose != expected:
            raise AssertionError(
                f"Expected the dependency to be for [{expected}], got "
                f"[{found[0].purpose if found else None}]."
            )

        return True

    return assertion


def _there_are_no_dependencies() -> Assertion[list[ServiceDependency]]:
    def assertion(found: list[ServiceDependency]) -> bool:
        if found:
            raise AssertionError(
                f"Expected a service the register holds no entry for to report "
                f"no dependencies, and it reported "
                f"{[dependency.name for dependency in found]}."
            )

        return True

    return assertion


def _the_first_one_is_recognised(expected: bool) -> Assertion[list[ServiceDependency]]:
    """That a word Argus knows is distinguishable from one it does not.

    Nothing gates on this, which is why it needs asserting: a field nothing
    refuses on can be wrong for a long time without anything failing, and what
    it is wrong about is the sentence a reader gets when a service of their own
    turns out to be unreachable.
    """
    def assertion(found: list[ServiceDependency]) -> bool:
        if not found:
            raise AssertionError(
                "Expected one dependency to weigh ownership of, and the "
                "register reported none at all."
            )

        if found[0].is_recognised is not expected:
            raise AssertionError(
                f"Expected an ownership of [{found[0].ownership}] to report "
                f"is_recognised as [{expected}], and it reported "
                f"[{found[0].is_recognised}]."
            )

        return True

    return assertion


def _the_url_asked_for(get: Any, expected: str) -> Assertion[Any]:
    def assertion(dont_care: Any) -> bool:
        asked = get.call_args.args[0] if get.call_args.args else None

        if asked != expected:
            raise AssertionError(
                f"Expected the register to be asked for [{expected}], and it "
                f"was asked for [{asked}]."
            )

        return True

    return assertion
