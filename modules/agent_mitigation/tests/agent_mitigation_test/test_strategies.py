"""Which action answers which cause, and nothing about whether it is allowed.

A strategy says what would help. Whether Argus may then do it unasked is a
different question with a different answer, asked of the closed set in
`admitting` - so nothing here has an opinion about autonomy, and a strategy
cannot earn its action a way past the gate by being registered.
"""

from __future__ import annotations

from collections.abc import Sequence

import pytest
from agent_mitigation import (
    Action,
    MitigationStrategy,
    RestartServiceStrategy,
    Strategies,
    propose_action,
)
from argus_core.models import (
    REVERT_FEATURE_FLAG,
    ActionType,
    FailureMode,
    FlagChange,
    Hypothesis,
    RestartService,
    RevertFeatureFlag,
)
from argus_testkit import Assertion, Scenario

from agent_mitigation_test.framework.builders import (
    DONT_CARE_FLAG,
    a_hypothesis_blaming,
    an_action_setting,
    an_enabling_of,
)


@pytest.mark.unit
def test_the_strategy_registered_for_a_cause_is_the_one_asked() -> None:
    # The lookup is by cause, and it is the registry handed in that decides -
    # not a branch inside the agent. A second kind of cause becomes an entry
    # here rather than another `if` in the function that chooses.
    some_flag_a_strategy_of_its_own_would_name = "kuki-flag"

    Scenario() \
        .given(
            a_registry_answering_for_bad_deployments := {
                FailureMode.BAD_DEPLOYMENT: _a_strategy_proposing(
                    an_action_setting(
                        some_flag_a_strategy_of_its_own_would_name, enabled=False
                    )
                )
            }
        ) \
        .when(
            lambda: propose_action(
                a_hypothesis_blaming(FailureMode.BAD_DEPLOYMENT),
                flag_changes=[an_enabling_of(DONT_CARE_FLAG)],
                strategies=a_registry_answering_for_bad_deployments
            )
        ) \
        .then(
            _the_action_proposed_names(some_flag_a_strategy_of_its_own_would_name)
        )


@pytest.mark.unit
def test_a_cause_no_strategy_answers_for_proposes_nothing() -> None:
    # Not an error: a cause Argus has nothing to offer for is an ordinary
    # outcome, and it is the same outcome as a strategy that looked and found
    # nothing to reverse. The walk has one place to go from here either way.
    Scenario() \
        .given(
            a_registry_that_answers_for_nothing := _no_strategies()
        ) \
        .when(
            lambda: propose_action(
                a_hypothesis_blaming(FailureMode.FEATURE_FLAG_TOGGLE),
                flag_changes=[an_enabling_of(DONT_CARE_FLAG)],
                strategies=a_registry_that_answers_for_nothing
            )
        ) \
        .then(
            _nothing_was_proposed()
        )


@pytest.mark.unit
def test_a_leak_is_answered_by_restarting_the_service_the_cause_names() -> None:
    # The service comes from the hypothesis and from nowhere else. A configured
    # name would hardcode the demo's answer into the agent, and the second
    # deployment would restart the wrong thing while reporting success.
    some_leaking_service = "kuki-service"

    Scenario() \
        .given(
            a_leak := a_hypothesis_blaming(FailureMode.RESOURCE_LEAK,
                                           subject=some_leaking_service)
        ) \
        .when(lambda: RestartServiceStrategy().propose(a_leak, [])) \
        .then(_the_service_to_restart_is(some_leaking_service))


@pytest.mark.unit
def test_a_leak_that_names_no_service_is_answered_with_nothing() -> None:
    # Nothing to act on is a real outcome, not a reason to guess at the only
    # service Argus happens to know about. Restarting the wrong thing costs a
    # service its process and buys the incident nothing.
    Scenario() \
        .given(
            a_leak_naming_nothing := a_hypothesis_blaming(FailureMode.RESOURCE_LEAK)
        ) \
        .when(lambda: RestartServiceStrategy().propose(a_leak_naming_nothing, [])) \
        .then(_nothing_was_proposed())


@pytest.mark.unit
def test_a_flag_that_moved_during_a_leak_does_not_change_what_is_proposed() -> None:
    # No toggle causes a heap to grow. A flag that happened to move during the
    # climb is a coincidence, and an agent that reached for it would put back a
    # change nobody had any reason to suspect and leave the leak running.
    some_leaking_service = "kuki-service"

    Scenario() \
        .given(
            a_leak := a_hypothesis_blaming(FailureMode.RESOURCE_LEAK,
                                           subject=some_leaking_service),
            a_flag_that_moved_meanwhile := [an_enabling_of(DONT_CARE_FLAG)]
        ) \
        .when(
            lambda: RestartServiceStrategy().propose(a_leak, a_flag_that_moved_meanwhile)
        ) \
        .then(_the_service_to_restart_is(some_leaking_service))


@pytest.mark.unit
def test_the_registry_argus_ships_answers_a_leak_with_a_restart() -> None:
    # The wiring, asked through the front door. A strategy nothing is
    # registered against is a strategy that never runs, and the two tests above
    # would pass just as well with the entry missing.
    some_leaking_service = "kuki-service"

    Scenario() \
        .given(
            a_leak := a_hypothesis_blaming(FailureMode.RESOURCE_LEAK,
                                           subject=some_leaking_service)
        ) \
        .when(lambda: propose_action(a_leak, flag_changes=[])) \
        .then(_the_service_to_restart_is(some_leaking_service))


def _no_strategies() -> Strategies:
    """A registry that answers for no cause at all.

    Spelled out rather than written as a bare `{}` at each call, because an
    empty mapping needs its type named for it to be one of these.
    """
    return {}


class _StandInStrategy:
    """A strategy built to propose one particular thing.

    A class rather than `create_autospec`, because what is being stood in for
    is a `Protocol` carrying an attribute as well as a method, and the
    attribute is half of what the thing under test reads.

    It answers for the one action type there is. That is the only one a
    registry can be asked about today, and standing in for a *second* type so
    that a test could name one would be a branch in every match in the repo,
    added for this file's benefit.
    """

    action_type: ActionType = REVERT_FEATURE_FLAG

    def __init__(self, proposing: Action | None) -> None:
        self._proposing = proposing

    def propose(self,
                dont_care_hypothesis: Hypothesis,
                dont_care_flag_changes: Sequence[FlagChange]) -> Action | None:
        return self._proposing


def _a_strategy_proposing(action: Action) -> MitigationStrategy:
    return _StandInStrategy(proposing=action)


def _the_action_proposed_names(flag: str) -> Assertion[Action | None]:
    def assertion(action: Action | None) -> bool:
        if not isinstance(action, RevertFeatureFlag):
            raise AssertionError(
                f"Expected an action naming flag [{flag}], got [{action}]."
            )

        if action.flag != flag:
            raise AssertionError(
                f"Expected an action naming flag [{flag}], "
                f"got one naming [{action.flag}]."
            )

        return True

    return assertion


def _the_service_to_restart_is(service: str) -> Assertion[Action | None]:
    def assertion(action: Action | None) -> bool:
        if not isinstance(action, RestartService):
            raise AssertionError(
                f"Expected a restart of [{service}], got [{action}]."
            )

        if action.service != service:
            raise AssertionError(
                f"Expected a restart of [{service}], "
                f"got one of [{action.service}]."
            )

        return True

    return assertion


def _nothing_was_proposed() -> Assertion[Action | None]:
    def assertion(action: Action | None) -> bool:
        if action is not None:
            raise AssertionError(
                f"Expected no action to be proposed, got [{action}]."
            )

        return True

    return assertion
