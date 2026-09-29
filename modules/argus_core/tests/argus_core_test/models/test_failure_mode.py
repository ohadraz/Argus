"""What each way of breaking means, in the words the model weighing it reads.

The taxonomy reaches the model as a list of values in a tool schema, and a value
is all it has to tell two modes apart by unless the meaning travels with it. So
the meanings are part of the contract rather than documentation: a mode added
without one is a mode the model has to infer from its spelling, and the pairs it
most often confuses are exactly the pairs whose evidence looks the same.

Asserted here rather than left to the agent that builds the schema. Without a
meaning the lookup raises while another module's tool definition is being
assembled - a failure that names the wrong package, at import time, in a suite
belonging to somebody who did not add the mode.
"""

from __future__ import annotations

import pytest
from argus_core.models import FailureMode
from argus_testkit import Assertion, Scenario, all_of


@pytest.mark.unit
def test_every_cause_says_what_it_means_and_not_only_what_it_is_called() -> None:
    Scenario() \
        .given(the_taxonomy := list(FailureMode)) \
        .when(lambda: {cause: _what_it_means(cause) for cause in the_taxonomy}) \
        .then(all_of(
            _every_cause_has_a_meaning(),
            _no_meaning_merely_repeats_the_name()
        ))


@pytest.mark.unit
def test_the_two_causes_a_deploy_could_be_say_what_separates_them() -> None:
    # Both arrive as a deployment and both are answered by returning it, so the
    # mitigation is not what tells them apart. What differs is the account the
    # incident gives and the fix left afterwards - a values file for one, the
    # service's source for the other - and a model that has just seen a deploy
    # land at the onset reads the change as a bad deployment unless the meaning
    # says when to prefer the other. That is not the model being careless, it is
    # the taxonomy declining to say.
    Scenario() \
        .given(config_induced := FailureMode.CONFIG_INDUCED_FAILURE) \
        .when(lambda: config_induced.meaning()) \
        .then(_the_meaning_of(config_induced).says_when_to_prefer_it_to(
            FailureMode.BAD_DEPLOYMENT
        ))


@pytest.mark.unit
def test_the_two_ways_a_neighbour_can_fail_say_what_separates_them() -> None:
    # The harder pair, and the one where the evidence genuinely cannot decide
    # it. Both are a service on the request path going wrong, both arrive as
    # this service's own latency or errors, and both are blamed by the caller's
    # own logs naming a host. The only thing that separates them is whether the
    # organisation owns that host, which is a fact no telemetry carries - so
    # each meaning has to send the model to the register rather than leaving it
    # to read the spelling of a host name.
    #
    # Both directions, unlike the pair above. That one has an order to it: a
    # deploy is the reading a model reaches first and the meaning only has to
    # argue it out of that. Here neither is the obvious reading, and whichever
    # the model considers first is the one that has to mention the other.
    Scenario() \
        .given(internal := FailureMode.INTERNAL_DEPENDENCY_FAILURE) \
        .when(lambda: (internal, FailureMode.UPSTREAM_DEPENDENCY_FAILURE)) \
        .then(all_of(
            _each_of_the_pair_names_the_other(),
            _the_pair_is_told_apart_by_ownership()
        ))


@pytest.mark.unit
def test_the_two_halves_of_resource_exhaustion_say_what_separates_them() -> None:
    # One resource, two responses, and a latency graph on which they are the same
    # shape. A leak is answered by reclaiming what accumulated and this by adding
    # capacity, so a model that reads saturation as a leak gets a restart that
    # makes the service briefly better before it returns - which is the mistake
    # the taxonomy says a system without the distinction makes.
    #
    # Both directions, as with the dependency pair: neither is the obvious
    # reading, so whichever the model considers first has to mention the other.
    Scenario() \
        .given(the_two_halves := (
            FailureMode.RESOURCE_LEAK, FailureMode.DEMAND_SATURATION
        )) \
        .when(lambda: the_two_halves) \
        .then(all_of(
            _each_of_the_pair_names_the_other(),
            _the_pair_is_told_apart_by_the_traffic()
        ))


