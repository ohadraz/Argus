"""Which step of the walk the writes being made belong to.

Bound by the walk around each node and read by the repositories that stamp a
row with it. What it has to promise is narrow: the step is there for exactly
as long as the block runs, however the block ends, and a step bound inside
another gives the outer one back - a step that leaked past its node would
stamp the next node's rows, and a second attempt at that node would take them
back.
"""

from __future__ import annotations

from contextlib import suppress

import pytest
from argus_testkit import (
    Scenario,
    attempting,
    the_answer_was,
    the_same_error_reached_the_caller,
)
from incident_record import the_current_step, within_step

SOME_STEP = 7
SOME_OTHER_STEP = SOME_STEP + 1
# What a node's failure says: the one a caller is shown it reached them with,
# and the one a caller dealt with, whose words nothing reads.
SOME_FAILURE_WORDS = "the read tier did not answer"
DONT_CARE_FAILURE_WORDS = "a failure already dealt with"


class _SomeFailure(Exception):
    """What a node raised, standing in for whatever a real one does."""


@pytest.mark.unit
def test_a_step_is_the_current_one_while_its_block_runs() -> None:
    Scenario() \
        .when(lambda: _the_step_read_within(SOME_STEP)) \
        .then(the_answer_was(SOME_STEP))


@pytest.mark.unit
def test_there_is_no_current_step_outside_any_block() -> None:
    # Intake, a person's ending and the worker's own escalation write here: rows
    # that belong to no step, and that no step run again takes back.
    Scenario() \
        .when(the_current_step) \
        .then(the_answer_was(None))


@pytest.mark.unit
def test_a_step_is_no_longer_current_once_its_block_has_ended() -> None:
    Scenario() \
        .given(_the_step_read_within(SOME_STEP)) \
        .when(the_current_step) \
        .then(the_answer_was(None))


@pytest.mark.unit
def test_a_step_is_no_longer_current_once_its_block_has_raised() -> None:
    # A node that fails is the case this exists for: the next node runs on the
    # same thread, and a step left bound would stamp its rows as the failed one's.
    Scenario() \
        .given(_a_block_that_raised_within(SOME_STEP)) \
        .when(the_current_step) \
        .then(the_answer_was(None))


@pytest.mark.unit
def test_what_a_block_raised_reaches_its_caller_as_it_was() -> None:
    some_failure = _SomeFailure(SOME_FAILURE_WORDS)

    Scenario() \
        .when(attempting(lambda: _raising_within(SOME_STEP, some_failure))) \
        .then(the_same_error_reached_the_caller(some_failure))


@pytest.mark.unit
def test_a_step_bound_inside_another_gives_the_outer_one_back() -> None:
    Scenario() \
        .when(lambda: _the_step_read_after_a_nested_one(SOME_STEP, SOME_OTHER_STEP)) \
        .then(the_answer_was(SOME_STEP))


def _the_step_read_within(step: int) -> int | None:
    with within_step(step):
        return the_current_step()


def _raising_within(step: int, failure: Exception) -> None:
    with within_step(step):
        raise failure


def _a_block_that_raised_within(step: int) -> _SomeFailure:
    """A block that raised, and whose failure its caller has already dealt
    with - so what is left to look at is whether the step went with it. The
    failure it dealt with is what it answers."""
    dealt_with = _SomeFailure(DONT_CARE_FAILURE_WORDS)

    with suppress(_SomeFailure):
        _raising_within(step, dealt_with)

    return dealt_with


def _the_step_read_after_a_nested_one(outer: int, inner: int) -> int | None:
    with within_step(outer):
        with within_step(inner):
            pass

        return the_current_step()
