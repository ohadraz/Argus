"""Where a planned change finds the platform's sync switch, compared with its plan.

One rule for the four actions that suspend reconciliation before they change
live state, read from three things: whether the plan found the platform
reconciling the application, whether it reconciles it now, and whose mark the
Application carries - the switch carrying the mark of whatever last wrote it.

Every way the three can stand is said here once, because each action's suite
says only the ways its own cases reach.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import create_autospec

import pytest
from argus_testkit import (
    Assertion,
    Scenario,
    all_of,
    an_error_was_raised,
    attempting,
    the_answer_was,
)
from deployment_platform import (
    DeploymentPlatformError,
    DeploymentPlatformWrites,
    MarkFound,
    PlatformRefused,
)
from write_mcp_server.sync_switch import (
    Switch,
    suspend_where_it_is_to_be,
    the_switch,
    this_claim_s_suspension_stands,
)

from write_mcp_server_test.framework.marks import (
    ANOTHER_CLAIM,
    THIS_CLAIM,
    a_mark,
    a_mark_found,
)

SOME_APPLICATION = "io-shop"
SOME_MARK = a_mark()
SOME_PLATFORM_WORDS = "the platform said no"
# The Application's mark as the port reads it back: this claim's, or another's.
THIS_CLAIM_S_MARK = a_mark_found(THIS_CLAIM)
ANOTHER_CLAIM_S_MARK = a_mark_found(ANOTHER_CLAIM)

# Every way the switch can stand: (whether the plan found it syncing, whether it
# syncs now, whose mark the Application carries, as the port reads it back), and
# what that makes it.
EVERY_WAY_THE_SWITCH_STANDS = [
    pytest.param(True, True, None, Switch.TO_SUSPEND, id="syncing-as-found-unmarked"),
    pytest.param(True, True, ANOTHER_CLAIM_S_MARK, Switch.TO_SUSPEND,
                 id="syncing-as-found-under-another-claim"),
    pytest.param(True, True, THIS_CLAIM_S_MARK, Switch.CHANGED_SINCE,
                 id="resumed-after-this-claim-suspended-it"),
    pytest.param(True, False, THIS_CLAIM_S_MARK, Switch.AS_NEEDED, id="suspended-by-this-claim"),
    pytest.param(True, False, None, Switch.CHANGED_SINCE, id="suspended-unmarked"),
    pytest.param(True, False, ANOTHER_CLAIM_S_MARK, Switch.CHANGED_SINCE,
                 id="suspended-under-another-claim"),
    pytest.param(False, False, None, Switch.AS_NEEDED, id="off-as-found"),
    pytest.param(False, False, THIS_CLAIM_S_MARK, Switch.AS_NEEDED,
                 id="off-as-found-under-this-claim"),
    pytest.param(False, False, ANOTHER_CLAIM_S_MARK, Switch.AS_NEEDED,
                 id="off-as-found-under-another-claim"),
    pytest.param(False, True, None, Switch.CHANGED_SINCE, id="turned-on-since"),
    pytest.param(False, True, THIS_CLAIM_S_MARK, Switch.CHANGED_SINCE,
                 id="turned-on-since-under-this-claim"),
    pytest.param(False, True, ANOTHER_CLAIM_S_MARK, Switch.CHANGED_SINCE,
                 id="turned-on-since-under-another-claim")
]

# Every way a suspension of this claim's does not stand - all but the one way it
# does, found syncing and off now under this claim's mark: (whether the plan
# found it syncing, whether it syncs now, whose mark the Application carries).
EVERY_WAY_NO_SUSPENSION_OF_THIS_CLAIM_S_STANDS = [
    pytest.param(True, True, None, id="syncing-as-found-unmarked"),
    pytest.param(True, True, THIS_CLAIM_S_MARK, id="resumed-since"),
    pytest.param(True, True, ANOTHER_CLAIM_S_MARK, id="syncing-as-found-under-another-claim"),
    pytest.param(True, False, None, id="suspended-unmarked"),
    pytest.param(True, False, ANOTHER_CLAIM_S_MARK, id="suspended-under-another-claim"),
    pytest.param(False, False, None, id="off-before-argus-came"),
    pytest.param(False, False, THIS_CLAIM_S_MARK, id="off-before-argus-came-under-this-claim"),
    pytest.param(False, False, ANOTHER_CLAIM_S_MARK,
                 id="off-before-argus-came-under-another-claim"),
    pytest.param(False, True, None, id="turned-on-since"),
    pytest.param(False, True, THIS_CLAIM_S_MARK, id="turned-on-since-under-this-claim"),
    pytest.param(False, True, ANOTHER_CLAIM_S_MARK, id="turned-on-since-under-another-claim")
]


@pytest.mark.unit
@pytest.mark.parametrize(("was_syncing_itself", "syncing_now", "marked_by", "expected"),
                         EVERY_WAY_THE_SWITCH_STANDS)
def test_the_switch_is_read_from_the_plan_the_platform_and_the_mark(
    was_syncing_itself: bool, syncing_now: bool, marked_by: MarkFound | None, expected: Switch
) -> None:
    # Reconciling as the plan found it is still to be suspended, whoever marked
    # it last; off under this claim's mark is where this claim left it; off as
    # the plan found it never needed suspending. Anything else is somebody's
    # switch since - turned off under no mark of this claim's, back on after this
    # claim turned it off, or on where the plan found it off.
    Scenario() \
        .given(SOME_MARK) \
        .when(lambda: the_switch(was_syncing_itself, syncing_now, marked_by, SOME_MARK)) \
        .then(the_answer_was(expected))


@pytest.mark.unit
def test_a_suspension_of_this_claim_s_stands_where_the_switch_is_off_under_its_mark() -> None:
    # The plan found it reconciling, it is off now, and this claim's mark says
    # this claim turned it off: a refusal has to carry the plan, the only record
    # of how to turn it back on.
    Scenario() \
        .given(SOME_MARK) \
        .when(lambda: this_claim_s_suspension_stands(True, False, THIS_CLAIM_S_MARK,
                                                        SOME_MARK)) \
        .then(the_answer_was(True))


@pytest.mark.unit
@pytest.mark.parametrize(("was_syncing_itself", "syncing_now", "marked_by"),
                         EVERY_WAY_NO_SUSPENSION_OF_THIS_CLAIM_S_STANDS)
def test_no_suspension_of_this_claim_s_stands_any_other_way(
    was_syncing_itself: bool, syncing_now: bool, marked_by: MarkFound | None
) -> None:
    # A switch somebody turned back on, one turned off by somebody else, and one
    # that was off before Argus came hold nothing of this claim's to put back.
    Scenario() \
        .given(SOME_MARK) \
        .when(lambda: this_claim_s_suspension_stands(was_syncing_itself, syncing_now,
                                                     marked_by, SOME_MARK)) \
        .then(the_answer_was(False))


@pytest.mark.unit
def test_a_switch_still_to_suspend_is_suspended_under_the_mark() -> None:
    platform = _a_platform()

    Scenario() \
        .given(platform) \
        .when(lambda: suspend_where_it_is_to_be(SOME_APPLICATION, Switch.TO_SUSPEND,
                                                platform, SOME_MARK, _refusing)) \
        .then(_it_was_suspended_under(platform, [(SOME_APPLICATION, SOME_MARK)]))


@pytest.mark.unit
@pytest.mark.parametrize("switch", [Switch.AS_NEEDED, Switch.CHANGED_SINCE])
def test_a_switch_not_to_suspend_is_left_alone(switch: Switch) -> None:
    # Already where the change needs it, or somebody's - neither is written.
    platform = _a_platform()

    Scenario() \
        .given(platform) \
        .when(lambda: suspend_where_it_is_to_be(SOME_APPLICATION, switch, platform,
                                                SOME_MARK, _refusing)) \
        .then(_it_was_suspended_under(platform, []))


@pytest.mark.unit
def test_a_suspension_the_platform_would_not_take_is_the_action_s_own_refusal() -> None:
    # The action's refusal rather than the platform's error, so each action says
    # in its own type, and with its own markers, what the failure left.
    platform = _a_platform()
    platform.suspend_sync.side_effect = PlatformRefused(SOME_PLATFORM_WORDS)

    Scenario() \
        .given(platform) \
        .when(attempting(lambda: suspend_where_it_is_to_be(
            SOME_APPLICATION, Switch.TO_SUSPEND, platform, SOME_MARK, _refusing
        ))) \
        .then(all_of(
            an_error_was_raised(_SomeRefusal),
            _it_was_refused_saying(SOME_APPLICATION, SOME_PLATFORM_WORDS)
        ))


class _SomeRefusal(Exception):
    """An action's refusal, as the action under test would build it."""


def _refusing(said: str, error: DeploymentPlatformError) -> _SomeRefusal:
    return _SomeRefusal(said)


def _a_platform() -> Any:
    return create_autospec(DeploymentPlatformWrites, instance=True)


def _it_was_suspended_under(platform: Any, expected: list[tuple[str, object]]) -> Assertion[object]:
    def assertion(dont_care: object) -> bool:
        asked = [call.args for call in platform.suspend_sync.call_args_list]

        if asked != expected:
            raise AssertionError(
                f"Expected the sync suspended as {expected}, and the platform was "
                f"asked {asked}."
            )

        return True

    return assertion


def _it_was_refused_saying(*words: str) -> Assertion[Exception | None]:
    def assertion(raised: Exception | None) -> bool:
        missing = [word for word in words if word not in str(raised)]

        if missing:
            raise AssertionError(
                f"Expected the refusal to say {list(words)}, and it said [{raised}], "
                f"missing {missing}."
            )

        return True

    return assertion