@pytest.mark.unit
def test_the_two_ways_capacity_can_be_wrong_say_what_separates_them() -> None:
    # The third capacity mode, and the pair where the evidence decides least. At
    # the bottom of every cycle a capacity that will not settle is saturation
    # exactly: the same alert, the same latency climb, the same traffic several
    # times the baseline, the same empty change channels. One field differs - the
    # capacity the deployment had, which takes more than one value across the
    # window - so this distinction has to be somewhere to look rather than a
    # judgement to make.
    #
    # Both directions, as with the two pairs above. The cost of getting it wrong
    # is the sharpest of the three: the two are answered by opposite actions, so a
    # model that reads a flap as saturation gets the mitigation the controller
    # undoes, and a model that reads saturation as a flap stops a controller that
    # was never running.
    Scenario() \
        .given(the_two_ways := (
            FailureMode.DEMAND_SATURATION, FailureMode.AUTOSCALING_PATHOLOGY
        )) \
        .when(lambda: the_two_ways) \
        .then(all_of(
            _each_of_the_pair_names_the_other(),
            _the_pair_is_told_apart_by_the_capacity()
        ))


@pytest.mark.unit
def test_the_two_ways_a_deployment_can_be_wrong_say_what_separates_them() -> None:
    # The fourth pair, and the one whose evidence agrees most completely. Both
    # arrive as one deploy entry at the onset, both move the service, and the
    # history recording that deploy cannot decide between them: it says a
    # revision was deployed and nothing about whether the revision finished
    # arriving. One channel differs - the rollout the platform is running - so
    # this distinction has to be somewhere to look rather than a judgement to
    # make.
    #
    # Both directions, as with the three pairs above, and here the cost of the
    # unmentioned direction is a false record rather than a wrong action: the
    # two are answered by the same rollback, so a model that reads a stalled
    # rollout as a bad deployment ends the incident and then files a fix against
    # code with no defect in it.
    Scenario() \
        .given(the_two_ways := (
            FailureMode.BAD_DEPLOYMENT,
            FailureMode.IN_FLIGHT_COMPATIBILITY_BREAK
        )) \
        .when(lambda: the_two_ways) \
        .then(all_of(
            _each_of_the_pair_names_the_other(),
            _the_pair_is_told_apart_by_the_rollout()
        ))


@pytest.mark.unit
def test_the_mode_whose_damage_outlives_its_cause_says_so() -> None:
    # The fifth pair, and the first whose two members can share a cause. A flag
    # moved at the onset in both, and the flag history says the same thing about
    # each: somebody turned something on and the shop went wrong from there. No
    # series separates them either - one steps the error rate, the other moves
    # nothing at all, and a model reading a flat window has nothing to compare.
    #
    # What decides it is what the flag left written. The cost of the wrong
    # reading is the sharpest in the taxonomy so far, because the mitigation
    # appears to work: the flag goes back, the drift stops, the incident is
    # closed as mitigated, and every value already written is still wrong with
    # nobody left looking at it.
    Scenario() \
        .given(the_pair := (
            FailureMode.FEATURE_FLAG_TOGGLE,
            FailureMode.SILENT_DATA_CORRUPTION
        )) \
        .when(lambda: the_pair) \
        .then(all_of(
            _each_of_the_pair_names_the_other(),
            _the_pair_is_told_apart_by_what_the_change_left_behind()
        ))


def _what_it_means(cause: FailureMode) -> str:
    """The meaning, or the empty string where asking for one fails.

    Caught rather than allowed to raise, so that a mode with no meaning is
    reported by the assertion below - naming the mode - instead of ending the
    test on a `KeyError` that names only the dictionary.
    """
    try:
        return cause.meaning()
    except KeyError:
        return ""


