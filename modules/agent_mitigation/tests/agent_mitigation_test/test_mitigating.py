from __future__ import annotations

from typing import cast
from unittest.mock import MagicMock, create_autospec

import pytest
from agent_mitigation import Outcome, Verdict, mitigate, take_action
from agent_mitigation.tools import fetch_recent_flag_changes
from argus_core.models.cause import CauseType
from argus_core.models.flag_change import FlagChange
from argus_testkit import Assertion, Scenario, all_of

from agent_mitigation_test.framework.assertions import the_verdict_is
from agent_mitigation_test.framework.builders import (
    DONT_CARE_FLAG,
    a_disabling_of,
    a_hypothesis_blaming,
    an_enabling_of,
    an_outcome_reaching,
)


@pytest.mark.unit
def test_mitigating_a_flag_toggle_takes_the_action_proposed_for_it() -> None:
    some_flag = "kuki-flag"
    some_verdict = Verdict.CONFIRMED

    Scenario() \
        .given(
            the_flag_was_switched_off := _a_record_of(a_disabling_of(some_flag)),
            take := _an_action_taker_reaching(some_verdict)
        ) \
        .when(
            lambda: mitigate(
                a_hypothesis_blaming(CauseType.FEATURE_FLAG_TOGGLE),
                fetch_flag_changes=the_flag_was_switched_off,
                take=take
            )
        ) \
        .then(all_of(
            _the_action_taken_sets(take, some_flag, enabled=True),
            the_verdict_is(some_verdict)
        ))


@pytest.mark.unit
def test_mitigating_a_cause_with_no_action_escalates_without_touching_anything() -> None:
    Scenario() \
        .given(
            a_flag_did_change := _a_record_of(an_enabling_of(DONT_CARE_FLAG)),
            take := _an_untouched_action_taker()
        ) \
        .when(
            lambda: mitigate(
                a_hypothesis_blaming(CauseType.BAD_DEPLOYMENT),
                fetch_flag_changes=a_flag_did_change,
                take=take
            )
        ) \
        .then(all_of(
            the_verdict_is(Verdict.ESCALATED),
            _nothing_was_taken(take)
        ))


def _a_record_of(*changes: FlagChange) -> MagicMock:
    """The provider's record of what changed, as the agent reads it."""
    fetch_flag_changes: MagicMock = create_autospec(fetch_recent_flag_changes)
    fetch_flag_changes.return_value = list(changes)

    return fetch_flag_changes


def _an_action_taker_reaching(verdict: Verdict) -> MagicMock:
    """Takes whatever action it is handed and comes back with `verdict`."""
    take: MagicMock = create_autospec(take_action)
    take.return_value = an_outcome_reaching(verdict)

    return take


def _an_untouched_action_taker() -> MagicMock:
    """No return value configured - a call would be the failure."""
    return cast(MagicMock, create_autospec(take_action))


def _the_action_taken_sets(take: MagicMock, flag: str, enabled: bool) -> Assertion[Outcome]:
    def assertion(_outcome: Outcome) -> bool:
        action = take.call_args.args[0]
        if (action.flag, action.enabled) != (flag, enabled):
            raise AssertionError(
                f"Expected the action taken to set flag [{flag}] to [{enabled}], "
                f"got flag [{action.flag}] to [{action.enabled}]."
            )

        return True

    return assertion


def _nothing_was_taken(take: MagicMock) -> Assertion[Outcome]:
    def assertion(_outcome: Outcome) -> bool:
        if take.call_count != 0:
            raise AssertionError(
                f"Expected no action to be taken, got [{take.call_count}] calls."
            )

        return True

    return assertion
