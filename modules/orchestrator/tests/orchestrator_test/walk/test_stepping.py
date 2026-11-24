"""Every node run as a numbered step of the walk.

The wrapper every node is registered through, for the reason `traced` is one:
a property all of them must have is one none of them can be trusted to
remember. What it gives a node is its step's number, bound for as long as it
runs, which every row it writes is stamped with; what it gives the walk is one
step more, counted in the state the checkpoint carries.

The nodes here are stand-ins that report the step they could see while they
ran. That is the whole of what the wrapper promises a node.
"""

from __future__ import annotations

from typing import Any

import pytest
from argus_testkit import (
    Assertion,
    Scenario,
    all_of,
    attempting,
    the_answer_was,
    the_same_error_reached_the_caller,
)
from core.models import Alert, IncidentStatus
from incident_record import the_current_step
from orchestrator.walk.deltas import StateDelta
from orchestrator.walk.state import IncidentState
from orchestrator.walk.stepping import stepped

from orchestrator_test.framework.builders import an_incident_state

DONT_CARE_ALERT = Alert(service="kuki", alert_name="HighErrorRate")
# How many steps the walk took before the one under test.
SOME_STEPS_TAKEN = 6
SOME_CANDIDATE_INDEX = 2
STEP_SEEN = "step_seen"


@pytest.mark.unit
def test_a_node_runs_inside_the_step_the_walk_has_reached() -> None:
    # Numbered by the steps taken before it, which is what a step run again
    # from its checkpoint reads as its interrupted attempt read it.
    Scenario() \
        .given(a_walk_some_steps_in := _a_state_after(SOME_STEPS_TAKEN)) \
        .when(lambda: stepped(_a_node_reading_its_step)(a_walk_some_steps_in)) \
        .then(_the_node_saw_step(SOME_STEPS_TAKEN))


@pytest.mark.unit
def test_no_step_is_bound_once_the_node_has_returned() -> None:
    # What a write made between steps - the worker escalating a walk that
    # stopped - belongs to no step, and no step run again takes it back.
    Scenario() \
        .given(a_walk_some_steps_in := _a_state_after(SOME_STEPS_TAKEN)) \
        .when(lambda: stepped(_a_node_reading_its_step)(a_walk_some_steps_in)) \
        .then(_no_step_is_bound())


@pytest.mark.unit
def test_no_step_is_bound_once_the_node_has_raised() -> None:
    some_failure = RuntimeError("the model was unavailable")

    Scenario() \
        .given(
            a_failing_step := stepped(_a_node_raising(some_failure))
        ) \
        .when(attempting(lambda: a_failing_step(_a_state_after(SOME_STEPS_TAKEN)))) \
        .then(all_of(
            the_same_error_reached_the_caller(some_failure),
            _no_step_is_bound()
        ))


@pytest.mark.unit
def test_a_mapping_a_node_returned_carries_one_step_more() -> None:
    # A node `with_status` wraps, which hands back the mapping LangGraph merges.
    Scenario() \
        .given(
            a_node_returning_a_mapping := _a_node_returning(
                {"candidate_index": SOME_CANDIDATE_INDEX})
        ) \
        .when(lambda: stepped(a_node_returning_a_mapping)(_a_state_after(SOME_STEPS_TAKEN))) \
        .then(the_answer_was({"candidate_index": SOME_CANDIDATE_INDEX,
                              "steps": SOME_STEPS_TAKEN + 1}))


@pytest.mark.unit
def test_a_delta_a_node_returned_is_merged_as_what_it_set_with_one_step_more() -> None:
    # The two nodes `with_status` does not wrap, whose delta reaches LangGraph
    # only through here - as the fields it set, and nothing else.
    Scenario() \
        .given(
            a_node_returning_a_delta := _a_node_returning(
                StateDelta(candidate_index=SOME_CANDIDATE_INDEX))
        ) \
        .when(lambda: stepped(a_node_returning_a_delta)(_a_state_after(SOME_STEPS_TAKEN))) \
        .then(the_answer_was({"candidate_index": SOME_CANDIDATE_INDEX,
                              "steps": SOME_STEPS_TAKEN + 1}))


def _a_state_after(steps: int) -> IncidentState:
    return an_incident_state(DONT_CARE_ALERT, IncidentStatus.INVESTIGATING) \
        .model_copy(update={"steps": steps})


def _a_node_reading_its_step(dont_care_state: IncidentState) -> dict[str, Any]:
    return {STEP_SEEN: the_current_step()}


def _a_node_returning(result: dict[str, Any] | StateDelta) -> Any:
    def node(dont_care_state: IncidentState) -> dict[str, Any] | StateDelta:
        return result

    return node


def _a_node_raising(failure: Exception) -> Any:
    def node(dont_care_state: IncidentState) -> dict[str, Any]:
        raise failure

    return node


def _the_node_saw_step(expected: int) -> Assertion[dict[str, Any]]:
    def assertion(updates: dict[str, Any]) -> bool:
        seen = updates.get(STEP_SEEN)

        if seen != expected:
            raise AssertionError(
                f"Expected the node to run inside step [{expected}], it saw [{seen}]."
            )

        return True

    return assertion


def _no_step_is_bound() -> Assertion[Any]:
    def assertion(dont_care_result: Any) -> bool:
        bound = the_current_step()

        if bound is not None:
            raise AssertionError(
                f"Expected no step bound once the node was done, step [{bound}] still was."
            )

        return True

    return assertion
