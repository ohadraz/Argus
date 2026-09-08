from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, create_autospec

import pytest
from agent_mitigation.tools import (
    FlagChangesSince,
    argus_changed_flag_since,
    fetch_recent_flag_changes,
)
from argus_core.models.flag_change import FlagChange
from argus_core.timestamps import to_iso
from argus_testkit import Assertion, Scenario

"""Asking the flag provider whether a half-finished action actually landed.

A worker that died between taking an action and recording what came of it
leaves a claim with no outcome. Only the provider knows whether the change was
made, and this is the one place Argus asks it that question about itself.
"""

SOME_FLAG = "kukibuki"
SOME_ARGUS_USER = "Shuki Tuki"
THE_MOMENT_IT_WAS_CLAIMED = datetime(2026, 9, 4, 22, 15, tzinfo=UTC)


@pytest.mark.unit
def test_a_provider_that_cannot_be_reached_answers_nothing() -> None:
    # The case that must not read as "no change was made": an unreachable
    # provider would then send the walk off to act a second time on an action
    # that may already have been taken.
    Scenario() \
        .given(
            the_provider_is_down := _a_fetch_that_fails()
        ) \
        .when(
            lambda: argus_changed_flag_since(
                SOME_FLAG, THE_MOMENT_IT_WAS_CLAIMED, fetch=the_provider_is_down
            )
        ) \
        .then(
            _it_answers_nothing()
        )


@pytest.mark.unit
def test_the_provider_is_asked_from_the_moment_the_action_was_claimed() -> None:
    # A change to the same flag before the claim belongs to whoever caused the
    # incident. Only one after it can be the attempt that stopped halfway.
    Scenario() \
        .given(
            fetch := _a_provider_reporting()
        ) \
        .when(
            lambda: argus_changed_flag_since(
                SOME_FLAG, THE_MOMENT_IT_WAS_CLAIMED, fetch=fetch
            )
        ) \
        .then(
            _it_asked_from(fetch, to_iso(THE_MOMENT_IT_WAS_CLAIMED))
        )


@pytest.mark.unit
def test_a_change_the_provider_attributes_to_argus_is_argus_own() -> None:
    # The answer a resumed walk acts on: the action it claimed did land, so
    # taking it again would be a second production write for one decision.
    Scenario() \
        .given(
            argus_changed_it := _a_provider_reporting(_a_change_by(SOME_ARGUS_USER))
        ) \
        .when(
            lambda: argus_changed_flag_since(SOME_FLAG, 
                                             THE_MOMENT_IT_WAS_CLAIMED, 
                                             fetch=argus_changed_it, 
                                             argus_user=lambda: SOME_ARGUS_USER
            )
        ) \
        .then(
            _it_answers(True)
        )


@pytest.mark.unit
def test_a_change_the_provider_attributes_to_somebody_else_is_not_argus_own() -> None:
    # Somebody else moved the same flag in the same window. The claimed action
    # still did not land, and the walk has to be free to take it.
    Scenario() \
        .given(
            somebody_else_changed_it := _a_provider_reporting(
                _a_change_by("some-human"))
        ) \
        .when(
            lambda: argus_changed_flag_since(SOME_FLAG,
                                             THE_MOMENT_IT_WAS_CLAIMED,
                                             fetch=somebody_else_changed_it,
                                             argus_user=lambda: SOME_ARGUS_USER
            )
        ) \
        .then(
            _it_answers(False)
        )


@pytest.mark.unit
def test_the_window_asked_for_reaches_back_one_lookback_from_now() -> None:
    # The window is decided here rather than by the caller, so that proposing
    # an action stays free of both configuration and I/O.
    some_lookback = timedelta(minutes=30)
    some_moment = datetime(2026, 9, 4, 22, 15, tzinfo=UTC)

    Scenario() \
        .given(
            fetch := _a_provider_reporting()
        ) \
        .when(
            lambda: fetch_recent_flag_changes(
                fetch=fetch,
                now=lambda: some_moment,
                lookback=lambda: some_lookback,
                argus_user=lambda: SOME_ARGUS_USER
            )
        ) \
        .then(
            _it_asked_from(fetch, to_iso(some_moment - some_lookback))
        )


@pytest.mark.unit
def test_changes_argus_made_itself_are_left_out() -> None:
    # Once Argus can act more than once on an incident its own revert lands in
    # this window, and a window carrying it turns the unambiguous case - one
    # flag changed, so that is the one to put back - into two, and refuses.
    somebody_elses = _a_change_by("some-human")

    Scenario() \
        .given(
            fetch := _a_provider_reporting(
                _a_change_by(SOME_ARGUS_USER), somebody_elses
            )
        ) \
        .when(
            lambda: fetch_recent_flag_changes(
                fetch=fetch,
                now=lambda: THE_MOMENT_IT_WAS_CLAIMED,
                lookback=lambda: timedelta(minutes=30),
                argus_user=lambda: SOME_ARGUS_USER
            )
        ) \
        .then(
            _it_returned_only(somebody_elses)
        )


def _a_fetch_that_fails() -> MagicMock:
    """The provider cannot be reached at all."""
    fetch: MagicMock = create_autospec(FlagChangesSince)
    fetch.side_effect = ConnectionError("the write tier is down")

    return fetch


def _it_answers_nothing() -> Assertion[bool | None]:
    def assertion(answer: bool | None) -> bool:
        if answer is not None:
            raise AssertionError(
                f"Expected no answer about the flag, got [{answer}]."
            )

        return True

    return assertion


def _it_asked_from(fetch: MagicMock, moment: str) -> Assertion[bool | None]:
    def assertion(_answer: bool | None) -> bool:
        if fetch.call_args.kwargs != {"since": moment}:
            raise AssertionError(
                f"Expected the provider to be asked from [{moment}], "
                f"got {fetch.call_args.kwargs}."
            )

        return True

    return assertion


def _a_change_by(actor: str) -> FlagChange:
    return FlagChange(
        flag=SOME_FLAG, enabled=True,
        occurred_at=to_iso(THE_MOMENT_IT_WAS_CLAIMED), actor=actor
    )


def _a_provider_reporting(*changes: FlagChange) -> MagicMock:
    fetch: MagicMock = create_autospec(FlagChangesSince)
    fetch.return_value = list(changes)

    return fetch


def _it_answers(expected: bool) -> Assertion[bool | None]:
    def assertion(answer: bool | None) -> bool:
        if answer is not expected:
            raise AssertionError(
                f"Expected the answer [{expected}], got [{answer}]."
            )

        return True

    return assertion


def _it_returned_only(*expected: FlagChange) -> Assertion[list[FlagChange]]:
    def assertion(changes: list[FlagChange]) -> bool:
        if tuple(changes) != expected:
            raise AssertionError(
                f"Expected the window to carry {expected}, got {tuple(changes)}."
            )

        return True

    return assertion
