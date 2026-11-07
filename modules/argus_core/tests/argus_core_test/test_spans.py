"""A span of time said as a person says it: days, hours, minutes and seconds,
naming only the units it has.

One rule in one place, because the postmortem's figures and narration's windows
each say how long something lasted, and a span said two ways on one page - "1446
minutes" in one line and "1 day 6 minutes" in the next - is two figures to a
reader comparing them.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from argus_core import said_as_a_span
from argus_testkit import Scenario, the_answer_was


@pytest.mark.unit
@pytest.mark.parametrize(("span", "said"), [
    (timedelta(days=1, minutes=6), "1 day 6 minutes"),
    (timedelta(hours=24), "1 day"),
    (timedelta(hours=2, seconds=1), "2 hours 1 second"),
    (timedelta(minutes=36), "36 minutes"),
    (timedelta(days=3, hours=1, minutes=2, seconds=5), "3 days 1 hour 2 minutes 5 seconds")
], ids=["a-day-and-minutes", "a-day", "hours-and-a-second", "minutes", "every-unit"])
def test_a_span_is_said_in_the_units_it_has_and_only_those(span: timedelta, said: str) -> None:
    # "1446 minutes" is a number a reader has to convert before it means
    # anything, and "1 day 0 hours 6 minutes" names a unit that holds nothing.
    Scenario() \
        .when(
            lambda: said_as_a_span(span)
        ) \
        .then(
            the_answer_was(said)
        )


@pytest.mark.unit
def test_a_span_is_said_exactly_to_the_second() -> None:
    # What a model is handed is the measurement, not a rounding of it: a span a
    # second short of an hour is not an hour.
    Scenario() \
        .when(
            lambda: said_as_a_span(timedelta(minutes=59, seconds=59))
        ) \
        .then(
            the_answer_was("59 minutes 59 seconds")
        )


@pytest.mark.unit
def test_a_span_shorter_than_a_second_is_said_as_that() -> None:
    # Said as nothing at all, the sentence carrying it would end where its
    # figure should be.
    Scenario() \
        .when(
            lambda: said_as_a_span(timedelta(milliseconds=400))
        ) \
        .then(
            the_answer_was("less than a second")
        )
