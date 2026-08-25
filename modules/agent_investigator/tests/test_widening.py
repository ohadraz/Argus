from __future__ import annotations

import pytest
from agent_investigator.widening import widening_schedule


@pytest.mark.unit
def test_the_schedule_has_one_lookback_per_iteration() -> None:
    dont_care_initial_minutes = 30
    dont_care_maximum_minutes = 180
    some_iteration_budget = 4

    schedule = widening_schedule(
        dont_care_initial_minutes, dont_care_maximum_minutes, some_iteration_budget
    )

    assert len(schedule) == some_iteration_budget


@pytest.mark.unit
def test_the_schedule_starts_at_the_initial_lookback_and_ends_at_the_maximum() -> None:
    some_initial_minutes = 30
    some_maximum_minutes = 180
    dont_care_iteration_budget = 3

    schedule = widening_schedule(
        some_initial_minutes, some_maximum_minutes, dont_care_iteration_budget
    )

    assert schedule[0] == some_initial_minutes
    assert schedule[-1] == some_maximum_minutes


@pytest.mark.unit
def test_every_step_of_the_schedule_reaches_strictly_further_back() -> None:
    # The structural trigger only makes sense if the next iteration can see
    # something the last one could not.
    dont_care_initial_minutes = 30
    dont_care_maximum_minutes = 180
    dont_care_iteration_budget = 5

    schedule = widening_schedule(
        dont_care_initial_minutes, dont_care_maximum_minutes, dont_care_iteration_budget
    )

    assert all(
        later > earlier for earlier, later in zip(schedule, schedule[1:], strict=False)
    )


@pytest.mark.unit
def test_the_schedule_still_ends_at_the_maximum_when_the_budget_changes() -> None:
    # The failure this replaces: doubling the lookback each iteration never
    # reached the ceiling under the default budget, so the "onset predates
    # everything retrievable" exhaustion condition was unreachable.
    dont_care_initial_minutes = 30
    some_maximum_minutes = 180
    some_small_iteration_budget = 2
    some_large_iteration_budget = 7

    shortest_schedule = widening_schedule(
        dont_care_initial_minutes, some_maximum_minutes, some_small_iteration_budget
    )
    longest_schedule = widening_schedule(
        dont_care_initial_minutes, some_maximum_minutes, some_large_iteration_budget
    )

    assert shortest_schedule[-1] == some_maximum_minutes
    assert longest_schedule[-1] == some_maximum_minutes


@pytest.mark.unit
def test_the_schedule_takes_small_steps_first_and_the_long_reach_last() -> None:
    # Geometric, not linear: causes cluster near the onset, so the early
    # iterations stay tight and the last one covers the rest.
    dont_care_initial_minutes = 30
    dont_care_maximum_minutes = 180
    dont_care_iteration_budget = 4

    schedule = widening_schedule(
        dont_care_initial_minutes, dont_care_maximum_minutes, dont_care_iteration_budget
    )

    steps = [
        later - earlier
        for earlier, later in zip(schedule, schedule[1:], strict=False)
    ]

    assert all(
        later_step > earlier_step
        for earlier_step, later_step in zip(steps, steps[1:], strict=False)
    )
