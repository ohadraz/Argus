"""Which model answers an agent, and how hard it is asked to think.

Three fields and one rule between them, but the rule is the whole reason this
is a type rather than three loose arguments: an effort that does not exist
must fail when the configuration is read, at startup, and not on the first
call of the first incident - by which point an agent has been assembled, a
walk has been claimed, and the thing that fails is an investigation somebody
was waiting on.

The defaults matter as much as the validation. A deployment naming none of
these gets what every agent got when there was one answer for all of them, so
adding the choice cannot quietly change what an unconfigured deployment does.
"""

from __future__ import annotations

import pytest
from argus_core.models.model_policy import (
    DEFAULT_EFFORT,
    DEFAULT_MAX_OUTPUT_TOKENS,
    DEFAULT_MODEL,
    LARGEST_UNSTREAMED_ANSWER,
    Effort,
    ModelPolicy,
)
from argus_testkit import (
    Assertion,
    Scenario,
    all_of,
    an_error_was_raised,
    attempting,
    the_error_mentioned,
)
from pydantic import ValidationError

# Anthropic's five, written out here rather than read off `Effort`. That is the
# whole point of the acceptance case below: a level the API offers and the
# `Literal` has lost is a level no deployment can select, and a list derived
# from `Effort` would lose it in the same breath and report nothing. Annotated
# rather than inferred, so that losing one fails the type check as well as the
# run - the same guard said twice, once at each moment it could be noticed.
EVERY_EFFORT_THE_MODEL_OFFERS: tuple[Effort, ...] = ("low", "medium", "high", "xhigh", "max")


@pytest.mark.unit
def test_an_effort_the_model_does_not_offer_is_refused() -> None:
    # The reason this is a `Literal` and not a string. An effort nobody
    # implements is a request the API rejects, and the useful moment to find
    # that out is when the configuration is read rather than partway through
    # the first incident of the day.
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
                lambda: ModelPolicy.model_validate({"effort": an_effort_nobody_implements})
            )
        ) \
        .then(
            all_of(
                an_error_was_raised(ValidationError),
                the_error_mentioned("effort")
            )
        )


@pytest.mark.unit
def test_a_policy_nobody_configured_asks_what_every_agent_used_to_ask() -> None:
    # Per-agent policy arrived after a single shared answer, and it must not
    # have moved the answer on its way in: a deployment that names nothing is
    # a deployment nothing changed for.
    Scenario() \
        .given(
            what_every_agent_used_to_share := (
                DEFAULT_MODEL, DEFAULT_EFFORT, DEFAULT_MAX_OUTPUT_TOKENS
            )
        ) \
        .when(
            lambda: ModelPolicy()
        ) \
        .then(
            _it_asks_for(*what_every_agent_used_to_share)
        )


@pytest.mark.unit
def test_the_default_answer_fits_in_one_response() -> None:
    # The default has to sit under the line where the SDK refuses to send a
    # non-streaming request, because most agents answer with a short verdict
    # and streaming every one of them would take on the harder-to-read
    # failure mode for nothing. Code-Fix is the exception and says so by
    # configuring its own.
    Scenario() \
        .given(
            where_an_answer_starts_having_to_stream := LARGEST_UNSTREAMED_ANSWER
        ) \
        .when(
            lambda: ModelPolicy().max_output_tokens
        ) \
        .then(
            _room_enough_to_stay_under(where_an_answer_starts_having_to_stream)
        )


@pytest.mark.unit
def test_every_effort_the_model_offers_is_accepted() -> None:
    # The other side of the rejection above, and the one that would fail
    # silently: a `Literal` missing a level the API supports is a level no
    # deployment can select, and nothing would say so except a configuration
    # that refused to load.
    Scenario() \
        .given(
            EVERY_EFFORT_THE_MODEL_OFFERS
        ) \
        .when(
            lambda: [
                ModelPolicy(effort=effort).effort
                for effort in EVERY_EFFORT_THE_MODEL_OFFERS
            ]
        ) \
        .then(
            _all_of_them_came_back(EVERY_EFFORT_THE_MODEL_OFFERS)
        )


def _it_asks_for(model: str, effort: Effort, max_output_tokens: int) -> Assertion[ModelPolicy]:
    """The three answers an unconfigured policy gives, checked together.

    Together rather than one at a time, because the claim is about the whole
    posture towards a deployment that named nothing: a field that quietly
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
                f"Expected a policy nobody configured to be unchanged, and {moved} "
                f"differed (expected, got)."
            )

        return True

    return assertion


def _room_enough_to_stay_under(ceiling: int) -> Assertion[int]:
    """That the default cap does not itself require streaming to send."""
    def assertion(room: int) -> bool:
        if room > ceiling:
            raise AssertionError(
                f"Expected the default room to stay under [{ceiling}], got [{room}]."
            )

        return True

    return assertion


def _all_of_them_came_back(expected: tuple[Effort, ...]) -> Assertion[list[Effort]]:
    """That every level offered was accepted, and came back as it was given.

    Came back rather than merely did not raise: a field that accepted a level
    and stored something else would satisfy "no error" and be wrong in the way
    that matters, since what is read afterwards is the stored value.
    """
    def assertion(accepted: list[Effort]) -> bool:
        if list(expected) != accepted:
            raise AssertionError(
                f"Expected every effort the model offers to come back as given, "
                f"asked for {list(expected)} and got {accepted}."
            )

        return True

    return assertion
