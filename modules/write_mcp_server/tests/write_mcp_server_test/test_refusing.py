"""What a write tool's refusal says about the estate it leaves.

One rule for every action through the deployment platform, and it is where
knowledge stops: at a change request that went out and got no answer saying it
was not applied. Before any change is asked for, the estate is known as it was
found, whatever the platform said. At a change the platform answered it did not
handle, what is left is what the earlier calls answered for, and that is known to
be all of it. At one whose answer was lost, the earlier calls' changes are still
carried, and nothing is said to be all of it - and nothing is marked, because a
platform marked unreachable narrows the walk onto an estate that may have moved.
"""

from __future__ import annotations

import pytest
from argus_core.models import DeploymentRollbackUndo
from argus_testkit import Assertion, Scenario, all_of
from deployment_platform import DeploymentPlatformError, PlatformRefused, PlatformUnreachable
from write_mcp_server.refusing import a_platform_refusal

from write_mcp_server_test.framework.refusals import (
    it_is_marked_unreachable,
    it_left_behind,
    what_it_left_is_known,
)

SOME_REFUSAL = "[io-shop] could not be rolled back to history entry [1]"

A_SUSPENSION = DeploymentRollbackUndo(
    application="io-shop",
    was_on_history_id=2,
    was_on_revision="0d8e826225f0de73958a8a8dd3d867b2ae249e72",
    was_syncing_itself=True
)


@pytest.mark.unit
@pytest.mark.parametrize(
    "error",
    [
        PlatformUnreachable("timed out", known_not_applied=False),
        PlatformUnreachable("connection refused", known_not_applied=True)
    ],
    ids=["timed out", "refused the connection"]
)
def test_a_platform_gone_before_any_change_was_asked_for_is_unreachable_and_left_nothing(
    error: DeploymentPlatformError
) -> None:
    # Nothing has been asked to change, so however the read failed, nothing did.
    Scenario() \
        .when(lambda: a_platform_refusal(SOME_REFUSAL, error, asked_to_change=False)) \
        .then(all_of(
            it_is_marked_unreachable(True),
            what_it_left_is_known(True),
            it_left_behind(None)
        ))


@pytest.mark.unit
@pytest.mark.parametrize(
    "error",
    [
        PlatformRefused("400", known_not_applied=True),
        PlatformRefused("does not say what was asked", known_not_applied=False)
    ],
    ids=["rejected", "unreadable"]
)
def test_a_platform_that_said_no_before_any_change_was_asked_for_left_nothing(
    error: DeploymentPlatformError
) -> None:
    # "Could not read [io-shop]" is no reason to write up nobody knowing
    # whether anything was changed: nothing had been asked to change.
    Scenario() \
        .when(lambda: a_platform_refusal(SOME_REFUSAL, error, asked_to_change=False)) \
        .then(all_of(
            it_is_marked_unreachable(False),
            what_it_left_is_known(True),
            it_left_behind(None)
        ))


@pytest.mark.unit
def test_a_platform_gone_at_a_change_it_did_not_handle_is_unreachable_with_what_it_left() -> None:
    # A 503 at the action's own write, after the suspension landed: every
    # action through the platform is unavailable, and the suspension is the
    # whole of what this one left.
    error = PlatformUnreachable("503", known_not_applied=True)

    Scenario() \
        .when(lambda: a_platform_refusal(SOME_REFUSAL, error, asked_to_change=True,
                                         left_behind=A_SUSPENSION)) \
        .then(all_of(
            it_is_marked_unreachable(True),
            what_it_left_is_known(True),
            it_left_behind(A_SUSPENSION)
        ))


@pytest.mark.unit
def test_a_change_the_platform_rejected_says_it_left_only_what_came_before() -> None:
    # A rollback refused with a 4xx after the sync was suspended has left the
    # application un-reconciled, and the refusal is the only record of it - so
    # it carries the suspension, and nothing else is left to account for.
    error = PlatformRefused("400", known_not_applied=True)

    Scenario() \
        .when(lambda: a_platform_refusal(SOME_REFUSAL, error, asked_to_change=True,
                                         left_behind=A_SUSPENSION)) \
        .then(all_of(
            it_is_marked_unreachable(False),
            what_it_left_is_known(True),
            it_left_behind(A_SUSPENSION)
        ))


@pytest.mark.unit
@pytest.mark.parametrize(
    "error",
    [
        PlatformUnreachable("timed out", known_not_applied=False),
        PlatformUnreachable("500", known_not_applied=False)
    ],
    ids=["timed out", "faulted"]
)
def test_a_change_whose_answer_was_lost_is_not_marked_and_carries_what_came_before(
    error: DeploymentPlatformError
) -> None:
    # The rollback may be landing this second. Marked unreachable, the walk
    # would narrow onto another action and judge it against a service that may
    # be recovering from this one; said known, the record would say nothing
    # changed beyond the suspension.
    Scenario() \
        .when(lambda: a_platform_refusal(SOME_REFUSAL, error, asked_to_change=True,
                                         left_behind=A_SUSPENSION)) \
        .then(all_of(
            it_is_marked_unreachable(False),
            what_it_left_is_known(False),
            it_left_behind(A_SUSPENSION)
        ))


@pytest.mark.unit
def test_a_first_change_whose_answer_was_lost_carries_nothing_and_is_not_known() -> None:
    # Nothing came before it to carry, and nothing about it can be said.
    error = PlatformUnreachable("timed out", known_not_applied=False)

    Scenario() \
        .when(lambda: a_platform_refusal(SOME_REFUSAL, error, asked_to_change=True)) \
        .then(all_of(
            it_is_marked_unreachable(False),
            what_it_left_is_known(False),
            it_left_behind(None)
        ))


@pytest.mark.unit
def test_a_refusal_is_said_in_its_own_words() -> None:
    error = PlatformRefused("400", known_not_applied=True)

    Scenario() \
        .when(lambda: a_platform_refusal(SOME_REFUSAL, error, asked_to_change=True,
                                         left_behind=A_SUSPENSION)) \
        .then(_it_says(SOME_REFUSAL))


def _it_says(expected: str) -> Assertion[str]:
    def assertion(said: str) -> bool:
        if expected not in said:
            raise AssertionError(
                f"Expected the refusal to say [{expected}], and it said [{said}]."
            )

        return True

    return assertion