def _every_cause_has_a_meaning() -> Assertion[dict[FailureMode, str]]:
    def assertion(meanings: dict[FailureMode, str]) -> bool:
        unexplained = [
            cause.value for cause, meaning in meanings.items() if not meaning
        ]

        if unexplained:
            raise AssertionError(
                f"{sorted(unexplained)} reach the model as bare names: nothing "
                f"says what they mean, so telling them apart is guesswork from "
                f"the spelling."
            )

        return True

    return assertion


def _no_meaning_merely_repeats_the_name() -> Assertion[dict[FailureMode, str]]:
    """A meaning has to add something the value does not already say.

    `bad-deployment` explained as "a bad deployment" passes the check above and
    tells a reader nothing, which is the failure this catches: the point is what
    was observed and what separates it from its nearest neighbour.
    """
    def assertion(meanings: dict[FailureMode, str]) -> bool:
        empty_of_content = [
            cause.value for cause, meaning in meanings.items()
            if len(meaning.split()) <= len(cause.value.split("-"))
        ]

        if empty_of_content:
            raise AssertionError(
                f"{sorted(empty_of_content)} are explained in no more words "
                f"than their own names contain, which is a restatement rather "
                f"than a meaning."
            )

        return True

    return assertion


def _the_meaning_of(cause: FailureMode) -> _Meaning:
    """One mode's meaning, named so the call site reads as a sentence.

    A factory rather than a lowercase class, for the reason `_the_field` is one
    in the Investigator's suite: the sentence is what the name is for, and a
    class spelled to make it work is a class named against the convention.
    """
    return _Meaning(cause)


class _Meaning:
    """The assertions about one mode's meaning, which all need to name it.

    A class rather than a run of functions each taking the mode again: the
    failure message has to say whose meaning fell short, and threading that
    through every helper is how it comes to be left out of one of them.
    """

    def __init__(self, cause: FailureMode) -> None:
        self._cause = cause

    def says_when_to_prefer_it_to(self, other: FailureMode) -> Assertion[str]:
        def assertion(meaning: str) -> bool:
            if other.value not in meaning:
                raise AssertionError(
                    f"The meaning of [{self._cause.value}] never mentions "
                    f"[{other.value}], so nothing tells a model looking at "
                    f"evidence that fits both which of the two it is looking "
                    f"at."
                )

            return True

        return assertion


def _each_of_the_pair_names_the_other() -> Assertion[tuple[FailureMode, FailureMode]]:
    def assertion(pair: tuple[FailureMode, FailureMode]) -> bool:
        one, other = pair
        silent = [
            cause.value for cause, neighbour in ((one, other), (other, one))
            if neighbour.value not in cause.meaning()
        ]

        if silent:
            raise AssertionError(
                f"{sorted(silent)} never mention the mode they are hardest to "
                f"tell apart from, so a model that considered one of them first "
                f"has nothing sending it to look at the other."
            )

        return True

    return assertion


def _the_pair_is_told_apart_by_ownership() -> Assertion[tuple[FailureMode, FailureMode]]:
    """Each meaning has to say that ownership is the question.

    Naming the other mode is not enough on its own: "not to be confused with
    upstream-dependency-failure" tells a model there is a distinction and not
    how to make it. What a model actually has in front of it is a host name,
    and the answer is never in the host name.
    """
    def assertion(pair: tuple[FailureMode, FailureMode]) -> bool:
        vague = [
            cause.value for cause in pair
            if "own" not in cause.meaning()
        ]

        if vague:
            raise AssertionError(
                f"{sorted(vague)} distinguish themselves from their neighbour "
                f"without saying that what separates them is who owns the "
                f"failing service - so the model is told there is a "
                f"distinction and not how to make it."
            )

        return True

    return assertion


