"""What a stored row is brought up to before it is read, and what a row that
cannot be read is said to be.

Every row holding a model's dump says which shape it was written in. A reader
brings an older one up to the shape its models have now, one step at a time,
before it validates anything - and a row written in a shape the reader does not
know was written by a newer Argus, and is said to be newer rather than guessed
at, because a reader that waits for the release that knows it loses nothing,
and one that passes over it loses the row.
"""

from __future__ import annotations

from typing import Any

import pytest
from argus_testkit import (
    Assertion,
    Scenario,
    an_error_was_raised,
    attempting,
    the_answer_was,
)
from core.stored import FIRST_SHAPE, NewerShape, Shapes, Unreadable, up_to_date

SOME_KIND = "some-kind"
ANOTHER_KIND = "another-kind"
SOME_ROW = {"said": "something"}


@pytest.mark.unit
def test_a_kind_with_no_upcasters_is_at_its_first_shape() -> None:
    Scenario() \
        .given(shapes := Shapes()) \
        .when(lambda: shapes.current(SOME_KIND)) \
        .then(the_answer_was(FIRST_SHAPE))


@pytest.mark.unit
def test_a_kind_is_one_shape_on_for_each_upcaster_it_has() -> None:
    # Each upcaster takes a row one shape on, from the first, so the shape a
    # kind is at now cannot disagree with the steps that reach it.
    some_steps = [_marking("first"), _marking("second")]

    Scenario() \
        .given(shapes := Shapes(upcasters={SOME_KIND: some_steps})) \
        .when(lambda: shapes.current(SOME_KIND)) \
        .then(the_answer_was(FIRST_SHAPE + len(some_steps)))


@pytest.mark.unit
def test_a_row_at_the_current_shape_is_read_as_it_was_written() -> None:
    after_its_one_step = FIRST_SHAPE + 1

    Scenario() \
        .given(shapes := Shapes(upcasters={SOME_KIND: [_marking("first")]})) \
        .when(lambda: up_to_date(SOME_KIND, after_its_one_step, SOME_ROW, shapes)) \
        .then(the_answer_was(SOME_ROW))


@pytest.mark.unit
def test_a_row_at_an_older_shape_is_brought_up_through_every_step_in_order() -> None:
    Scenario() \
        .given(shapes := Shapes(upcasters={SOME_KIND: [_marking("first"), _marking("second")]})) \
        .when(lambda: up_to_date(SOME_KIND, FIRST_SHAPE, SOME_ROW, shapes)) \
        .then(_it_was_brought_up_through(["first", "second"]))


@pytest.mark.unit
def test_a_row_part_of_the_way_up_is_brought_up_only_through_the_steps_after_it() -> None:
    after_the_first_step = FIRST_SHAPE + 1

    Scenario() \
        .given(shapes := Shapes(upcasters={SOME_KIND: [_marking("first"), _marking("second")]})) \
        .when(lambda: up_to_date(SOME_KIND, after_the_first_step, SOME_ROW, shapes)) \
        .then(_it_was_brought_up_through(["second"]))


@pytest.mark.unit
def test_one_kind_s_upcasters_are_not_run_on_another_kind() -> None:
    Scenario() \
        .given(shapes := Shapes(upcasters={SOME_KIND: [_marking("first")]})) \
        .when(lambda: up_to_date(ANOTHER_KIND, FIRST_SHAPE, SOME_ROW, shapes)) \
        .then(the_answer_was(SOME_ROW))


@pytest.mark.unit
def test_a_row_at_a_shape_the_reader_does_not_know_is_newer() -> None:
    # Written by a newer Argus. Not guessed at: a reader that reads it as the
    # shape it knows reads whatever the newer one moved into the wrong field.
    Scenario() \
        .given(shapes := Shapes(upcasters={SOME_KIND: [_marking("first")]})) \
        .when(attempting(lambda: up_to_date(SOME_KIND, shapes.current(SOME_KIND) + 1,
                                            SOME_ROW, shapes))) \
        .then(an_error_was_raised(NewerShape))


@pytest.mark.unit
@pytest.mark.parametrize("shape", [FIRST_SHAPE - 1, FIRST_SHAPE - 2])
def test_a_shape_below_the_first_is_no_shape(shape: int) -> None:
    Scenario() \
        .when(attempting(lambda: up_to_date(SOME_KIND, shape, SOME_ROW, Shapes()))) \
        .then(an_error_was_raised(ValueError))


@pytest.mark.unit
def test_the_shapes_a_reader_is_given_by_default_are_the_shipped_ones() -> None:
    # Every kind starts at its first shape: no upcaster ships yet.
    Scenario() \
        .when(lambda: up_to_date(SOME_KIND, FIRST_SHAPE, SOME_ROW)) \
        .then(the_answer_was(SOME_ROW))


@pytest.mark.unit
def test_a_row_newer_than_its_reader_is_unreadable_as_newer() -> None:
    some_newer = NewerShape("shape 3 of [some-kind], and this reader knows up to 2")

    Scenario() \
        .when(lambda: Unreadable.of(some_newer)) \
        .then(the_answer_was(Unreadable(why=str(some_newer), newer=True)))


@pytest.mark.unit
def test_a_row_that_could_not_be_brought_up_is_unreadable_and_not_newer() -> None:
    # Said why in the failure's own words.
    some_failure = ValueError("the field [said] is missing")

    Scenario() \
        .when(lambda: Unreadable.of(some_failure)) \
        .then(the_answer_was(Unreadable(why=str(some_failure), newer=False)))


def _marking(step: str) -> Any:
    """An upcaster that adds `step` to the steps the row went through."""
    def upcast(raw: Any) -> Any:
        return {**raw, "steps": [*raw.get("steps", []), step]}

    return upcast


def _it_was_brought_up_through(expected: list[str]) -> Assertion[Any]:
    def assertion(raw: Any) -> bool:
        if raw.get("steps") != expected:
            raise AssertionError(f"Expected the row brought up through {expected}, in that "
                                 f"order, and it was brought up through {raw.get('steps')}.")

        return True

    return assertion
