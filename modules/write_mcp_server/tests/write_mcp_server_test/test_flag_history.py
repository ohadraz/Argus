"""What the flag provider's event log says changed, and in what order.

Current state cannot answer the question Mitigation asks. A flag that is off
now was either switched off into this incident or has been off for a year, and
only the history tells those apart - so what is read here is the log of
changes, not the state, and every rule below is about which rows of it count.

Order is the other half, and it is load-bearing rather than cosmetic. The
latest change is what decides which way a flag gets reverted, so a reader that
returned them backwards would make Argus switch a flag off when it should
switch it on.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import create_autospec

import httpx
import pytest
from argus_core.models import FlagChange
from argus_testkit import Assertion, Scenario, an_error_was_raised, attempting
from write_mcp_server.flag_history import (
    FlagHistoryUnavailable,
    recent_flag_changes,
)
from write_mcp_server.flag_state import FlagWriteSettings

DONT_CARE_FLAG = "dont-care-flag"

SINCE = "2026-08-20T11:00:00Z"
BEFORE_THE_WINDOW = "2026-08-20T10:31:07.881Z"
INSIDE_THE_WINDOW = "2026-08-20T11:04:38.033Z"
LATER_IN_THE_WINDOW = "2026-08-20T11:09:12.581Z"


@pytest.mark.unit
def test_a_flag_that_was_switched_on_is_reported_as_enabled() -> None:
    some_flag = "monthly-spend-feature"

    Scenario() \
        .given(
            provider := a_provider_reporting(
                [an_enabling_of(some_flag, at=INSIDE_THE_WINDOW)]
            )
        ) \
        .when(
            lambda: recent_flag_changes(SINCE, settings=some_settings(), get=provider.get)
        ) \
        .then(
            _what_changed_was([(some_flag, True)])
        )


@pytest.mark.unit
def test_a_flag_that_was_switched_off_is_reported_as_disabled() -> None:
    # The case current state cannot answer. A flag switched off into an
    # incident is off now, and so is every flag that has been off for a year -
    # only the history tells the two apart, and only it carries the direction.
    some_flag = "monthly-spend-feature"

    Scenario() \
        .given(
            provider := a_provider_reporting(
                [a_disabling_of(some_flag, at=INSIDE_THE_WINDOW)]
            )
        ) \
        .when(
            lambda: recent_flag_changes(SINCE, settings=some_settings(), get=provider.get)
        ) \
        .then(
            _what_changed_was([(some_flag, False)])
        )


@pytest.mark.unit
def test_changes_before_the_window_are_not_reported() -> None:
    Scenario() \
        .given(
            provider := a_provider_reporting(
                [an_enabling_of(DONT_CARE_FLAG, at=BEFORE_THE_WINDOW)]
            )
        ) \
        .when(
            lambda: recent_flag_changes(SINCE, settings=some_settings(), get=provider.get)
        ) \
        .then(
            _nothing_was_reported()
        )


@pytest.mark.unit
def test_changes_in_another_environment_are_not_reported() -> None:
    # One Target Service maps to one environment. A flag toggled in staging did
    # not cause the incident in production, and reverting it would change an
    # environment nobody was looking at.
    Scenario() \
        .given(
            provider := a_provider_reporting(
                [an_enabling_of(DONT_CARE_FLAG, at=INSIDE_THE_WINDOW, environment="development")]
            )
        ) \
        .when(
            lambda: recent_flag_changes(
                SINCE, settings=some_settings(environment="production"), get=provider.get
            )
        ) \
        .then(
            _nothing_was_reported()
        )


@pytest.mark.unit
def test_events_that_are_not_flag_toggles_are_not_reported() -> None:
    # The provider's log records everything it does to itself - features
    # created, strategies added, tokens issued. None of them changed what the
    # service evaluates, so none of them is a change to undo.
    Scenario() \
        .given(
            provider := a_provider_reporting(
                [
                    an_event_of_type("feature-created", DONT_CARE_FLAG, at=INSIDE_THE_WINDOW),
                    an_event_of_type(
                        "feature-strategy-add", DONT_CARE_FLAG, at=INSIDE_THE_WINDOW
                    ),
                    an_event_of_type("api-token-created", None, at=INSIDE_THE_WINDOW)
                ]
            )
        ) \
        .when(
            lambda: recent_flag_changes(SINCE, settings=some_settings(), get=provider.get)
        ) \
        .then(
            _nothing_was_reported()
        )


@pytest.mark.unit
def test_changes_are_reported_oldest_first() -> None:
    # The provider answers newest first. Callers ask which change was *latest*,
    # and every other windowed read in Argus runs in time order - one direction
    # for all of them, decided here rather than at each call site.
    some_flag = "monthly-spend-feature"

    Scenario() \
        .given(
            provider := a_provider_reporting(
                [
                    a_disabling_of(some_flag, at=LATER_IN_THE_WINDOW, event_id=12),
                    an_enabling_of(some_flag, at=INSIDE_THE_WINDOW, event_id=11)
                ]
            )
        ) \
        .when(
            lambda: recent_flag_changes(SINCE, settings=some_settings(), get=provider.get)
        ) \
        .then(
            _they_were_reported_in_this_order([True, False])
        )


@pytest.mark.unit
def test_two_changes_within_the_same_second_keep_the_order_they_happened_in() -> None:
    # Timestamps are recorded to the second, and a flag switched on and then
    # straight back off produces two changes inside one of them. Ordering on
    # the timestamp alone leaves those two tied, and a stable sort then keeps
    # whatever order the provider listed them in - which is newest first, so
    # "the latest change" silently becomes the earliest one.
    #
    # That is not a cosmetic ordering bug: the latest change is what decides
    # which way a flag gets reverted, so getting it backwards makes Argus
    # switch a flag off when it should switch it on. The provider's own event
    # ids are the sequence it actually recorded, and they do not tie.
    some_flag = "legacy-checkout-fallback"
    the_same_second = INSIDE_THE_WINDOW

    Scenario() \
        .given(
            provider := a_provider_reporting(
                [
                    a_disabling_of(some_flag, at=the_same_second, event_id=13),
                    an_enabling_of(some_flag, at=the_same_second, event_id=12)
                ]
            )
        ) \
        .when(
            lambda: recent_flag_changes(SINCE, settings=some_settings(), get=provider.get)
        ) \
        .then(
            _they_were_reported_in_this_order([True, False])
        )


@pytest.mark.unit
def test_a_change_is_reported_with_who_made_it() -> None:
    # Whose change it was is what will one day tell Argus's own revert from a
    # human's. It is recorded now because the provider says it now.
    some_actor = "admin"

    Scenario() \
        .given(
            provider := a_provider_reporting(
                [an_enabling_of(DONT_CARE_FLAG, at=INSIDE_THE_WINDOW, created_by=some_actor)]
            )
        ) \
        .when(
            lambda: recent_flag_changes(SINCE, settings=some_settings(), get=provider.get)
        ) \
        .then(
            _the_first_change_was_made_by(some_actor)
        )


@pytest.mark.unit
def test_reading_the_history_uses_the_credential_that_can_read_it() -> None:
    # The provider issues no read-only admin credential, which is why this read
    # lives in the write process at all.
    some_admin_token = "*:*.some-admin-token"

    Scenario() \
        .given(
            provider := a_provider_reporting([])
        ) \
        .when(
            lambda: recent_flag_changes(
                SINCE, settings=some_settings(admin_token=some_admin_token), get=provider.get
            )
        ) \
        .then(
            _it_was_read_with(provider, some_admin_token)
        )


@pytest.mark.unit
def test_an_unreachable_provider_is_not_reported_as_an_empty_history() -> None:
    # "Nothing changed" is a conclusion Mitigation acts on - it escalates. An
    # outage read as an empty history would look like an environment with
    # nothing to revert, which is a different incident entirely.
    some_transport_error = httpx.ConnectError("connection refused")
    provider = a_provider_reporting([])
    provider.get.side_effect = some_transport_error

    Scenario() \
        .when(
            attempting(
                lambda: recent_flag_changes(
                    SINCE, settings=some_settings(), get=provider.get
                )
            )
        ) \
        .then(
            an_error_was_raised(FlagHistoryUnavailable)
        )


class _Provider:
    def __init__(self) -> None:
        self.get: Any = create_autospec(httpx.get)


def a_provider_reporting(events: list[dict[str, Any]]) -> _Provider:
    provider = _Provider()
    provider.get.return_value = httpx.Response(
        status_code=200,
        json={"version": 1, "events": events, "totalEvents": len(events)},
        request=httpx.Request("GET", "http://flags.invalid/")
    )
    return provider


def an_enabling_of(flag: str,
                   at: str,
                   environment: str = "production",
                   created_by: str = "dont-care-actor",
                   event_id: int = 11) -> dict[str, Any]:
    return an_event_of_type(
        "feature-environment-enabled", flag, at, environment, created_by, event_id
    )


def a_disabling_of(flag: str,
                   at: str,
                   environment: str = "production",
                   created_by: str = "dont-care-actor",
                   event_id: int = 11) -> dict[str, Any]:
    return an_event_of_type(
        "feature-environment-disabled", flag, at, environment, created_by, event_id
    )


def an_event_of_type(event_type: str,
                     flag: str | None,
                     at: str,
                     environment: str = "production",
                     created_by: str = "dont-care-actor",
                     event_id: int = 11) -> dict[str, Any]:
    """One row of the provider's event log, in its own wire shape."""
    return {
        "id": event_id,
        "type": event_type,
        "createdBy": created_by,
        "createdAt": at,
        "featureName": flag,
        "project": "default",
        "environment": environment
    }


