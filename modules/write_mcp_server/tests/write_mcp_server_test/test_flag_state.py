"""Changing a flag, and recording enough to change it back.

The write tier's one act on the flag provider, and the only place Argus holds
a credential that can alter what the Target Service evaluates. Two things are
being claimed here and they are separate: that the right flag in the right
environment was addressed with the right credential, and that the call did not
return until the provider was actually serving the new value.

The second matters because a toggle is not instantly visible through the
evaluation API. Returning early would hand Mitigation a window in which it
reads the old value and refutes a hypothesis that was right.

What comes back is the undo - the state to restore, not the call that would
restore it - and it carries the provider's own time for the write rather than
this process's, since an undo compares it against the provider's log.
"""

from __future__ import annotations

from datetime import UTC, datetime
from email.utils import format_datetime
from typing import Any
from unittest.mock import create_autospec

import httpx
import pytest
from argus_core.models import FlagUndo
from argus_testkit import Assertion, Scenario, all_of, an_error_was_raised, attempting
from write_mcp_server.flag_state import (
    EvaluateFlags,
    FlagNotSet,
    FlagWriteSettings,
    set_flag,
)

DONT_CARE_FLAG = "dont-care-flag"


@pytest.mark.unit
def test_setting_a_flag_off_addresses_its_environment() -> None:
    some_flag = "monthly-spend-feature"
    some_project = "default"
    some_environment = "production"

    Scenario() \
        .given(
            provider := a_flag_provider_reporting([])
        ) \
        .when(
            lambda: set_flag(
                some_flag,
                enabled=False,
                settings=some_settings(project=some_project, environment=some_environment),
                post=provider.post,
                evaluate=provider.evaluate
            )
        ) \
        .then(
            _the_write_addressed(
                provider,
                f"/api/admin/projects/{some_project}/features/{some_flag}"
                f"/environments/{some_environment}/off"
            )
        )


@pytest.mark.unit
def test_setting_a_flag_on_addresses_its_environment() -> None:
    # The direction that did not exist before. An incident can be caused by a
    # flag being withdrawn - a fallback disabled, traffic moved back to a path
    # that has since rotted - and an agent that can only turn flags off cannot
    # mitigate that incident at all.
    some_flag = "monthly-spend-feature"
    some_project = "default"
    some_environment = "production"

    Scenario() \
        .given(
            provider := a_flag_provider_reporting([some_flag])
        ) \
        .when(
            lambda: set_flag(
                some_flag,
                enabled=True,
                settings=some_settings(project=some_project, environment=some_environment),
                post=provider.post,
                evaluate=provider.evaluate
            )
        ) \
        .then(
            _the_write_addressed(
                provider,
                f"/api/admin/projects/{some_project}/features/{some_flag}"
                f"/environments/{some_environment}/on"
            )
        )


@pytest.mark.unit
def test_setting_a_flag_uses_the_credential_that_can_change_state() -> None:
    # The write tier exists to hold this one. A change authenticating with the
    # evaluation credential would fail against a real provider, and the tier
    # split would be describing a boundary the code does not actually use.
    some_admin_token = "*:*.some-admin-token"

    Scenario() \
        .given(
            provider := a_flag_provider_reporting([])
        ) \
        .when(
            lambda: set_flag(
                DONT_CARE_FLAG,
                enabled=False,
                settings=some_settings(admin_token=some_admin_token),
                post=provider.post,
                evaluate=provider.evaluate
            )
        ) \
        .then(
            _the_write_used(provider, some_admin_token)
        )


@pytest.mark.unit
def test_setting_a_flag_off_returns_only_once_it_evaluates_off() -> None:
    # A toggle is not instantly visible through the evaluation API. Returning
    # before it is would hand Mitigation a window in which it reads the old
    # value and refutes a hypothesis that was right.
    Scenario() \
        .given(
            provider := a_flag_provider_still_reporting_it_on_twice()
        ) \
        .when(
            lambda: set_flag(
                DONT_CARE_FLAG,
                enabled=False,
                settings=some_settings(),
                post=provider.post,
                evaluate=provider.evaluate
            )
        ) \
        .then(
            _it_kept_asking_until_it_agreed(provider, times=3)
        )


@pytest.mark.unit
def test_setting_a_flag_on_returns_only_once_it_evaluates_on() -> None:
    Scenario() \
        .given(
            provider := a_flag_provider_still_reporting_it_off_twice()
        ) \
        .when(
            lambda: set_flag(
                DONT_CARE_FLAG,
                enabled=True,
                settings=some_settings(),
                post=provider.post,
                evaluate=provider.evaluate
            )
        ) \
        .then(
            _it_kept_asking_until_it_agreed(provider, times=3)
        )


