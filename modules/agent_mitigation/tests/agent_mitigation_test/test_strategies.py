from __future__ import annotations

from collections.abc import Sequence

import pytest
from agent_mitigation import (
    DEFAULT_STRATEGIES,
    Action,
    MitigationStrategy,
    Strategies,
    can_be_undone,
    propose_action,
)
from argus_core.models import (
    REVERT_FEATURE_FLAG,
    ActionType,
    CauseType,
    FlagChange,
    Hypothesis,
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
                CauseType.BAD_DEPLOYMENT: _a_strategy_proposing(
                    an_action_setting(
                        some_flag_a_strategy_of_its_own_would_name, enabled=False
                    )
                )
            }
        ) \
        .when(
            lambda: propose_action(
                a_hypothesis_blaming(CauseType.BAD_DEPLOYMENT),
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
                a_hypothesis_blaming(CauseType.FEATURE_FLAG_TOGGLE),
                flag_changes=[an_enabling_of(DONT_CARE_FLAG)],
                strategies=a_registry_that_answers_for_nothing
            )
        ) \
        .then(
            _nothing_was_proposed()
        )


@pytest.mark.unit
def test_an_action_its_strategy_can_put_back_is_reversible() -> None:
    Scenario() \
        .given(
            an_action_argus_really_takes := an_action_setting(
                DONT_CARE_FLAG, enabled=False
            )
        ) \
        .when(
            lambda: can_be_undone(an_action_argus_really_takes, DEFAULT_STRATEGIES)
        ) \
        .then(
            _it_is_reversible()
        )


@pytest.mark.unit
def test_an_action_whose_strategy_says_it_cannot_be_put_back_is_not_reversible() -> None:
    # What §13's gate is *for*. Reversibility is a fact about the kind of
    # change, so it is the strategy that would have to perform the undo that
    # answers - not a field on the instance, which by now cannot be absent.
    # An action type with no way back is refused before anything is called.
    Scenario() \
        .given(
            a_registry_that_cannot_undo_what_it_proposes := {
                CauseType.FEATURE_FLAG_TOGGLE: _a_strategy_that_cannot_put_anything_back()
            }
        ) \
        .when(
            lambda: can_be_undone(
                an_action_setting(DONT_CARE_FLAG, enabled=False),
                a_registry_that_cannot_undo_what_it_proposes
            )
        ) \
        .then(
            _it_is_not_reversible()
        )


@pytest.mark.unit
def test_an_action_no_strategy_answers_for_is_not_reversible() -> None:
    # A missing entry is not a reason to assume the best about an action. If
    # nothing here knows how to put this kind of change back, then as far as
    # Argus is concerned it cannot be put back, and the gate refuses it.
    Scenario() \
        .given(
            a_registry_that_answers_for_nothing := _no_strategies()
        ) \
        .when(
            lambda: can_be_undone(
                an_action_setting(DONT_CARE_FLAG, enabled=False),
                a_registry_that_answers_for_nothing
            )
        ) \
        .then(
            _it_is_not_reversible()
        )


def _no_strategies() -> Strategies:
    """A registry that answers for no cause at all.

    Spelled out rather than written as a bare `{}` at each call, because an
    empty mapping needs its type named for it to be one of these.
    """
    return {}


class _StandInStrategy:
    """A strategy built to answer two questions a particular way.

    A class rather than `create_autospec`, because what is being stood in for
    is a `Protocol` carrying an attribute as well as two methods, and the
    attribute is half of what the thing under test reads.

    It answers for the one action type there is. That is the only one a
    registry can be asked about today, and standing in for a *second* type so
    that a test could name one would be a branch in every match in the repo,
    added for this file's benefit.
    """

    action_type: ActionType = REVERT_FEATURE_FLAG

    def __init__(self, proposing: Action | None, undoable: bool) -> None:
        self._proposing = proposing
        self._undoable = undoable

    def propose(self,
                dont_care_hypothesis: Hypothesis,
                dont_care_flag_changes: Sequence[FlagChange]) -> Action | None:
        return self._proposing

    def can_be_undone(self) -> bool:
        return self._undoable


def _a_strategy_proposing(action: Action) -> MitigationStrategy:
    return _StandInStrategy(proposing=action, undoable=True)


def _a_strategy_that_cannot_put_anything_back() -> MitigationStrategy:
    return _StandInStrategy(proposing=None, undoable=False)


def _the_action_proposed_names(flag: str) -> Assertion[Action | None]:
    def assertion(action: Action | None) -> bool:
        if action is None:
            raise AssertionError(
                f"Expected an action naming flag [{flag}], got none."
            )

        if action.flag != flag:
            raise AssertionError(
                f"Expected an action naming flag [{flag}], "
                f"got one naming [{action.flag}]."
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


def _it_is_reversible() -> Assertion[bool]:
    def assertion(reversible: bool) -> bool:
        if not reversible:
            raise AssertionError(
                "Expected the action to be reversible, and it was refused."
            )

        return True

    return assertion


def _it_is_not_reversible() -> Assertion[bool]:
    def assertion(reversible: bool) -> bool:
        if reversible:
            raise AssertionError(
                "Expected the action to be refused as irreversible, "
                "and it was admitted."
            )

        return True

    return assertion