def _the_pair_is_told_apart_by_the_traffic() -> Assertion[
    tuple[FailureMode, FailureMode]
]:
    """Each meaning has to say that the traffic is the question.

    Naming the other mode is not enough, for the reason it is not enough of the
    dependency pair: a model told these two are different still has to be told
    how to decide. What it has in front of it is a resource running out, which
    both are - and the only thing that separates them is whether the traffic moved
    with the consumption.
    """
    def assertion(pair: tuple[FailureMode, FailureMode]) -> bool:
        vague = [
            cause.value for cause in pair
            if "traffic" not in cause.meaning()
        ]

        if vague:
            raise AssertionError(
                f"{sorted(vague)} distinguish themselves from their neighbour "
                f"without saying that what separates them is whether the "
                f"traffic moved with the consumption - so the model is told "
                f"there is a distinction and not how to make it."
            )

        return True

    return assertion


def _the_pair_is_told_apart_by_the_capacity() -> Assertion[
    tuple[FailureMode, FailureMode]
]:
    """Each meaning has to name the series that decides it.

    Naming the other mode is not enough, for the reason it is not enough of
    either pair above - and here it is less enough than anywhere else, because
    there is no judgement left to fall back on. At the bottom of every cycle a
    capacity that will not settle *is* a capacity that was outgrown, in the
    alert, in the latency, in the traffic and in the empty change channels. So a
    meaning that does not send the model to one field sends it nowhere.
    """
    def assertion(pair: tuple[FailureMode, FailureMode]) -> bool:
        vague = [
            cause.value for cause in pair
            if "cpu_limit_cores" not in cause.meaning()
        ]

        if vague:
            raise AssertionError(
                f"{sorted(vague)} distinguish themselves from their neighbour "
                f"without naming the series that separates them - the capacity "
                f"the deployment had, which moves in one of the pair and holds "
                f"still in the other - so the model is left to judge where it "
                f"could have looked."
            )

        return True

    return assertion


def _the_pair_is_told_apart_by_the_rollout() -> Assertion[
    tuple[FailureMode, FailureMode]
]:
    """Each meaning has to send the model to the rollout.

    Naming the other mode is not enough, for the reason it is not enough of any
    pair above. What a model has in front of it is a deployment at the onset,
    which both of these have, and the deploy history cannot decide between them:
    it records that a revision was deployed and says nothing about whether that
    revision finished arriving. So a meaning that does not send the model to the
    rollout leaves it choosing between a faulty revision and a half-applied one
    on evidence that describes the two identically.
    """
    def assertion(pair: tuple[FailureMode, FailureMode]) -> bool:
        vague = [
            cause.value for cause in pair
            if "rollout" not in cause.meaning()
        ]

        if vague:
            raise AssertionError(
                f"{sorted(vague)} distinguish themselves from their neighbour "
                f"without sending the model to the rollout - whether the "
                f"deployment converged - so the model is left to judge between "
                f"a wrong revision and two revisions serving at once where it "
                f"could have looked."
            )

        return True

    return assertion


def _the_pair_is_told_apart_by_what_the_change_left_behind() -> Assertion[
    tuple[FailureMode, FailureMode]
]:
    """Each meaning has to say whether putting the change back ends it.

    Naming the other mode is not enough, for the reason it is not enough of any
    pair above - and here the evidence agrees on the one thing a model looks at
    first. Both of these arrive as a flag that moved at the onset, and the flag
    history describes the two identically: somebody turned something on, and the
    shop went wrong from that minute.

    What separates them is what the flag left behind. Put it back and a toggle
    is over; put it back here and the drift stops while every value already
    written stays wrong. So a meaning that does not send the model to what the
    service has already written leaves it reading a mode whose damage outlives
    its cause as one whose damage ends with it - and the cost of that reading is
    an incident closed as mitigated over a shop that is still lying.
    """
    def assertion(pair: tuple[FailureMode, FailureMode]) -> bool:
        vague = [
            cause.value for cause in pair
            if "written" not in cause.meaning()
        ]

        if vague:
            raise AssertionError(
                f"{sorted(vague)} distinguish themselves from their neighbour "
                f"without saying what the change left written behind it - so a "
                f"model is told there is a distinction and not that putting the "
                f"flag back ends one of the pair and repairs nothing in the "
                f"other."
            )

        return True

    return assertion