@pytest.mark.unit
def test_a_flag_that_never_reaches_the_requested_state_is_not_reported_as_set() -> None:
    provider = a_flag_provider_reporting([DONT_CARE_FLAG])

    Scenario() \
        .when(
            attempting(
                lambda: set_flag(
                    DONT_CARE_FLAG,
                    enabled=False,
                    settings=some_settings(),
                    post=provider.post,
                    evaluate=provider.evaluate
                )
            )
        ) \
        .then(
            an_error_was_raised(FlagNotSet)
        )


@pytest.mark.unit
def test_an_unreachable_provider_is_not_reported_as_set() -> None:
    some_transport_error = httpx.ConnectError("connection refused")
    provider = a_flag_provider_reporting([])
    provider.post.side_effect = some_transport_error

    Scenario() \
        .when(
            attempting(
                lambda: set_flag(
                    DONT_CARE_FLAG,
                    enabled=False,
                    settings=some_settings(),
                    post=provider.post,
                    evaluate=provider.evaluate
                )
            )
        ) \
        .then(
            an_error_was_raised(FlagNotSet)
        )


@pytest.mark.unit
def test_switching_a_flag_off_records_that_it_had_been_on() -> None:
    # The descriptor names the state to restore, not the call that would
    # restore it: a tool renamed or resignatured later would leave the second
    # kind of record pointing at nothing.
    some_flag = "monthly-spend-feature"
    some_environment = "production"

    Scenario() \
        .given(
            provider := a_flag_provider_reporting([])
        ) \
        .when(
            lambda: set_flag(
                some_flag,
                enabled=False,
                settings=some_settings(environment=some_environment),
                post=provider.post,
                evaluate=provider.evaluate
            )
        ) \
        .then(
            all_of(
                _the_undo_names(some_flag, some_environment),
                _the_undo_restores_it_to(enabled=True)
            )
        )


@pytest.mark.unit
def test_switching_a_flag_on_records_that_it_had_been_off() -> None:
    # The undo of a mitigation that undid a switch-off. Recording `was_enabled`
    # as true here - as a revert-only tool would have to - would have the undo
    # leave the flag in the state that caused the incident.
    Scenario() \
        .given(
            provider := a_flag_provider_reporting([DONT_CARE_FLAG])
        ) \
        .when(
            lambda: set_flag(
                DONT_CARE_FLAG,
                enabled=True,
                settings=some_settings(),
                post=provider.post,
                evaluate=provider.evaluate
            )
        ) \
        .then(
            _the_undo_restores_it_to(enabled=False)
        )


@pytest.mark.unit
def test_the_undo_descriptor_records_when_the_provider_recorded_the_write() -> None:
    # The one fact the descriptor was missing, and the reason it needs it: an
    # undo asks the provider what changed *since* Argus wrote, and a time taken
    # from Argus's own clock would be compared against timestamps from the
    # provider's. The write's own response carries the provider's.
    some_moment_the_provider_recorded = datetime(2026, 9, 6, 17, 38, tzinfo=UTC)

    Scenario() \
        .given(
            provider := a_flag_provider_dating_its_write(some_moment_the_provider_recorded)
        ) \
        .when(
            lambda: set_flag(
                DONT_CARE_FLAG,
                enabled=False,
                settings=some_settings(),
                post=provider.post,
                evaluate=provider.evaluate
            )
        ) \
        .then(
            _the_undo_was_written_at(some_moment_the_provider_recorded)
        )


@pytest.mark.unit
def test_a_provider_that_dates_nothing_leaves_the_moment_absent() -> None:
    # Absent rather than filled in from this process's clock. A descriptor that
    # carried Argus's own time would be compared against the provider's log and
    # would be wrong by whatever the two clocks disagree by - and an undo can
    # say it could not establish the state, which is one of its three answers.
    Scenario() \
        .given(
            provider := a_flag_provider_reporting([])
        ) \
        .when(
            lambda: set_flag(
                DONT_CARE_FLAG,
                enabled=False,
                settings=some_settings(),
                post=provider.post,
                evaluate=provider.evaluate
            )
        ) \
        .then(
            _the_undo_was_written_at(None)
        )


class _FlagProvider:
    def __init__(self) -> None:
        self.post: Any = create_autospec(httpx.post)
        # Spec'd against the port, not `evaluated_flags`: that reads under
        # a credential, and confirming a write needs only the answer.
        self.evaluate: Any = create_autospec(EvaluateFlags, instance=True)


def a_flag_provider() -> _FlagProvider:
    provider = _FlagProvider()
    provider.post.return_value = httpx.Response(
        status_code=200,
        json={},
        request=httpx.Request("POST", "http://flags.invalid/")
    )
    return provider


