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
    RestartDependencyStrategy,
    RestartServiceStrategy,
    ScaleOutStrategy,
    Strategies,
    a_mitigation_answers,
    propose_action,
)
from agent_mitigation.strategies import DEFAULT_STRATEGIES
from argus_core.models import (
    REVERT_FEATURE_FLAG,
    ROLL_BACK_DEPLOYMENT,
    ActionType,
    ChangeEvent,
    DiscardCacheEntries,
    FailureMode,
    FlagChange,
    Hypothesis,
    RestartService,
    RevertFeatureFlag,
    RollBackDeployment,
    ScaleOut,
)
from argus_testkit import Assertion, Scenario

from agent_mitigation_test.framework.assertions import nothing_was_proposed
from agent_mitigation_test.framework.builders import (
    DONT_CARE_FLAG,
    a_deployment,
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

NO_FLAGS_CHANGED: Sequence[FlagChange] = []

SOME_APPLICATION_THE_ALERT_NAMES = "io-shop"


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
            nothing_was_proposed()
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
                a_leak, NO_FLAGS_CHANGED, service=some_alerting_service
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
                a_leak_describing_nothing, NO_FLAGS_CHANGED, service=some_alerting_service
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
                a_leak, flag_changes=NO_FLAGS_CHANGED, service=some_alerting_service
            )
        ) \
        .then(_the_service_to_restart_is(some_alerting_service))


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
            lambda: propose_action(an_upstream_failure, NO_FLAGS_CHANGED, DONT_CARE_SERVICE)
        ) \
        .then(
            nothing_was_proposed()
        )


