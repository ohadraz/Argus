"""A day said as narration says one beside a time: the month and the day of
the month, "Oct 20" - as the rest of the page says one.

The kernel's, because two parties have to agree on it: narration writes it, and
the postmortem's reader of figures has to know one when it meets it. Read word by
word, "Oct 20 20:31" is a word, the figure "20" and a time, and the brief offered
the day of the month to the model as a number the incident gave.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from argus_core import A_DAY_SAID, said_as_a_day, said_as_a_time, the_day_said
from argus_testkit import Assertion, Scenario, the_answer_was


@pytest.mark.unit
def test_a_day_is_said_as_the_month_and_the_day_of_the_month() -> None:
    Scenario() \
        .when(
            lambda: said_as_a_day(datetime(2026, 10, 20, 20, 31, 54, tzinfo=UTC))
        ) \
        .then(
            the_answer_was("Oct 20")
        )


@pytest.mark.unit
def test_a_day_early_in_the_month_is_said_in_two_digits() -> None:
    # As every day the page has said: "Sep 05", which is what a reader of it
    # has to recognise.
    Scenario() \
        .when(
            lambda: said_as_a_day(datetime(2026, 9, 5, 10, 13, tzinfo=UTC))
        ) \
        .then(
            the_answer_was("Sep 05")
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


@pytest.mark.unit
def test_a_time_with_no_seconds_is_said_to_the_minute() -> None:
    # "20:31:00" claims a precision nothing measured.
    Scenario() \
        .when(
            lambda: said_as_a_time(datetime(2026, 10, 20, 20, 31, tzinfo=UTC))
        ) \
        .then(
            the_answer_was("20:31")
        )


@pytest.mark.unit
def test_a_time_with_seconds_is_said_to_the_second() -> None:
    # Cut to its minute, a moment beside a span read a minute out: "fired at
    # 19:12 UTC, 5m 55s later", where the timeline said 19:12:55.
    Scenario() \
        .when(
            lambda: said_as_a_time(datetime(2026, 10, 20, 20, 31, 54, tzinfo=UTC))
        ) \
        .then(
            the_answer_was("20:31:54")
        )


@pytest.mark.unit
@pytest.mark.parametrize(("said", "near", "named"), [
    ("Oct 20", date(2026, 10, 25), date(2026, 10, 20)),
    ("Dec 30", date(2027, 1, 2), date(2026, 12, 30)),
    ("Feb 29", date(2028, 3, 1), date(2028, 2, 29)),
    ("Feb 29", date(2026, 3, 1), None),
    ("20 connections", date(2026, 10, 25), None)
], ids=["in-the-year-near", "in-the-year-before", "feb-29-in-a-leap-year-near",
        "feb-29-with-no-leap-year-near", "no-day-said"])
def test_a_day_said_is_read_back_in_the_year_nearest_the_day_it_is_said_near(
        said: str, near: date, named: date | None) -> None:
    # A day said carries no year, and nothing Argus says names a day a year
    # from the incident it is about.
    Scenario() \
        .when(
            lambda: the_day_said(said, near)
        ) \
        .then(
            the_answer_was(named)
        )


def _it_is_a_day_said() -> Assertion[str]:
    def assertion(said: str) -> bool:
        if not A_DAY_SAID.fullmatch(said):
            raise AssertionError(f"Expected [{said}] to be recognised as a day said, it was not.")

        return True

    return assertion
