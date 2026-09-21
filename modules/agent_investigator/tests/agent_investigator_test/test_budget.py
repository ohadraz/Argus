"""What one investigation may spend, read off what this deployment configured.

The arithmetic is the kernel's and is tested there. What is left here is the
mapping, which sounds too small to be worth a test and is exactly the shape of
thing that fails silently: three numbers going into three parameters of the
same types, in a module whose counterpart in Code-Fix does the same job over
fields with different names. Swap two and everything still builds, every type
checks, and an investigation runs to a bound nobody chose.

The failure has no symptom of its own, either. A budget handed the time bound
as its token bound does not raise - it stops early, or late, and reports
having run out of something, which reads exactly like a deployment that
configured a number badly.
"""

from __future__ import annotations

import pytest
from agent_investigator.budget import Bound, a_budget_for
from argus_core.budget import Budget
from argus_core.models import ToolCall, Turn
from argus_testkit import Assertion, Scenario

from agent_investigator_test.framework.builders.configuration import (
    some_investigation_settings,
)


@pytest.mark.unit
def test_the_call_bound_is_the_one_this_deployment_configured() -> None:
    # Each of the three is asserted on its own, because the failure being
    # guarded is a crossed wire rather than a missing one: a budget built
    # from all three settings in the wrong order satisfies any assertion
    # that only asks whether some bound binds eventually.
    some_call_bound = 2

    Scenario() \
        .given(
            budget := a_budget_for(
                some_investigation_settings(tool_calls=some_call_bound)
            )
        ) \
        .when(
            lambda: _having_charged(budget, _a_turn_costing(calls=some_call_bound))
        ) \
        .then(
            _the_bounds_reached_were(Bound.TOOL_CALLS)
        )


@pytest.mark.unit
def test_the_token_bound_is_the_one_this_deployment_configured() -> None:
    some_token_bound = 500

    Scenario() \
        .given(
            budget := a_budget_for(
                some_investigation_settings(tokens=some_token_bound)
            )
        ) \
        .when(
            lambda: _having_charged(budget, _a_turn_costing(tokens=some_token_bound))
        ) \
        .then(
            _the_bounds_reached_were(Bound.TOKENS)
        )


@pytest.mark.unit
def test_the_time_bound_is_the_one_this_deployment_configured() -> None:
    # The one no amount of spending reaches, which is what makes it the
    # easiest of the three to wire to the wrong field and never notice: a
    # time bound fed a token count runs for as many seconds as the model was
    # allowed tokens, and nothing about that looks wrong until an incident
    # has sat for an afternoon.
    no_time_at_all = 0.0

    Scenario() \
        .given(
            budget := a_budget_for(
                some_investigation_settings(seconds=no_time_at_all)
            )
        ) \
        .when(
            lambda: budget
        ) \
        .then(
            _the_bounds_reached_were(Bound.TIME)
        )


def _having_charged(budget: Budget, turn: Turn) -> Budget:
    """The budget, with one turn already spent against it.

    A `when` that does the spending rather than a `given` that does, because
    charging is the act under test here: what is being asked is which bound a
    figure was wired to, and that is only visible once something has been
    spent against it.
    """
    budget.record(turn)

    return budget


def _a_turn_costing(calls: int = 0, tokens: int = 0) -> Turn:
    """A turn that spends against exactly one axis.

    Nothing on the axes a test did not name, so a bound reporting itself
    reached is one this turn actually spent against.
    """
    return Turn(
        text="dont care what it said",
        tool_calls=[
            ToolCall(id=f"toolu_{position}", name="get_logs", arguments={})
            for position in range(calls)
        ],
        input_tokens=tokens,
        output_tokens=0
    )


def _the_bounds_reached_were(*bounds: Bound) -> Assertion[Budget]:
    """Exactly these bounds, and no others.

    Exactly, because a crossed wire shows up as the wrong bound rather than
    as no bound: a test satisfied by "at least the one I named" would pass on
    a budget that had reached all three.
    """
    def assertion(budget: Budget) -> bool:
        reached = budget.bounds_reached()

        if reached != list(bounds):
            raise AssertionError(
                f"Expected the bounds {list(bounds)} to be reached, got {reached}."
            )

        return True

    return assertion