@pytest.mark.unit
def test_nothing_answers_monitoring_configuration_drift_though_a_revision_is_there() -> None:
    # The absence is the decision, as it is for the upstream failure above, and
    # here it has something to resist. A revision is recorded at the onset and a
    # rollback would bring the sight back - which is exactly why it must not be
    # proposed: the revision is the work somebody meant, and what is behind is the
    # monitoring's configuration, which no mitigation reaches.
    Scenario() \
        .given(
            drift := a_hypothesis_blaming(FailureMode.MONITORING_CONFIGURATION_DRIFT)
        ) \
        .when(lambda: propose_action(
            drift, NO_FLAGS_CHANGED, DONT_CARE_SERVICE, deployments=[a_deployment()]
        )) \
        .then(
            nothing_was_proposed()
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


@pytest.mark.unit
def test_a_config_induced_failure_is_answered_by_rolling_the_configuration_back() -> None:
    Scenario() \
        .given(a_hypothesis_blaming(FailureMode.CONFIG_INDUCED_FAILURE)) \
        .when(lambda: propose_action(
            a_hypothesis_blaming(FailureMode.CONFIG_INDUCED_FAILURE),
            NO_FLAGS_CHANGED,
            SOME_APPLICATION_THE_ALERT_NAMES
        )) \
        .then(_it_rolls_back(SOME_APPLICATION_THE_ALERT_NAMES))


@pytest.mark.unit
def test_a_bad_deployment_is_answered_by_rolling_the_deployment_back() -> None:
    # The same action the config-induced failure is answered by, deliberately: a
    # revision carries the code and the configuration it shipped with, so the
    # platform's rollback is one operation over both. Two modes reaching one
    # strategy is the ordinary shape of a lookup rather than a collision - what
    # separates the modes is the account the incident gives and the fix left
    # afterwards, a values file there and the service's source here.
    Scenario() \
        .given(a_hypothesis_blaming(FailureMode.BAD_DEPLOYMENT)) \
        .when(lambda: propose_action(
            a_hypothesis_blaming(FailureMode.BAD_DEPLOYMENT),
            NO_FLAGS_CHANGED,
            SOME_APPLICATION_THE_ALERT_NAMES
        )) \
        .then(_it_rolls_back(SOME_APPLICATION_THE_ALERT_NAMES))


@pytest.mark.unit
def test_silent_data_corruption_is_answered_by_reverting_the_flag_that_caused_it() -> None:
    # The fourth mode reaching a strategy it does not own, and the only one that
    # maps to an action Argus will not be allowed to take. That is the gate's
    # judgement and not this lookup's: a mode with no strategy answers `None`,
    # which is refused as "nothing answers this kind of failure" and escalates
    # with nothing named - so the incident would end saying a person is needed
    # and not saying what for.
    #
    # The action is the flag toggle's exactly, because the cause is a flag that
    # moved and putting it back is what stops the drift. What differs is
    # everything after: it repairs nothing already written, and nothing can
    # confirm it inside the time Argus waits.
    Scenario() \
        .given(a_hypothesis_blaming(FailureMode.SILENT_DATA_CORRUPTION)) \
        .when(lambda: propose_action(
            a_hypothesis_blaming(FailureMode.SILENT_DATA_CORRUPTION),
            flag_changes=[an_enabling_of(DONT_CARE_FLAG)],
            service=DONT_CARE_SERVICE
        )) \
        .then(_the_action_proposed_names(DONT_CARE_FLAG))


@pytest.mark.unit
def test_silent_data_corruption_a_deployment_caused_is_answered_by_rolling_it_back() -> None:
    # The mode names the damage and not the change, so the action follows the
    # record rather than the mode. A walk that read a flat window and reached
    # for a flag would have learned the flag scenario rather than the mode, and
    # here it would find no flag to put back and recommend nothing at all.
    Scenario() \
        .given(a_hypothesis_blaming(FailureMode.SILENT_DATA_CORRUPTION)) \
        .when(lambda: propose_action(
            a_hypothesis_blaming(FailureMode.SILENT_DATA_CORRUPTION),
            NO_FLAGS_CHANGED,
            SOME_APPLICATION_THE_ALERT_NAMES,
            deployments=[a_deployment()]
        )) \
        .then(_it_rolls_back(SOME_APPLICATION_THE_ALERT_NAMES))


@pytest.mark.unit
def test_silent_data_corruption_with_no_change_recorded_proposes_nothing() -> None:
    # Not a rollback by default. A recommendation is still read and acted on by
    # a person, and a rollback with no deployment behind it sends somebody to
    # undo a week of somebody else's work for a fault it did not cause - a
    # migration, a console edit, anything neither history records.
    Scenario() \
        .given(a_hypothesis_blaming(FailureMode.SILENT_DATA_CORRUPTION)) \
        .when(lambda: propose_action(
            a_hypothesis_blaming(FailureMode.SILENT_DATA_CORRUPTION),
            NO_FLAGS_CHANGED,
            SOME_APPLICATION_THE_ALERT_NAMES,
            deployments=[]
        )) \
        .then(nothing_was_proposed())


@pytest.mark.unit
def test_a_flag_the_corruption_names_wins_over_a_deployment_beside_it() -> None:
    # The more specific evidence is asked first. An estate deploys far more often
    # than it toggles, so a deployment in the window is the weaker claim, and a
    # recorded flag the candidate names is the stronger one.
    the_flag_it_names = "kuki-flag"
    naming_a_flag = a_hypothesis_blaming(
        FailureMode.SILENT_DATA_CORRUPTION, subject=the_flag_it_names
    )

    Scenario() \
        .given(naming_a_flag) \
        .when(lambda: propose_action(
            naming_a_flag,
            [an_enabling_of(the_flag_it_names)],
            SOME_APPLICATION_THE_ALERT_NAMES,
            deployments=[a_deployment()]
        )) \
        .then(_the_action_proposed_names(the_flag_it_names))


@pytest.mark.unit
def test_a_deployment_recorded_changes_nothing_for_any_other_mode() -> None:
    # One mode reads the deploy history. A leak answered by a restart must not
    # change because a revision happened to go out while the heap climbed.
    Scenario() \
        .given(a_leak := a_hypothesis_blaming(FailureMode.RESOURCE_LEAK)) \
        .when(lambda: propose_action(
            a_leak, NO_FLAGS_CHANGED, DONT_CARE_SERVICE, deployments=[a_deployment()]
        )) \
        .then(_the_service_to_restart_is(DONT_CARE_SERVICE))


@pytest.mark.unit
def test_the_strategy_answering_corruption_declares_both_actions_it_may_take() -> None:
    # Which change is undone is the record's to say, so either kind may come
    # back - and a declaration naming one would be wrong whenever the record
    # held the other.
    Scenario() \
        .given(the_mode := FailureMode.SILENT_DATA_CORRUPTION) \
        .when(lambda: DEFAULT_STRATEGIES[the_mode].action_types) \
        .then(_the_kinds_declared_are(
            frozenset({REVERT_FEATURE_FLAG, ROLL_BACK_DEPLOYMENT})
        ))


@pytest.mark.unit
def test_a_monitoring_blind_spot_is_answered_by_rolling_the_deployment_back() -> None:
    # The fourth mode reaching this strategy, and the only one where what the
    # rollback restores is the sight of the service rather than its behaviour.
    # Nothing about the shop got worse - what got worse is what can be seen of
    # it - so what says the action worked is the readings existing again rather
    # than a level coming back down.
    #
    # A flag is handed in and must not be acted on. The blind spot is staged by
    # a revision that stopped the rows reaching the scrape, and a flag that
    # happened to move while that revision was running is a coincidence: a
    # revert would put back something that was never the cause, and would then
    # be judged against readings that are still absent.
    #
    # Registered rather than left out, for the reason silent data corruption is:
    # a mode absent from this mapping answers `None`, which is refused as
    # nothing answering the kind of failure at all - so an incident Argus had
    # diagnosed correctly, and could have ended in seconds by returning one
    # deployment, would escalate to a person with no action named.
    Scenario() \
        .given(a_hypothesis_blaming(FailureMode.MONITORING_BLIND_SPOT)) \
        .when(lambda: propose_action(
            a_hypothesis_blaming(FailureMode.MONITORING_BLIND_SPOT),
            flag_changes=[an_enabling_of(DONT_CARE_FLAG)],
            service=SOME_APPLICATION_THE_ALERT_NAMES
        )) \
        .then(_it_rolls_back(SOME_APPLICATION_THE_ALERT_NAMES))


@pytest.mark.unit
def test_an_in_flight_compatibility_break_is_answered_by_rolling_the_deployment_back() -> None:
    # The third mode reaching this strategy, and the first whose reason is not
    # that the revision carried the fault. Neither revision did - each one alone
    # would work - so what ends the incident is every replica arriving on one of
    # them, and returning the deployment is the call that does it. The account
    # differs and the action does not, which is this mapping being many-to-one
    # on purpose rather than by coincidence.
    Scenario() \
        .given(a_hypothesis_blaming(FailureMode.IN_FLIGHT_COMPATIBILITY_BREAK)) \
        .when(lambda: propose_action(
            a_hypothesis_blaming(FailureMode.IN_FLIGHT_COMPATIBILITY_BREAK),
            NO_FLAGS_CHANGED,
            SOME_APPLICATION_THE_ALERT_NAMES
        )) \
        .then(_it_rolls_back(SOME_APPLICATION_THE_ALERT_NAMES))


@pytest.mark.unit
def test_the_deployment_rolled_back_is_the_one_the_alert_names() -> None:
    # Not Argus's configuration, which would hardcode one deployment's answer
    # into the agent, and not the hypothesis, whose subject is the model's
    # description of what went wrong rather than the name of anything that
    # can be addressed.
    describing_a_symptom = a_hypothesis_blaming(
        FailureMode.CONFIG_INDUCED_FAILURE,
        subject="the summary cache (cache_hit_ratio at 0)"
    )

    Scenario() \
        .given(describing_a_symptom) \
        .when(lambda: propose_action(
            describing_a_symptom, NO_FLAGS_CHANGED, SOME_APPLICATION_THE_ALERT_NAMES
        )) \
        .then(_it_rolls_back(SOME_APPLICATION_THE_ALERT_NAMES))


@pytest.mark.unit
def test_a_rollback_names_no_revision_to_return_to() -> None:
    # Nothing at this layer could name one honestly: a deployment history
    # lives with the platform, behind the write tier, and a strategy inventing
    # an entry would be inventing a state to ship.
    Scenario() \
        .given(a_hypothesis_blaming(FailureMode.CONFIG_INDUCED_FAILURE)) \
        .when(lambda: propose_action(
            a_hypothesis_blaming(FailureMode.CONFIG_INDUCED_FAILURE),
            NO_FLAGS_CHANGED,
            SOME_APPLICATION_THE_ALERT_NAMES
        )) \
        .then(_it_carries_nothing_but_the_application())


@pytest.mark.unit
def test_an_internal_dependency_is_answered_by_restarting_the_dependency() -> None:
    # The first mitigation ever addressed to something other than the service
    # that was paged. Every strategy before this one takes its subject from the
    # alert, which was right for as long as the alerting service was always the
    # faulty one - and this is the incident where it is not.
    the_dependency_that_is_slow = "io-pricing"

    Scenario() \
        .given(
            a_slow_neighbour := a_hypothesis_blaming(
                FailureMode.INTERNAL_DEPENDENCY_FAILURE,
                faulting_service=the_dependency_that_is_slow
            )
        ) \
        .when(
            lambda: RestartDependencyStrategy().propose(
                a_slow_neighbour, NO_FLAGS_CHANGED, service="io-shop"
            )
        ) \
        .then(_the_service_to_restart_is(the_dependency_that_is_slow))


@pytest.mark.unit
def test_the_alerting_service_is_not_what_gets_restarted() -> None:
    # Said as its own case rather than left to the one above, because the two
    # can both be satisfied by accident: a strategy that read the alert would
    # pass the test above if the test happened to name the same service. Here
    # they are deliberately different, and what must not come back is the one
    # the alert named.
    Scenario() \
        .given(
            a_slow_neighbour := a_hypothesis_blaming(
                FailureMode.INTERNAL_DEPENDENCY_FAILURE,
                faulting_service="io-pricing"
            )
        ) \
        .when(
            lambda: RestartDependencyStrategy().propose(
                a_slow_neighbour, NO_FLAGS_CHANGED, service="io-shop"
            )
        ) \
        .then(_it_is_not_a_restart_of("io-shop"))


@pytest.mark.unit
def test_a_dependency_failure_naming_no_service_proposes_nothing() -> None:
    # Unlike the leak, which always has something to restart. Here the address
    # is the whole of what the strategy has to work from, and an answer that
    # fell back to the alerting service would restart the one process this
    # incident has established is healthy - and would then read the shop's
    # unchanged telemetry as evidence that restarting does not help.
    Scenario() \
        .given(
            a_diagnosis_with_no_address := a_hypothesis_blaming(
                FailureMode.INTERNAL_DEPENDENCY_FAILURE
            )
        ) \
        .when(
            lambda: RestartDependencyStrategy().propose(
                a_diagnosis_with_no_address, NO_FLAGS_CHANGED, service="io-shop"
            )
        ) \
        .then(nothing_was_proposed())


@pytest.mark.unit
def test_the_registry_argus_ships_answers_an_internal_dependency_failure() -> None:
    Scenario() \
        .given(
            a_slow_neighbour := a_hypothesis_blaming(
                FailureMode.INTERNAL_DEPENDENCY_FAILURE,
                faulting_service="io-pricing"
            )
        ) \
        .when(
            lambda: propose_action(a_slow_neighbour, NO_FLAGS_CHANGED, "io-shop")
        ) \
        .then(_the_service_to_restart_is("io-pricing"))


@pytest.mark.unit
def test_demand_saturation_is_answered_by_scaling_the_deployment_out() -> None:
    # The fourth generic mitigation, and the first that adds something rather
    # than restoring something. What a saturated deployment needs is headroom it
    # never had, which none of the three that put something back can buy.
    Scenario() \
        .given(
            a_deployment_that_outgrew_its_size := a_hypothesis_blaming(
                FailureMode.DEMAND_SATURATION
            )
        ) \
        .when(
            lambda: ScaleOutStrategy().propose(
                a_deployment_that_outgrew_its_size,
                NO_FLAGS_CHANGED,
                service=SOME_APPLICATION_THE_ALERT_NAMES
            )
        ) \
        .then(_it_scales_out(SOME_APPLICATION_THE_ALERT_NAMES))


@pytest.mark.unit
def test_a_leak_and_a_saturated_service_reach_different_mitigations() -> None:
    # The pair, asked of the registry Argus ships, because the pair is the whole
    # claim: these are the two halves of resource exhaustion and they are
    # separated by what is done about them. Either mode asked alone would pass
    # with both of them mapped to the same strategy, which is exactly the
    # mistake the mode exists to prevent - a restart makes a saturated shop
    # briefly better before the load returns it.
    Scenario() \
        .given(
            the_two_halves_of_resource_exhaustion := [
                a_hypothesis_blaming(FailureMode.RESOURCE_LEAK),
                a_hypothesis_blaming(FailureMode.DEMAND_SATURATION)
            ]
        ) \
        .when(
            lambda: [
                propose_action(
                    hypothesis, NO_FLAGS_CHANGED, SOME_APPLICATION_THE_ALERT_NAMES
                )
                for hypothesis in the_two_halves_of_resource_exhaustion
            ]
        ) \
        .then(
            _the_leak_restarts_and_the_saturation_scales(
                SOME_APPLICATION_THE_ALERT_NAMES
            )
        )


@pytest.mark.unit
def test_the_deployment_scaled_out_is_the_one_the_alert_names() -> None:
    # Not the hypothesis, whose subject is the model's description of what ran
    # out of room rather than the name of anything a platform can be asked
    # about - and not a flag that happened to move while the load was climbing,
    # because no toggle causes traffic to arrive.
    describing_what_ran_out = a_hypothesis_blaming(
        FailureMode.DEMAND_SATURATION,
        subject="io-shop CPU (cpu_used_cores pinned at a 3.0 core limit)"
    )

    Scenario() \
        .given(
            a_flag_that_moved_meanwhile := [an_enabling_of(DONT_CARE_FLAG)]
        ) \
        .when(
            lambda: ScaleOutStrategy().propose(
                describing_what_ran_out,
                a_flag_that_moved_meanwhile,
                service=SOME_APPLICATION_THE_ALERT_NAMES
            )
        ) \
        .then(_it_scales_out(SOME_APPLICATION_THE_ALERT_NAMES))


@pytest.mark.unit
def test_a_scale_out_names_no_count_to_scale_to() -> None:
    # A stronger version of the reason a rollback names no revision. A target
    # count is meaningless without the count it replaces, that count is live
    # state only the write tier can read, and a strategy asserting six would be
    # asserting the deployment is running three - a fact no evidence in front of
    # it carries, and one that stops being true the moment anybody scales.
    Scenario() \
        .given(a_hypothesis_blaming(FailureMode.DEMAND_SATURATION)) \
        .when(lambda: propose_action(
            a_hypothesis_blaming(FailureMode.DEMAND_SATURATION),
            NO_FLAGS_CHANGED,
            SOME_APPLICATION_THE_ALERT_NAMES
        )) \
        .then(_the_scale_out_carries_nothing_but_the_application())


def _no_strategies() -> Strategies:
    """A registry that answers for no cause at all.

    Spelled out rather than written as a bare `{}` at each call, because an
    empty mapping needs its type named for it to be one of these.
    """
    return {}


@pytest.mark.unit
def test_state_divergence_is_answered_by_discarding_the_entries_named() -> None:
    # The sixth generic mitigation, and the first that removes rather than puts
    # back. What makes it a complete fix is that the authority it was derived
    # from never moved: the entries go, and the next read works the figure out
    # again from data nothing touched.
    some_stale_keys = ("io-shop:summary:shopper-3", "io-shop:summary:shopper-7")

    Scenario() \
        .given(
            a_promoted_stale_replica := a_hypothesis_blaming(
                FailureMode.STATE_DIVERGENCE
            )
        ) \
        .when(
            lambda: propose_action(
                a_promoted_stale_replica,
                NO_FLAGS_CHANGED,
                DONT_CARE_SERVICE,
                stale_entry_keys=some_stale_keys
            )
        ) \
        .then(
            _the_entries_discarded_are(some_stale_keys)
        )


@pytest.mark.unit
def test_the_entries_discarded_are_the_evidence_s_exactly_and_entirely() -> None:
    # The keys travel as data from the check that found them to the call that
    # removes them, and nothing in between may add one, drop one or reorder
    # them. Duplicates and an unsorted order are both in here on purpose: a
    # strategy that passed them through a set would answer with the same count
    # and a different collection.
    many_stale_keys = tuple(
        f"io-shop:summary:shopper-{index}" for index in (9, 2, 2, 40, 1)
    )

    Scenario() \
        .given(
            a_promoted_stale_replica := a_hypothesis_blaming(
                FailureMode.STATE_DIVERGENCE
            )
        ) \
        .when(
            lambda: propose_action(
                a_promoted_stale_replica,
                NO_FLAGS_CHANGED,
                DONT_CARE_SERVICE,
                stale_entry_keys=many_stale_keys
            )
        ) \
        .then(
            _the_entries_discarded_are(many_stale_keys)
        )


@pytest.mark.unit
def test_a_divergence_naming_no_entries_proposes_nothing() -> None:
    # Not an empty discard. An action that reached the store and removed nothing
    # comes back with a count of zero, and a zero is indistinguishable from
    # entries somebody else had already discarded - so the attempt would be
    # confirmed by a receipt saying nothing happened.
    Scenario() \
        .given(
            a_divergence_naming_nothing := a_hypothesis_blaming(
                FailureMode.STATE_DIVERGENCE
            )
        ) \
        .when(
            lambda: propose_action(
                a_divergence_naming_nothing,
                NO_FLAGS_CHANGED,
                DONT_CARE_SERVICE,
                stale_entry_keys=()
            )
        ) \
        .then(
            nothing_was_proposed()
        )


@pytest.mark.unit
def test_a_mode_carrying_no_entries_is_answered_as_it_always_was() -> None:
    # Every other mode reaches this lookup with nothing to discard, so an
    # absence of keys is the ordinary state of this input rather than a fault. A
    # leak answered by a restart must not change because a different mode
    # acquired a fourth kind of evidence.
    Scenario() \
        .given(
            a_leak := a_hypothesis_blaming(FailureMode.RESOURCE_LEAK)
        ) \
        .when(
            lambda: propose_action(a_leak, NO_FLAGS_CHANGED, DONT_CARE_SERVICE)
        ) \
        .then(
            _the_service_to_restart_is(DONT_CARE_SERVICE)
        )


@pytest.mark.unit
def test_the_registry_argus_ships_answers_state_divergence() -> None:
    Scenario() \
        .given(
            the_mode_a_discard_answers := FailureMode.STATE_DIVERGENCE
        ) \
        .when(
            lambda: a_mitigation_answers(the_mode_a_discard_answers)
        ) \
        .then(
            _the_answer_is(True)
        )


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

    action_types: frozenset[ActionType] = frozenset({REVERT_FEATURE_FLAG})

    def __init__(self, proposing: Action | None) -> None:
        self._proposing = proposing

    def propose(self,
                dont_care_hypothesis: Hypothesis,
                dont_care_flag_changes: Sequence[FlagChange],
                service: str,
                stale_entry_keys: Sequence[str] = (),
                deployments: Sequence[ChangeEvent] = ()) -> Action | None:
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


def _the_answer_is(expected: bool) -> Assertion[bool]:
    def assertion(answered: bool) -> bool:
        if answered is not expected:
            raise AssertionError(
                f"Expected [{expected}], got [{answered}]."
            )

        return True

    return assertion


def _it_scales_out(application: str) -> Assertion[Action | None]:
    def assertion(action: Action | None) -> bool:
        if not isinstance(action, ScaleOut):
            raise AssertionError(f"Expected a scale-out, got [{action}].")

        if action.application != application:
            raise AssertionError(
                f"Expected [{application}] to be scaled out, and "
                f"[{action.application}] was."
            )

        return True

    return assertion


def _the_leak_restarts_and_the_saturation_scales(
    service: str
) -> Assertion[Sequence[Action | None]]:
    """Both halves reported, whichever of them the registry got wrong."""
    def assertion(proposed: Sequence[Action | None]) -> bool:
        for_the_leak, for_the_saturation = proposed
        wrong: list[str] = []

        if not isinstance(for_the_leak, RestartService):
            wrong.append(
                f"a leak should be answered by a restart of [{service}], and it "
                f"was answered with [{for_the_leak}]"
            )

        if not isinstance(for_the_saturation, ScaleOut):
            wrong.append(
                f"demand saturation should be answered by a scale-out of "
                f"[{service}], and it was answered with [{for_the_saturation}]"
            )

        if wrong:
            raise AssertionError(
                "Expected the two halves of resource exhaustion to reach "
                f"different mitigations: {'; '.join(wrong)}."
            )

        return True

    return assertion


def _the_scale_out_carries_nothing_but_the_application() -> Assertion[Action | None]:
    def assertion(action: Action | None) -> bool:
        if not isinstance(action, ScaleOut):
            raise AssertionError(f"Expected a scale-out, got [{action}].")

        carried = set(action.model_dump()) - {"action_type", "application"}

        if carried:
            raise AssertionError(
                f"Expected a scale-out naming only the application, and it also "
                f"carried {sorted(carried)}."
            )

        return True

    return assertion


def _it_is_not_a_restart_of(service: str) -> Assertion[Action | None]:
    def assertion(action: Action | None) -> bool:
        if isinstance(action, RestartService) and action.service == service:
            raise AssertionError(
                f"The mitigation was addressed to [{service}], which is the "
                f"service the alert named and the one this incident establishes "
                f"is healthy."
            )

        return True

    return assertion


def _it_rolls_back(application: str) -> Assertion[Action | None]:
    def assertion(action: Action | None) -> bool:
        if not isinstance(action, RollBackDeployment):
            raise AssertionError(f"Expected a rollback, got [{action}].")

        if action.application != application:
            raise AssertionError(
                f"Expected [{application}] to be rolled back, and "
                f"[{action.application}] was."
            )

        return True

    return assertion


def _it_carries_nothing_but_the_application() -> Assertion[Action | None]:
    def assertion(action: Action | None) -> bool:
        if not isinstance(action, RollBackDeployment):
            raise AssertionError(f"Expected a rollback, got [{action}].")

        carried = set(action.model_dump()) - {"action_type", "application"}

        if carried:
            raise AssertionError(
                f"Expected a rollback naming only the application, and it also "
                f"carried {sorted(carried)}."
            )

        return True

    return assertion


def _the_entries_discarded_are(expected: tuple[str, ...]) -> Assertion[Action | None]:
    """Exactly the addresses the evidence named, in the order it named them.

    Order and entirety are both asserted because both can be lost silently. A
    set would discard duplicates and a sorted sequence would reorder, and either
    produces a call that removes a different collection of entries while
    reporting the same count - which is the one corruption a receipt cannot
    expose, since the count would still be right.
    """
    def assertion(action: Action | None) -> bool:
        if not isinstance(action, DiscardCacheEntries):
            raise AssertionError(
                f"Expected a discard of the entries the evidence named, and the "
                f"strategy proposed {action!r}."
            )

        if action.keys != expected:
            raise AssertionError(
                f"The entries proposed for discard are not the ones the evidence "
                f"named: expected {expected}, and the action carries "
                f"{action.keys}. Argus composes no key, so anything here the "
                f"alert did not carry was invented, and anything missing was "
                f"dropped on the way."
            )

        return True

    return assertion


def _the_kinds_declared_are(
    expected: frozenset[ActionType]
) -> Assertion[frozenset[ActionType]]:
    def assertion(declared: frozenset[ActionType]) -> bool:
        if declared != expected:
            raise AssertionError(
                f"Expected the strategy to declare it may answer with "
                f"{sorted(expected)}, and it declares {sorted(declared)}."
            )

        return True

    return assertion
