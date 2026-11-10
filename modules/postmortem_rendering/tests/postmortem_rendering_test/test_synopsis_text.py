"""The synopsis in words: each part under its heading, in the order the
synopsis reads, as the lines it is said in - worded once for whatever prints it.
"""

from __future__ import annotations

from typing import Any

import pytest
from argus_testkit import Assertion, Scenario
from postmortem_rendering.synopsis_text import the_parts

from postmortem_rendering_test.framework.synopses import (
    A_DURATION_CARD,
    A_LOSS_CARD,
    A_TOTAL_ROW,
    SOME_HEADINGS,
    SOME_NOTES,
    TWO_ROWS,
    a_synopsis_read,
)


@pytest.mark.unit
def test_every_part_is_said_under_its_heading_in_the_order_the_synopsis_reads() -> None:
    Scenario() \
        .when(
            lambda: [part.heading for part in the_parts(a_synopsis_read())]
        ) \
        .then(
            _they_are([SOME_HEADINGS["overview"], SOME_HEADINGS["when"],
                       SOME_HEADINGS["impact"], SOME_HEADINGS["resolution"],
                       SOME_HEADINGS["human-cost"]])
        )


@pytest.mark.unit
def test_the_resolution_alone_is_said_as_a_list() -> None:
    # Steps taken one after another; every other part is lines read in turn.
    Scenario() \
        .when(
            lambda: {part.heading: part.listed for part in the_parts(a_synopsis_read())}
        ) \
        .then(
            _they_are({SOME_HEADINGS["overview"]: False, SOME_HEADINGS["when"]: False,
                       SOME_HEADINGS["impact"]: False, SOME_HEADINGS["resolution"]: True,
                       SOME_HEADINGS["human-cost"]: False})
        )


@pytest.mark.unit
def test_each_title_says_its_people_minutes_and_cost_with_its_range_then_the_total() -> None:
    a_row_of_two, a_row_of_one = TWO_ROWS

    Scenario() \
        .when(
            lambda: _the_lines_under(SOME_HEADINGS["human-cost"])
        ) \
        .then(
            _they_are([f"{a_row_of_two.title}: {a_row_of_two.people} people, "
                       f"{a_row_of_two.minutes}, {a_row_of_two.midpoint} ({a_row_of_two.range})",
                       f"{a_row_of_one.title}: {a_row_of_one.people} person, "
                       f"{a_row_of_one.minutes}, {a_row_of_one.midpoint} ({a_row_of_one.range})",
                       f"{A_TOTAL_ROW.title}: {A_TOTAL_ROW.people} people, "
                       f"{A_TOTAL_ROW.minutes}, {A_TOTAL_ROW.midpoint} ({A_TOTAL_ROW.range})",
                       *SOME_NOTES])
        )


@pytest.mark.unit
def test_a_figure_is_said_before_what_it_is() -> None:
    Scenario() \
        .when(
            lambda: _the_lines_under(SOME_HEADINGS["impact"])
        ) \
        .then(
            _they_are([f"{A_DURATION_CARD.value} - {A_DURATION_CARD.label}",
                       f"{A_LOSS_CARD.value} - {A_LOSS_CARD.label}"])
        )


def _the_lines_under(heading: str) -> list[str]:
    return next(list(part.lines) for part in the_parts(a_synopsis_read())
                if part.heading == heading)


def _they_are(expected: Any) -> Assertion[Any]:
    def assertion(said: Any) -> bool:
        if said != expected:
            raise AssertionError(f"Expected {expected}, got {said}.")

        return True

    return assertion
