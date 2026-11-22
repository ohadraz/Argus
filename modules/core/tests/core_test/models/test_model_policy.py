"""Which model answers an agent, and how hard it is asked to think.

Three fields and one rule between them, but the rule is the whole reason this
is a type rather than three loose arguments: an effort that does not exist
must fail when the configuration is read, at startup, and not on the first
call of the first incident - by which point an agent has been assembled, a
walk has been claimed, and the thing that fails is an investigation somebody
was waiting on.

The defaults matter as much as the validation. An agent naming its model and
nothing else gets the effort and the room every agent got when there was one
answer for all of them, so adding the choice cannot quietly change what an
unconfigured deployment does. The model itself has no default: it is a name in
one provider's catalogue, and the provider's adapter says which one answers a
caller with no opinion.
"""

from __future__ import annotations

import pytest
from argus_testkit import (
    Assertion,
    Scenario,
    all_of,
    an_error_was_raised,
    attempting,
    the_error_mentioned,
)
from core.models.model_policy import (
    DEFAULT_EFFORT,
    DEFAULT_MAX_OUTPUT_TOKENS,
    ModelPolicy,
    Reasoning,
)
from pydantic import ValidationError

# Argus's five, written out here rather than read off `Reasoning`. That is the
# whole point of the acceptance case below: a level the scale has lost is a
# level no deployment can select, and a list derived from `Reasoning` would lose
# it in the same breath and report nothing. As text, because text is how a
# level arrives - out of an environment, as words nobody type-checked.
EVERY_LEVEL_A_DEPLOYMENT_MAY_NAME = ("low", "medium", "high", "higher", "highest")

# Whichever model a policy is for, where the case is about something else.
DONT_CARE_MODEL = "dont-care-model"


@pytest.mark.unit
def test_an_effort_nobody_implements_is_refused() -> None:
    # The reason this is an enum and not a string. An effort nobody
    # implements is a request no provider can take, and the useful moment to
    # find that out is when the configuration is read rather than partway
    # through the first incident of the day.
    #
    # Validated from a mapping rather than constructed, because a mapping is
    # how such a value actually arrives - out of an environment, as text
    # nobody type-checked. Writing it as a constructor call would be asking
    # the type system to overlook the one mistake only the runtime can catch.
    Scenario() \
        .given(
            an_effort_nobody_implements := "exhaustive"
        ) \
        .when(
            attempting(
                lambda: ModelPolicy.model_validate({"model": DONT_CARE_MODEL,
                                                    "effort": an_effort_nobody_implements})
            )
        ) \
        .then(
            all_of(
                an_error_was_raised(ValidationError),
                the_error_mentioned("effort")
            )
        )


@pytest.mark.unit
def test_a_vendors_own_spelling_of_a_level_is_refused() -> None:
    # The scale is Argus's, so a deployment written against one vendor's words
    # fails when it loads rather than reaching that vendor by accident - or,
    # worse, being read as some other level by a provider that spells it
    # differently.
    Scenario() \
        .given(
            a_vendors_own_word := "xhigh"
        ) \
        .when(
            attempting(
                lambda: ModelPolicy.model_validate({"model": DONT_CARE_MODEL,
                                                    "effort": a_vendors_own_word})
            )
        ) \
        .then(
            all_of(
                an_error_was_raised(ValidationError),
                the_error_mentioned("effort")
            )
        )


@pytest.mark.unit
def test_a_policy_naming_only_its_model_asks_what_every_agent_used_to_ask() -> None:
    # Per-agent policy arrived after a single shared answer, and it must not
    # have moved the answer on its way in: a deployment that names only each
    # agent's model is asked as every agent used to be.
    some_model = "some-model"

    Scenario() \
        .given(
            what_every_agent_used_to_share := (
                some_model, DEFAULT_EFFORT, DEFAULT_MAX_OUTPUT_TOKENS
            )
        ) \
        .when(
            lambda: ModelPolicy(model=some_model)
        ) \
        .then(
            _it_asks_for(*what_every_agent_used_to_share)
        )


@pytest.mark.unit
def test_a_policy_naming_no_model_is_refused() -> None:
    # A model is a name in one provider's catalogue, so a default here would be
    # a vendor's name in a kernel that names none - and an agent nobody gave a
    # model would be answered by whichever one that was.
    Scenario() \
        .given(
            a_policy_naming_only_an_effort := {"effort": "high"}
        ) \
        .when(
            attempting(lambda: ModelPolicy.model_validate(a_policy_naming_only_an_effort))
        ) \
        .then(
            all_of(
                an_error_was_raised(ValidationError),
                the_error_mentioned("model")
            )
        )


@pytest.mark.unit
def test_every_level_a_deployment_may_name_is_accepted() -> None:
    # The other side of the rejection above, and the one that would fail
    # silently: a scale missing a level is a level no deployment can select,
    # and nothing would say so except a configuration that refused to load.
    Scenario() \
        .given(
            EVERY_LEVEL_A_DEPLOYMENT_MAY_NAME
        ) \
        .when(
            lambda: [
                ModelPolicy.model_validate({"model": DONT_CARE_MODEL, "effort": named}).effort
                for named in EVERY_LEVEL_A_DEPLOYMENT_MAY_NAME
            ]
        ) \
        .then(
            _all_of_them_came_back(EVERY_LEVEL_A_DEPLOYMENT_MAY_NAME)
        )


def _it_asks_for(model: str,
                 effort: Reasoning,
                 max_output_tokens: int) -> Assertion[ModelPolicy]:
    """The three answers a policy naming only its model gives, checked together.

    Together rather than one at a time, because the claim is about the whole
    posture towards a deployment that named only the model: a field that quietly
    acquired a new default would slip past a run of assertions that stopped at
    the first one to fail, and the field that moved is the one nobody would
    then be looking at.
    """
    def assertion(asked_of: ModelPolicy) -> bool:
        wanted = {
            "model": model, "effort": effort, "max_output_tokens": max_output_tokens
        }
        moved = {
            field: (expected, getattr(asked_of, field))
            for field, expected in wanted.items()
            if getattr(asked_of, field) != expected
        }
        if moved:
            raise AssertionError(
                f"Expected a policy naming only its model to be unchanged, and {moved} "
                f"differed (expected, got)."
            )

        return True

    return assertion


def _all_of_them_came_back(expected: tuple[str, ...]) -> Assertion[list[Reasoning]]:
    """That every level named was accepted, and came back as it was named.

    Came back rather than merely did not raise: a field that accepted a level
    and stored something else would satisfy "no error" and be wrong in the way
    that matters, since what is read afterwards is the stored value.
    """
    def assertion(accepted: list[Reasoning]) -> bool:
        if [str(level) for level in accepted] != list(expected):
            raise AssertionError(
                f"Expected every level a deployment may name to come back as named, "
                f"named {list(expected)} and got {[str(level) for level in accepted]}."
            )

        return True

    return assertion
