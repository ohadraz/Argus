"""Asking the flag provider whether a half-finished action actually landed.

A worker that died between taking an action and recording what came of it
leaves a claim with no outcome. Only the provider knows whether the change was
made, and this is the one place Argus asks it that question about itself.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import NamedTuple
from unittest.mock import MagicMock, Mock, create_autospec

import pytest
from agent_mitigation.tools import (
    FlagChangesSince,
    MitigationSettings,
    argus_changed_flag_since,
    deployment_restorer_over,
    deployment_roller_over,
    fetch_recent_flag_changes,
    flag_changes_over,
    flag_setter_over,
    recent_metrics_over,
)
from argus_core import to_iso
from argus_core.mcp_transport import McpClient
from argus_core.models import DeploymentRollbackUndo, FlagChange
from argus_testkit import Assertion, Scenario, all_of

SOME_FLAG = "kukibuki"
SOME_ARGUS_USER = "Shuki Tuki"
THE_MOMENT_IT_WAS_CLAIMED = datetime(2026, 9, 4, 22, 15, tzinfo=UTC)
SOME_MOMENT = to_iso(THE_MOMENT_IT_WAS_CLAIMED)

METRICS_TOOL = "get_metrics_summary"
FLAG_CHANGES_TOOL = "get_recent_flag_changes"
SET_FLAG_TOOL = "set_feature_flag"
ROLL_BACK_TOOL = "roll_back_deployment"
RESTORE_CONFIGURATION_TOOL = "restore_deployment"

SOME_APPLICATION = "io-shop"
A_ROLLBACK_TO_PUT_BACK = DeploymentRollbackUndo(
    application=SOME_APPLICATION,
    was_on_history_id=2,
    was_on_revision="0d8e826225f0de73958a8a8dd3d867b2ae249e72",
    was_syncing_itself=True
)


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
                SOME_FLAG,
                THE_MOMENT_IT_WAS_CLAIMED,
                _some_mitigation_settings(),
                fetch=the_provider_is_down
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
                SOME_FLAG,
                THE_MOMENT_IT_WAS_CLAIMED,
                _some_mitigation_settings(),
                fetch=fetch
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
                                             _some_mitigation_settings(),
                                             fetch=argus_changed_it
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
                                             _some_mitigation_settings(),
                                             fetch=somebody_else_changed_it
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
                _some_mitigation_settings(lookback=some_lookback),
                fetch=fetch,
                now=lambda: some_moment
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
                _some_mitigation_settings(),
                fetch=fetch,
                now=lambda: THE_MOMENT_IT_WAS_CLAIMED
            )
        ) \
        .then(
            _it_returned_only(somebody_elses)
        )


@pytest.mark.integration
def test_the_flag_history_is_asked_over_the_write_tier() -> None:
    # The provider serves its audit log to admin credentials alone, and
    # `argus-read-mcp` holds none by design. A history bound to the read tier
    # would not error - it would find nothing, which reads exactly like an
    # incident in which no flag moved.
    Scenario() \
        .given(
            read := _a_session_that_remembers_what_it_was_asked(),
            write := _a_session_that_remembers_what_it_was_asked()
        ) \
        .when(
            _asking(read, write,
                    lambda: flag_changes_over(write)(since=SOME_MOMENT))
        ) \
        .then(all_of(
            _the_read_tier_was_asked_for(),
            _the_write_tier_was_asked_for(FLAG_CHANGES_TOOL)
        ))


@pytest.mark.integration
def test_the_one_write_argus_makes_goes_over_the_write_tier() -> None:
    # The tier split is enforced by absence: no read server has this tool at
    # all (spec §12.1, §13). A setter bound to the read client would fail on the
    # one call Argus makes that changes production - after the walk had already
    # decided to make it.
    Scenario() \
        .given(
            read := _a_session_that_remembers_what_it_was_asked(),
            write := _a_session_that_remembers_what_it_was_asked()
        ) \
        .when(
            _asking(read, write,
                    lambda: flag_setter_over(write)(SOME_FLAG, True))
        ) \
        .then(all_of(
            _the_read_tier_was_asked_for(),
            _the_write_tier_was_asked_for(SET_FLAG_TOOL)
        ))


@pytest.mark.integration
def test_the_service_is_re_read_over_the_read_tier() -> None:
    # The verdict's own evidence, and the one thing Mitigation asks that has
    # nothing to do with the provider. It belongs to the read tier for the same
    # reason every other retrieval does: reading needs no credential to mutate.
    Scenario() \
        .given(
            read := _a_session_that_remembers_what_it_was_asked(),
            write := _a_session_that_remembers_what_it_was_asked()
        ) \
        .when(
            _asking(read, write, lambda: recent_metrics_over(read)())
        ) \
        .then(all_of(
            _the_read_tier_was_asked_for(METRICS_TOOL),
            _the_write_tier_was_asked_for()
        ))


@pytest.mark.integration
def test_returning_a_deployment_to_an_earlier_revision_goes_over_the_write_tier() -> None:
    # The third write, and one no read server has either. A roller bound to the
    # read client would fail at the moment the walk had already decided to roll
    # production back - and the incident it was mitigating would still be
    # happening.
    Scenario() \
        .given(
            read := _a_session_that_remembers_what_it_was_asked(),
            write := _a_session_that_answers_with(A_ROLLBACK_TO_PUT_BACK)
        ) \
        .when(
            _asking(read, write,
                    lambda: deployment_roller_over(write)(SOME_APPLICATION))
        ) \
        .then(all_of(
            _the_read_tier_was_asked_for(),
            _the_write_tier_was_asked_for(ROLL_BACK_TOOL)
        ))


@pytest.mark.integration
def test_putting_a_rolled_back_deployment_back_goes_over_the_write_tier() -> None:
    # Undoing a rollback is its own tool rather than the same call reversed,
    # which is what separates it from a flag: a flag's undo is `set_state` with
    # the state the descriptor recorded, and a rollback's undo has two pieces of
    # prior state and a platform that refuses one order of them.
    Scenario() \
        .given(
            read := _a_session_that_remembers_what_it_was_asked(),
            write := _a_session_that_remembers_what_it_was_asked()
        ) \
        .when(
            _asking(read, write,
                    lambda: deployment_restorer_over(write)(A_ROLLBACK_TO_PUT_BACK))
        ) \
        .then(all_of(
            _the_read_tier_was_asked_for(),
            _the_write_tier_was_asked_for(RESTORE_CONFIGURATION_TOOL)
        ))


class _Asked(NamedTuple):
    """Which tool each tier was asked for, in the order it was asked."""

    read: list[str]
    write: list[str]


def _a_session_that_remembers_what_it_was_asked() -> Mock:
    """A client that answers nothing and records the question.

    Specced against `McpClient` rather than a `Protocol` of this suite's own,
    because what these seams are handed is the real thing and the question being
    asked is which of two it was handed.
    """
    client: Mock = create_autospec(McpClient, instance=True)

    return client


def _a_session_that_answers_with(answer: object) -> Mock:
    """A session that records the question and gives a usable answer.

    The rollback's typed client checks what came back is a record of a
    deployment being rolled back, and refuses anything else - so a session
    answering with a bare mock is refused before the tier it was asked over can
    be read off it. Which is the client doing its job, and not what this test
    is about.
    """
    client: Mock = create_autospec(McpClient, instance=True)
    client.call.return_value = answer

    return client


def _asking(read: Mock, write: Mock, ask: Callable[[], object]) -> Callable[[], _Asked]:
    """Runs one seam and reports what each tier was asked for."""
    def step() -> _Asked:
        ask()

        return _Asked(
            read=[asked.args[0] for asked in read.call.call_args_list],
            write=[asked.args[0] for asked in write.call.call_args_list]
        )

    return step


def _the_read_tier_was_asked_for(*tools: str) -> Assertion[_Asked]:
    def assertion(asked: _Asked) -> bool:
        if asked.read != list(tools):
            raise AssertionError(
                f"Expected the read tier to be asked for {list(tools)}, "
                f"got {asked.read}."
            )

        return True

    return assertion


def _the_write_tier_was_asked_for(*tools: str) -> Assertion[_Asked]:
    def assertion(asked: _Asked) -> bool:
        if asked.write != list(tools):
            raise AssertionError(
                f"Expected the write tier to be asked for {list(tools)}, "
                f"got {asked.write}."
            )

        return True

    return assertion


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


def _some_mitigation_settings(
    actor: str = SOME_ARGUS_USER,
    lookback: timedelta = timedelta(minutes=30)
) -> MitigationSettings:
    """How Mitigation behaves, as this suite sets it.

    The actor and the lookback are what these tests are about - who a change is
    attributed to, and how far back the window reaches. The wait is never
    reached here, since nothing in this file takes an action, and neither is
    the cap - nothing here proposes a second attempt on anything.
    """
    a_wait_nothing_here_reaches = 180.0

    return MitigationSettings(
        flag_change_lookback_minutes=int(lookback.total_seconds() // 60),
        unleash_actor=actor,
        mitigation_verification_timeout_seconds=a_wait_nothing_here_reaches,
        mitigation_attempts_per_subject=1
    )