def some_settings(environment: str = "production",
                  admin_token: str = "*:*.dont-care-admin-token") -> FlagWriteSettings:
    """The slice this reader runs under.

    The same slice the writer takes, because the provider's history is served
    to admin tokens only - reading it is a write-tier act performed by the
    process that already holds the credential.
    """
    dont_care_frontend_token = "default:production.dont-care-frontend-token"
    dont_care_project = "default"

    return FlagWriteSettings(
        unleash_base_url="http://flags.invalid",
        unleash_frontend_token=dont_care_frontend_token,
        unleash_project=dont_care_project,
        unleash_environment=environment,
        unleash_admin_token=admin_token
    )


def _what_changed_was(expected: list[tuple[str, bool]]) -> Assertion[list[FlagChange]]:
    """Which flags were reported, and which way each of them went.

    The pair rather than either half: a reader that found the right flag and
    read its direction backwards is the failure this whole module exists to
    prevent, and naming only the flag would pass it.
    """
    def assertion(changes: list[FlagChange]) -> bool:
        reported = [(change.flag, change.enabled) for change in changes]
        if reported != expected:
            raise AssertionError(f"Expected {expected} to have changed, got {reported}.")

        return True

    return assertion


def _nothing_was_reported() -> Assertion[list[FlagChange]]:
    """That a row the reader must ignore reached nobody.

    Distinct from an empty provider: every case using this hands over a log
    with something in it, so an empty answer is the reader having excluded
    it rather than having found nothing.
    """
    def assertion(changes: list[FlagChange]) -> bool:
        if changes:
            raise AssertionError(f"Expected nothing to be reported, got {changes}.")

        return True

    return assertion


