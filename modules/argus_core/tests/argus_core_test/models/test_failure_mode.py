"""What each way of breaking means, in the words the model weighing it reads.

The taxonomy reaches the model as a list of values in a tool schema, and a value
is all it has to tell two modes apart by unless the meaning travels with it. So
the meanings are part of the contract rather than documentation: a mode added
without one is a mode the model has to infer from its spelling, and the pair it
most often confuses is exactly the pair that dispatches to different mitigations.

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
    # Both arrive as a deployment, and they are answered by different
    # mitigations: one rolls the code back, the other returns the application to
    # a configuration revision that already ran. A model that has just seen a
    # deploy land at the onset reads the change as a bad deployment unless the
    # meaning tells it when to prefer the other - which is not the model being
    # careless, it is the taxonomy declining to say.
    Scenario() \
        .given(config_induced := FailureMode.CONFIG_INDUCED_FAILURE) \
        .when(lambda: config_induced.meaning()) \
        .then(_it_says_when_to_prefer_it_to(FailureMode.BAD_DEPLOYMENT))


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


def _it_says_when_to_prefer_it_to(other: FailureMode) -> Assertion[str]:
    def assertion(meaning: str) -> bool:
        if other.value not in meaning:
            raise AssertionError(
                f"The meaning of [{FailureMode.CONFIG_INDUCED_FAILURE.value}] "
                f"never mentions [{other.value}], so nothing tells a model "
                f"reading a deploy that landed at the onset which of the two "
                f"it is looking at - and the two are answered by different "
                f"mitigations."
            )

        return True

    return assertion
