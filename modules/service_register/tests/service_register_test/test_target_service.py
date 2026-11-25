"""The register of what calls what, and whose each one is.

Two layers, as the flag reader has them and for the same reason: one makes the
request and is where a URL and an outage live, and the other maps the answer onto
the type Mitigation weighs. The adapter is the two composed, behind the port.

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
from argus_testkit import raising, returning, the_answer_was
from argus_testkit.assertions import Assertion, all_of, an_error_was_raised
from argus_testkit.scenario import Scenario, attempting, calling
from core.models import Ownership, ServiceDependency
from service_register import RegistryUnavailable
from service_register.target_service import (
    FetchRegisteredService,
    TargetServiceRegister,
    TargetServiceRegisterSettings,
    fetch_registered_service,
    what_a_service_depends_on,
)

SOME_SERVICE = "io-shop"
SOME_BASE_URL = "http://registry.invalid"
SOME_SERVICE_PATH = "/registry/services/{service}"


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
                base_url=SOME_BASE_URL,
                service_path=SOME_SERVICE_PATH
            )
        ) \
        .when(
            lambda: fetch_registered_service(SOME_SERVICE, some_settings, get=get)
        ) \
        .then(_the_url_asked_for(
            get, f"{SOME_BASE_URL}{SOME_SERVICE_PATH.format(service=SOME_SERVICE)}"
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
def test_the_adapter_asks_the_register_about_the_service_and_maps_what_it_holds() -> None:
    # The port's one call is the two layers composed: asked at the address the
    # deployment configured, about the service named, and answered as the type
    # Mitigation weighs.
    get = a_mock_http_get()
    get.return_value = _a_response(a_register_listing(
        _an_entry(name="io-pay", ownership="third-party")
    ))

    Scenario() \
        .given(
            register := TargetServiceRegister(_some_registry_settings(), get=get)
        ) \
        .when(
            lambda: register.dependencies_of(SOME_SERVICE)
        ) \
        .then(all_of(
            _the_url_asked_for(
                get, f"{SOME_BASE_URL}{SOME_SERVICE_PATH.format(service=SOME_SERVICE)}"
            ),
            _the_dependencies_are("io-pay"),
            _the_first_one_is_ours(False)
        ))


@pytest.mark.unit
def test_the_register_carries_where_it_is_and_no_credential() -> None:
    # The settings carry exactly two fields, and the absence is as deliberate as
    # the presence: no credential. A register of what calls what is not secret
    # inside the organisation keeping it, and a field for one here would be a
    # field the read tier could be handed a mutating token in. Read off the
    # declared defaults rather than off a `TargetServiceRegisterSettings()`,
    # which would read the developer's own environment.
    Scenario() \
        .given() \
        .when(lambda: TargetServiceRegisterSettings.model_construct()) \
        .then(all_of(
            _it_carries_exactly({
                "service_registry_base_url",
                "service_registry_service_path"
            }),
            _the_path_names_the_service_it_is_asked_about()
        ))


@pytest.mark.unit
def test_the_register_is_configured_by_the_variables_it_always_was(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    # The names a deployment already sets, unchanged by the move out of the
    # kernel's `Settings` - a renamed variable is a deployment that silently
    # falls back to its defaults.
    some_base_url = "http://kuki.invalid:8181"
    some_service_path = "/buki/{service}/calls"

    Scenario() \
        .given(
            calling(lambda: monkeypatch.setenv("SERVICE_REGISTRY_BASE_URL", some_base_url)),
            calling(lambda: monkeypatch.setenv("SERVICE_REGISTRY_SERVICE_PATH",
                                               some_service_path))
        ) \
        .when(lambda: TargetServiceRegisterSettings()) \
        .then(the_answer_was(TargetServiceRegisterSettings(
            service_registry_base_url=some_base_url,
            service_registry_service_path=some_service_path
        )))


@pytest.mark.unit
def test_an_unconfigured_register_is_the_demos() -> None:
    # The defaults the kernel's `Settings` declared before the settings moved,
    # spelled out because there is nothing left to derive them from. Read off
    # the declared defaults rather than off a `TargetServiceRegisterSettings()`,
    # which would read the developer's own environment. The demo Target Service
    # stands in for the register, so its address is the shop's.
    the_demos_register = "http://localhost:8080"
    the_demos_route = "/registry/services/{service}"

    Scenario() \
        .when(lambda: TargetServiceRegisterSettings.model_construct().model_dump()) \
        .then(the_answer_was({
            "service_registry_base_url": the_demos_register,
            "service_registry_service_path": the_demos_route
        }))


def _it_carries_exactly(field_names: set[str]) -> Assertion[TargetServiceRegisterSettings]:
    def assertion(settings: TargetServiceRegisterSettings) -> bool:
        carried = set(type(settings).model_fields)

        if carried != field_names:
            raise AssertionError(
                f"Expected the settings to carry exactly {sorted(field_names)}, and "
                f"they carry {sorted(carried)}."
            )

        return True

    return assertion


def _the_path_names_the_service_it_is_asked_about(
) -> Assertion[TargetServiceRegisterSettings]:
    """That the configured path has somewhere to put a service name.

    A path with no placeholder formats to itself, which is deliberate - a
    register with one route stays configurable - but the deployment default is
    the demo's, and that one is per service. A default that quietly asked the
    same URL for every service would have every incident read one service's
    dependencies.
    """
    def assertion(settings: TargetServiceRegisterSettings) -> bool:
        if "{service}" not in settings.service_registry_service_path:
            raise AssertionError(
                f"The configured register path "
                f"[{settings.service_registry_service_path}] names no service, "
                f"so every service would be looked up at the same URL."
            )

        return True

    return assertion


def a_mock_registry() -> Any:
    """A stand-in for whatever asks the register, spec'd against the protocol.

    Not against `fetch_registered_service`: that takes the settings it reads
    under, and what maps the answer only names a service.
    """
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
    base_url: str = SOME_BASE_URL,
    service_path: str = SOME_SERVICE_PATH
) -> TargetServiceRegisterSettings:
    return TargetServiceRegisterSettings(
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