def _they_were_reported_in_this_order(expected: list[bool]) -> Assertion[list[FlagChange]]:
    """The directions in the order they were handed back.

    Order is the claim, so it is asserted as a sequence rather than as a set.
    Which change is last decides which way a revert goes.
    """
    def assertion(changes: list[FlagChange]) -> bool:
        reported = [change.enabled for change in changes]
        if reported != expected:
            raise AssertionError(f"Expected the order {expected}, got {reported}.")

        return True

    return assertion


def _the_first_change_was_made_by(expected: str) -> Assertion[list[FlagChange]]:
    def assertion(changes: list[FlagChange]) -> bool:
        if not changes:
            raise AssertionError(f"Expected a change made by [{expected}], got none at all.")

        if changes[0].actor != expected:
            raise AssertionError(
                f"Expected a change made by [{expected}], got [{changes[0].actor}]."
            )

        return True

    return assertion


def _it_was_read_with(provider: _Provider, expected: str) -> Assertion[list[FlagChange]]:
    """That the credential sent was the one the provider serves this to.

    Read off the call rather than off the answer, because a reader that asked
    with the wrong token would be answered by the double either way - the
    double is not the provider and does not refuse.
    """
    def assertion(dont_care_changes: list[FlagChange]) -> bool:
        asked_with = provider.get.call_args.kwargs["headers"]["Authorization"]
        if asked_with != expected:
            raise AssertionError(f"Expected the read to use [{expected}], got [{asked_with}].")

        return True

    return assertion
