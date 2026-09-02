from __future__ import annotations

from collections.abc import Callable

import pytest
from agent_investigator.budget import Bound, Budget
from argus_core.models.turn import ToolCall, Turn
from argus_testkit import Assertion, Scenario

"""What stops an investigation that the model would happily continue.

The loop hands the model tools and lets it decide what to read; this is the
half that decides when it has to stop. Three bounds, checked between turns,
because they fail differently and none of them implies the others - a model
reading three-hour windows is cheap in calls and ruinous in tokens, and one
looping on a narrow window is the reverse.

Nothing here asks the model anything. A bound the model could be persuaded to
respect is not a bound, so every one of these is arithmetic the loop does on
its own.
"""


@pytest.mark.unit
def test_an_investigation_that_has_done_nothing_has_reached_no_bound() -> None:
    # The state every investigation opens in. A budget that reported a bound
    # before the first turn would end every investigation before it started.
    Scenario() \
        .given(
            some_budget := _a_budget()
        ) \
        .when(
            lambda: some_budget
        ) \
        .then(
            _no_bound_was_reached()
        )


@pytest.mark.unit
def test_a_turn_inside_every_bound_reaches_none_of_them() -> None:
    # The ordinary case, and the one worth stating: recording a turn is not
    # itself what ends an investigation.
    some_generous_token_bound = 10_000
    some_generous_tool_call_bound = 10
    a_turn_well_inside_them = some_generous_token_bound // 100

    Scenario() \
        .given(
            some_budget := _a_budget(max_tool_calls=some_generous_tool_call_bound,
                                    max_tokens=some_generous_token_bound),
            lambda: some_budget.record(
                _a_turn_asking_for(1, costing_each_way=a_turn_well_inside_them))
        ) \
        .when(
            lambda: some_budget
        ) \
        .then(
            _no_bound_was_reached()
        )


@pytest.mark.unit
def test_tool_calls_are_counted_across_turns() -> None:
    # Across, not within. A model that asks for two channels a turn reaches a
    # three-call bound on its second turn, and a budget counting turns rather
    # than calls would let it read twice what it was allowed.
    some_tool_call_bound = 3
    some_slightly_below_bound_calls_a_turn = some_tool_call_bound - 1

    Scenario() \
        .given(
            some_budget := _a_budget(max_tool_calls=some_tool_call_bound),
            lambda: some_budget.record(
                _a_turn_asking_for(some_slightly_below_bound_calls_a_turn)),
            lambda: some_budget.record(
                _a_turn_asking_for(some_slightly_below_bound_calls_a_turn))
        ) \
        .when(
            lambda: some_budget
        ) \
        .then(
            _the_bounds_reached_were(Bound.TOOL_CALLS)
        )


@pytest.mark.unit
def test_tokens_are_counted_across_turns() -> None:
    # The bound a wide window blows through while the call count still looks
    # healthy. Both directions count: what the model was sent is most of the
    # spend, because every turn resends the whole transcript.
    some_token_bound = 500
    # Both directions are counted, so a turn costs twice this. One turn stays
    # inside the bound and two pass it - which is what makes this a test of
    # accumulation rather than of a single expensive turn.
    some_turn_costing_less_than_the_bound = some_token_bound // 4 + 10
    a_turn_the_bound_allows = _a_turn_asking_for(
        1, costing_each_way=some_turn_costing_less_than_the_bound
    )

    Scenario() \
        .given(
            some_budget := _a_budget(max_tokens=some_token_bound),
            lambda: some_budget.record(a_turn_the_bound_allows),
            lambda: some_budget.record(a_turn_the_bound_allows)
        ) \
        .when(
            lambda: some_budget
        ) \
        .then(
            _the_bounds_reached_were(Bound.TOKENS)
        )


@pytest.mark.unit
def test_time_runs_out_even_when_nothing_has_been_spent() -> None:
    # The bound that has nothing to do with what the model did. An incident
    # has a human waiting on it, and an investigation that is cheap and slow
    # has still failed them.
    some_time_bound_seconds = 60.0
    a_clock = a_clock_that_reads(0.0)

    Scenario() \
        .given(
            some_budget := _a_budget(max_seconds=some_time_bound_seconds, now=a_clock),
            lambda: a_clock.moves_to(some_time_bound_seconds)
        ) \
        .when(
            lambda: some_budget
        ) \
        .then(
            _the_bounds_reached_were(Bound.TIME)
        )


