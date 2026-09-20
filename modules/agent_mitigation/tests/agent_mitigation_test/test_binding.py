"""Binding the agent's capabilities to the tier they are performed over.

Two properties, and neither is visible from inside the thing bound.

**Whole.** A collaborator is bound with `functools.partial`, and a partial that
leaves a required keyword unsupplied is a well-typed object that raises
`TypeError` the first time it is called. For an undo that is on a path nobody
runs by accident - a refuted mitigation, a withdrawn incident - so it is asked
here by inspection rather than by hoping a suite reaches it.

**Over the write tier.** No read server has these tools at all, so an undo bound
to the read client would fail at the moment somebody was putting production back.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any
from unittest.mock import Mock, create_autospec

import pytest
from agent_mitigation import an_undo_over
from agent_mitigation.tools import MitigationSettings
from argus_core.mcp_transport import McpClient
from argus_core.models import ConfigRollbackUndo
from argus_testkit import Assertion, Scenario, all_of

RESTORE_CONFIGURATION_TOOL = "restore_configuration"

SOME_APPLICATION = "io-shop"
SOME_ARGUS_USER = "Shuki Tuki"

A_ROLLBACK_TO_PUT_BACK = ConfigRollbackUndo(
    application=SOME_APPLICATION,
    was_on_history_id=2,
    was_on_revision="0d8e826225f0de73958a8a8dd3d867b2ae249e72",
    was_syncing_itself=True
)

# What either caller passes when it puts a change back: the record of the change
# and nothing else. Which changes to undo, in what order, and where the answers
# are written down belong to whoever holds the records - so anything still
# required beyond this is a collaborator the binding was never given.
WHAT_AN_UNDO_IS_GIVEN = frozenset({"undo_descriptor"})


@pytest.mark.unit
def test_an_undo_needs_nothing_but_the_change_it_is_putting_back() -> None:
    # The failure this exists for is quiet in every way that matters. A new kind
    # of action arrives, the agent grows a collaborator for putting it back, and
    # the binding is not given one. Every gate stays green - a partial missing a
    # required keyword is well-typed until it is called - and the walk dies at
    # the moment it tries to undo something, which is the moment production is
    # already changed.
    Scenario() \
        .given(dont_care_client := _a_session_that_answers_nothing()) \
        .when(lambda: an_undo_over(dont_care_client, _some_mitigation_settings())) \
        .then(_it_still_requires_only(WHAT_AN_UNDO_IS_GIVEN))


@pytest.mark.integration
def test_an_undo_puts_a_rolled_back_deployment_back_over_the_write_tier() -> None:
    # Bound once, here, because it is wanted in two places: the walk binds it so
    # a refuted mitigation can put itself back, and the worker binds it so a
    # withdrawn incident can. Two copies of one binding is how the second came to
    # be missing a collaborator the first had.
    #
    # The tier split is enforced by absence: no read server has this tool at all
    # (spec §12.1, §13). An undo bound to the read client would fail on the one
    # call that puts production back - after the walk had already changed it.
    Scenario() \
        .given(
            read := _a_session_that_answers_nothing(),
            write := _a_session_that_answers_nothing()
        ) \
        .when(
            _asking(read, write, lambda: an_undo_over(
                write, _some_mitigation_settings()
            )(A_ROLLBACK_TO_PUT_BACK))
        ) \
        .then(all_of(
            _the_read_tier_was_asked_for(),
            _the_write_tier_was_asked_for(RESTORE_CONFIGURATION_TOOL)
        ))


def _a_session_that_answers_nothing() -> Mock:
    """A client that records the question and answers with a mock.

    Specced against `McpClient` rather than a `Protocol` of this suite's own,
    because what the binding is handed is the real thing and the question being
    asked is which of two it was handed.
    """
    client: Mock = create_autospec(McpClient, instance=True)

    return client


def _asking(read: Mock,
            write: Mock,
            ask: Callable[[], object]) -> Callable[[], tuple[list[str], list[str]]]:
    """Runs one binding and reports what each tier was asked for."""
    def step() -> tuple[list[str], list[str]]:
        ask()

        return (
            [asked.args[0] for asked in read.call.call_args_list],
            [asked.args[0] for asked in write.call.call_args_list]
        )

    return step


def _the_read_tier_was_asked_for(
    *tools: str
) -> Assertion[tuple[list[str], list[str]]]:
    def assertion(asked: tuple[list[str], list[str]]) -> bool:
        if asked[0] != list(tools):
            raise AssertionError(
                f"Expected the read tier to be asked for {list(tools)}, "
                f"got {asked[0]}."
            )

        return True

    return assertion


def _the_write_tier_was_asked_for(
    *tools: str
) -> Assertion[tuple[list[str], list[str]]]:
    def assertion(asked: tuple[list[str], list[str]]) -> bool:
        if asked[1] != list(tools):
            raise AssertionError(
                f"Expected the write tier to be asked for {list(tools)}, "
                f"got {asked[1]}."
            )

        return True

    return assertion


def _it_still_requires_only(
    supplied: frozenset[str]
) -> Assertion[Callable[..., Any]]:
    """Every parameter the binding has left, against what its callers pass.

    `inspect.signature` resolves a partial's bound keywords into defaults, so
    what comes back is exactly what a caller would still have to supply - which
    is the question being asked, and one no type checker answers.
    """
    def assertion(undo: Callable[..., Any]) -> bool:
        required = {
            name for name, parameter in inspect.signature(undo).parameters.items()
            if parameter.default is inspect.Parameter.empty
            and parameter.kind not in (
                inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD
            )
        }
        unbound = required - supplied

        if unbound:
            raise AssertionError(
                f"The binding left {sorted(unbound)} unsupplied, so putting a "
                f"change back raises TypeError the first time anybody tries - "
                f"and every gate passes until they do."
            )

        return True

    return assertion


def _some_mitigation_settings() -> MitigationSettings:
    """How Mitigation behaves, as this file sets it.

    Nothing here reads any of it: the binding passes the lookback and the actor
    into the provider check it composes, and no test below reaches that check.
    They are required, and required is the whole of why they are present.
    """
    a_lookback_nothing_here_reaches = 30
    a_wait_nothing_here_reaches = 180.0

    return MitigationSettings(
        flag_change_lookback_minutes=a_lookback_nothing_here_reaches,
        unleash_actor=SOME_ARGUS_USER,
        mitigation_verification_timeout_seconds=a_wait_nothing_here_reaches,
        mitigation_attempts_per_subject=1
    )
