"""A day said as narration says one beside a time: the day of the month and
the month, "20 Oct".

The kernel's, because two parties have to agree on it: narration writes it, and
the postmortem's reader of figures has to know one when it meets it. Read word by
word, "20 Oct 20:31" is the figure "20", a word and a time, and the brief offered
the day of the month to the model as a number the incident gave.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from argus_core import A_DAY_SAID, said_as_a_day
from argus_testkit import Assertion, Scenario, the_answer_was


@pytest.mark.unit
def test_a_day_is_said_as_the_day_of_the_month_and_the_month() -> None:
    Scenario() \
        .when(
            lambda: said_as_a_day(datetime(2026, 10, 20, 20, 31, 54, tzinfo=UTC))
        ) \
        .then(
            the_answer_was("20 Oct")
        )


@pytest.mark.unit
def test_a_day_early_in_the_month_is_said_in_two_digits() -> None:
    # As every day narration has said: "05 Sep", which is what a reader of it
    # has to recognise.
    Scenario() \
        .when(
            lambda: said_as_a_day(datetime(2026, 9, 5, 10, 13, tzinfo=UTC))
        ) \
        .then(
            the_answer_was("05 Sep")
        )


@pytest.mark.unit
@pytest.mark.parametrize("month", range(1, 13))
def test_every_day_said_is_recognised_as_one(month: int) -> None:
    # Whatever narration writes, the reader knows it - in every month, so a
    # spelling and a pattern kept apart cannot drift for one of them.
    some_day = datetime(2026, month, 28, tzinfo=UTC)

    Scenario() \
        .when(
            lambda: said_as_a_day(some_day)
        ) \
        .then(
            _it_is_a_day_said()
        )


@pytest.mark.unit
def test_a_count_of_something_is_not_a_day_said() -> None:
    # A number beside a word is a figure of the incident's, and taken for a day
    # it would be one the model could no longer name.
    Scenario() \
        .when(
            lambda: A_DAY_SAID.search("pool exhausted at 20 connections")
        ) \
        .then(
            the_answer_was(None)
        )


def _it_is_a_day_said() -> Assertion[str]:
    def assertion(said: str) -> bool:
        if not A_DAY_SAID.fullmatch(said):
            raise AssertionError(f"Expected [{said}] to be recognised as a day said, it was not.")

        return True

    return assertion