@pytest.mark.unit
def test_the_last_turn_is_known_before_the_bound_binds() -> None:
    # So the model can be told. A turn's warning is what lets it spend its
    # last one answering instead of reading - and the loop can only warn if it
    # can see the bound coming rather than only having hit it.
    some_tool_call_bound = 3

    Scenario() \
        .given(
            some_budget := _a_budget(max_tool_calls=some_tool_call_bound),
            lambda: some_budget.record(_a_turn_asking_for(some_tool_call_bound - 1))
        ) \
        .when(
            lambda: some_budget
        ) \
        .then(
            _it_is_the_last_turn_available()
        )


@pytest.mark.unit
def test_a_budget_with_room_to_spare_is_not_on_its_last_turn() -> None:
    # The other side of the same question, and the one that would break
    # quietly: a loop warning every turn teaches the model to ignore warnings.
    some_tool_call_bound = 10

    Scenario() \
        .given(
            some_budget := _a_budget(max_tool_calls=some_tool_call_bound),
            lambda: some_budget.record(_a_turn_asking_for(1))
        ) \
        .when(
            lambda: some_budget
        ) \
        .then(
            _it_is_not_the_last_turn_available()
        )


def _no_bound_was_reached() -> Assertion[Budget]:
    """An investigation the loop may carry on with - nothing has run out."""
    def assertion(budget: Budget) -> bool:
        reached = budget.bounds_reached()
        if reached:
            raise AssertionError(f"Expected no bound to be reached, got {reached}.")

        return True

    return assertion


def _the_bounds_reached_were(*bounds: Bound) -> Assertion[Budget]:
    """Every bound that ran out, not the first one noticed.

    All of them, because the escalation summary names them to a human and two
    bounds running together is a different account of the incident than one.
    Reporting a single winner would also make the answer depend on the order
    the checks happen to be written in, which is not a fact about the
    investigation.
    """
    def assertion(budget: Budget) -> bool:
        reached = budget.bounds_reached()
        if reached != list(bounds):
            raise AssertionError(
                f"Expected the bounds {list(bounds)} to be reached, got {reached}."
            )

        return True

    return assertion


def _it_is_the_last_turn_available() -> Assertion[Budget]:
    def assertion(budget: Budget) -> bool:
        if not budget.is_on_its_last_turn():
            raise AssertionError("Expected the budget to be on its last turn, and it was not.")

        return True

    return assertion


def _it_is_not_the_last_turn_available() -> Assertion[Budget]:
    def assertion(budget: Budget) -> bool:
        if budget.is_on_its_last_turn():
            raise AssertionError("Expected the budget to have room to spare, and it did not.")

        return True

    return assertion


class a_clock_that_reads:
    """A clock a test moves by hand.

    A real one cannot be made to run out inside a unit test without the test
    sleeping for the bound it is checking. Injected as a plain callable, so
    the production default is `time.monotonic` and nothing is patched.
    """

    def __init__(self, seconds: float) -> None:
        self.seconds = seconds

    def __call__(self) -> float:
        return self.seconds

    def moves_to(self, seconds: float) -> None:
        self.seconds = seconds


def _a_budget(max_tool_calls: int = 100,
             max_tokens: int = 1_000_000,
             max_seconds: float = 3600.0,
             now: Callable[[], float] | None = None) -> Budget:
    """A budget whose unnamed bounds are far enough away to stay out of the way.

    Each test names the one bound it is about, so the others must not reach
    first - a default that happened to bind would make the test pass for the
    wrong reason.
    """
    return Budget(
        max_tool_calls=max_tool_calls,
        max_tokens=max_tokens,
        max_seconds=max_seconds,
        now=now if now is not None else a_clock_that_reads(0.0)
    )


def _a_turn_asking_for(calls: int, costing_each_way: int = 1) -> Turn:
    """A turn requesting `calls` tools, charged `costing_each_way` in and out.

    Named for both directions because a turn is billed twice: what the model
    was sent, and what it wrote. A parameter called `costing` would say a turn
    costs half what it does.
    """
    dont_care_what_it_said = "dont care what it said"

    return Turn(
        text=dont_care_what_it_said,
        tool_calls=[
            ToolCall(id=f"toolu_{position}", name="get_logs", arguments={})
            for position in range(calls)
        ],
        input_tokens=costing_each_way,
        output_tokens=costing_each_way
    )