def a_flag_provider_reporting(enabled_flags: list[str]) -> _FlagProvider:
    provider = a_flag_provider()
    provider.evaluate.return_value = enabled_flags
    return provider


def a_flag_provider_still_reporting_it_on_twice() -> _FlagProvider:
    """A provider that catches up on the third read rather than the first.

    Two stale answers and then the new one, which is what makes "returns only
    once it evaluates off" a claim about waiting rather than about luck.
    """
    provider = a_flag_provider()
    provider.evaluate.side_effect = [[DONT_CARE_FLAG], [DONT_CARE_FLAG], []]

    return provider


def a_flag_provider_still_reporting_it_off_twice() -> _FlagProvider:
    """The same lag in the other direction."""
    provider = a_flag_provider()
    provider.evaluate.side_effect = [[], [], [DONT_CARE_FLAG]]

    return provider


def a_flag_provider_dating_its_write(moment: datetime) -> _FlagProvider:
    dont_care_provider_url = "http://kuki.com/"
    provider = a_flag_provider_reporting([])
    provider.post.return_value = httpx.Response(
        status_code=200,
        json={},
        headers={"Date": format_datetime(moment, usegmt=True)},
        request=httpx.Request("POST", dont_care_provider_url)
    )

    return provider


def some_settings(project: str = "default",
                  environment: str = "production",
                  admin_token: str = "*:*.dont-care-admin-token") -> FlagWriteSettings:
    """The slice this tier writes under.

    Each test names only the field it is about. The evaluation credential is
    never one of them - what confirms the change is injected as `evaluate`, so
    nothing here ever sends it.
    """
    dont_care_frontend_token = "default:production.dont-care-frontend-token"

    return FlagWriteSettings(
        unleash_base_url="http://flags.invalid",
        unleash_frontend_token=dont_care_frontend_token,
        unleash_project=project,
        unleash_environment=environment,
        unleash_admin_token=admin_token
    )


def _the_write_addressed(provider: _FlagProvider, expected: str) -> Assertion[FlagUndo]:
    """Which URL the change was posted to, read off the call itself.

    Read off the call rather than inferred from the answer, because the double
    answers the same way whatever it is asked - it is not the provider and
    does not refuse a flag that does not exist or an environment that is not
    this one.
    """
    def assertion(dont_care_undo: FlagUndo) -> bool:
        addressed = provider.post.call_args.args[0]
        if not addressed.endswith(expected):
            raise AssertionError(f"Expected a write to [...{expected}], got [{addressed}].")

        return True

    return assertion


def _the_write_used(provider: _FlagProvider, expected: str) -> Assertion[FlagUndo]:
    def assertion(dont_care_undo: FlagUndo) -> bool:
        used = provider.post.call_args.kwargs["headers"]["Authorization"]
        if used != expected:
            raise AssertionError(f"Expected the write to use [{expected}], got [{used}].")

        return True

    return assertion


def _it_kept_asking_until_it_agreed(provider: _FlagProvider,
                                    times: int) -> Assertion[FlagUndo]:
    """That the call did not return on the provider's first, stale answer.

    Counted rather than merely "more than once", because the fixture lags by a
    known number of reads: fewer means it returned early, and more means it
    kept asking after the provider had already caught up.
    """
    def assertion(dont_care_undo: FlagUndo) -> bool:
        asked = provider.evaluate.call_count
        if asked != times:
            raise AssertionError(f"Expected the state to be read [{times}] times, got [{asked}].")

        return True

    return assertion


def _the_undo_names(flag: str, environment: str) -> Assertion[FlagUndo]:
    """Both halves of what an undo has to address, reported together.

    An undo naming the right flag in the wrong environment would restore a
    value in an environment nobody touched, and leave the incident's own
    environment as the mitigation left it.
    """
    def assertion(undo: FlagUndo) -> bool:
        named = (undo.flag, undo.environment)
        if named != (flag, environment):
            raise AssertionError(f"Expected the undo to name {(flag, environment)}, got {named}.")

        return True

    return assertion


def _the_undo_restores_it_to(enabled: bool) -> Assertion[FlagUndo]:
    """The state the flag is to be put back into - which is the state it was
    in before the write, not the state the write left it in."""
    def assertion(undo: FlagUndo) -> bool:
        if undo.was_enabled is not enabled:
            raise AssertionError(
                f"Expected the undo to restore it to [{enabled}], got [{undo.was_enabled}]."
            )

        return True

    return assertion


def _the_undo_was_written_at(expected: datetime | None) -> Assertion[FlagUndo]:
    def assertion(undo: FlagUndo) -> bool:
        if undo.written_at != expected:
            raise AssertionError(
                f"Expected the write to be dated [{expected}], got [{undo.written_at}]."
            )

        return True

    return assertion
