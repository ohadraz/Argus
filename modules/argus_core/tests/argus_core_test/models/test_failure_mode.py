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
