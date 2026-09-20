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
    a_mitigation_answers,
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

# What a model actually wrote in the `subject` of a leak it had diagnosed. Kept
# verbatim because the shape is the point: it is a description of the heap, not
# a name anything can be addressed to, and the slash inside it is what turned a
# restart into a request for a resource nobody has.
SOME_SUBJECT_A_MODEL_WROTE = "kuki heap (memory_used_bytes / heap of 2048MiB limit)"

# The service a test has to name to ask its question, where the question is not
# about which service. Every proposal is addressed to one now, so there is no
# spelling of these calls that leaves it out.
DONT_CARE_SERVICE = "dont-care-service"


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
                service=DONT_CARE_SERVICE,
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
                service=DONT_CARE_SERVICE,
                strategies=a_registry_that_answers_for_nothing
            )
        ) \
        .then(
            _nothing_was_proposed()
        )


@pytest.mark.unit
def test_a_leak_is_answered_by_restarting_the_service_the_alert_names() -> None:
    # The service comes from the alert and from nowhere else. It is not
    # configured - the alert being answered says which service it is about - and
    # it is not read off the hypothesis, because what the model puts in a
    # subject is a description of the leak rather than the name of anything.
    some_alerting_service = "kuki-service"

    Scenario() \
        .given(
            a_leak := a_hypothesis_blaming(FailureMode.RESOURCE_LEAK,
                                           subject=SOME_SUBJECT_A_MODEL_WROTE)
        ) \
        .when(
            lambda: RestartServiceStrategy().propose(
                a_leak, [], service=some_alerting_service
            )
        ) \
        .then(_the_service_to_restart_is(some_alerting_service))


@pytest.mark.unit
def test_a_leak_whose_cause_describes_nothing_is_still_answered_with_a_restart() -> None:
    # A candidate that described no subject is not a candidate with nothing to
    # act on. The alert names a service whether or not the model found words
    # for what was accumulating inside it, and that service is the one that
    # gets its process back.
    some_alerting_service = "kuki-service"

    Scenario() \
        .given(
            a_leak_describing_nothing := a_hypothesis_blaming(FailureMode.RESOURCE_LEAK)
        ) \
        .when(
            lambda: RestartServiceStrategy().propose(
                a_leak_describing_nothing, [], service=some_alerting_service
            )
        ) \
        .then(_the_service_to_restart_is(some_alerting_service))


@pytest.mark.unit
def test_a_flag_that_moved_during_a_leak_does_not_change_what_is_proposed() -> None:
    # No toggle causes a heap to grow. A flag that happened to move during the
    # climb is a coincidence, and an agent that reached for it would put back a
    # change nobody had any reason to suspect and leave the leak running.
    some_alerting_service = "kuki-service"

    Scenario() \
        .given(
            a_leak := a_hypothesis_blaming(FailureMode.RESOURCE_LEAK,
                                           subject=SOME_SUBJECT_A_MODEL_WROTE),
            a_flag_that_moved_meanwhile := [an_enabling_of(DONT_CARE_FLAG)]
        ) \
        .when(
            lambda: RestartServiceStrategy().propose(
                a_leak, a_flag_that_moved_meanwhile, service=some_alerting_service
            )
        ) \
        .then(_the_service_to_restart_is(some_alerting_service))


@pytest.mark.unit
def test_the_registry_argus_ships_answers_a_leak_with_a_restart() -> None:
    # The wiring, asked through the front door. A strategy nothing is
    # registered against is a strategy that never runs, and the tests above
    # would pass just as well with the entry missing.
    some_alerting_service = "kuki-service"

    Scenario() \
        .given(
            a_leak := a_hypothesis_blaming(FailureMode.RESOURCE_LEAK,
                                           subject=SOME_SUBJECT_A_MODEL_WROTE)
        ) \
        .when(
            lambda: propose_action(
                a_leak, flag_changes=[], service=some_alerting_service
            )
        ) \
        .then(_the_service_to_restart_is(some_alerting_service))


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
                dont_care_flag_changes: Sequence[FlagChange],
                dont_care_service: str) -> Action | None:
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


@pytest.mark.unit
def test_nothing_answers_an_upstream_dependency_failure() -> None:
    # The absence is the decision, not an omission. Argus's mitigations reach
    # its own deployment - a flag it can put back, a process it can restart -
    # and another company's service is outside all of them. A strategy
    # registered here would be Argus claiming it could do something about an
    # outage it cannot reach.
    Scenario() \
        .given(
            an_upstream_failure := a_hypothesis_blaming(
                FailureMode.UPSTREAM_DEPENDENCY_FAILURE
            )
        ) \
        .when(
            lambda: propose_action(an_upstream_failure, [], DONT_CARE_SERVICE)
        ) \
        .then(
            _nothing_was_proposed()
        )


@pytest.mark.unit
def test_a_mode_nothing_answers_says_so_when_asked() -> None:
    # Asked of the policy that holds the mapping, because the gate has to tell
    # two silences apart - a mode with no mitigation at all, and a mode whose
    # mitigation could not identify what to act on - and a gate holding its own
    # copy of the set would be a second place for the answer to drift.
    Scenario() \
        .given(
            the_mode_nothing_answers := FailureMode.UPSTREAM_DEPENDENCY_FAILURE
        ) \
        .when(
            lambda: a_mitigation_answers(the_mode_nothing_answers)
        ) \
        .then(
            _the_answer_is(False)
        )


@pytest.mark.unit
def test_a_mode_with_a_strategy_is_answered() -> None:
    Scenario() \
        .given(
            the_mode_a_revert_answers := FailureMode.FEATURE_FLAG_TOGGLE
        ) \
        .when(
            lambda: a_mitigation_answers(the_mode_a_revert_answers)
        ) \
        .then(
            _the_answer_is(True)
        )


@pytest.mark.unit
def test_no_mode_at_all_is_answered_by_nothing() -> None:
    # A candidate that named no cause has nothing to look a strategy up by,
    # which is not the same as a cause whose answer is "nothing can be done" -
    # and the two must not end up reading the same way to whoever picks the
    # incident up.
    Scenario() \
        .given(
            no_mode_was_determined := None
        ) \
        .when(
            lambda: a_mitigation_answers(no_mode_was_determined)
        ) \
        .then(
            _the_answer_is(False)
        )


def _the_answer_is(expected: bool) -> Assertion[bool]:
    def assertion(answered: bool) -> bool:
        if answered is not expected:
            raise AssertionError(
                f"Expected [{expected}], got [{answered}]."
            )

        return True

    return assertion
