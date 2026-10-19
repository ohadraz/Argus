"""How a stored value is written for a reader.

Formatting belongs to whatever shows the value, never to what stores it: the
document keeps every amount at the precision it was computed to, and only what
shows it rounds. Each case is one value and the words it must come out as.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from argus_testkit import Scenario, the_answer_was
from postmortem_rendering.formatting import as_money, as_revision, as_span, in_utc, on_the_clock


@pytest.mark.unit
def test_money_is_shown_to_two_places_with_its_thousands_grouped() -> None:
    Scenario() \
        .given(
            some_loss := Decimal("1736.68485900091116011163646")
        ) \
        .when(
            lambda: as_money(some_loss)
        ) \
        .then(
            the_answer_was("1,736.68")
        )


@pytest.mark.unit
def test_half_a_cent_rounds_up() -> None:
    # As a till rounds, not as a statistician does: a reader checking the
    # figure by hand rounds half up, and a page rounding half to even would
    # disagree with them whenever the cent below is even.
    Scenario() \
        .given(
            some_amount := Decimal("0.125")
        ) \
        .when(
            lambda: as_money(some_amount)
        ) \
        .then(
            the_answer_was("0.13")
        )


@pytest.mark.unit
def test_a_whole_amount_still_shows_its_cents() -> None:
    Scenario() \
        .given(
            some_amount := Decimal("500")
        ) \
        .when(
            lambda: as_money(some_amount)
        ) \
        .then(
            the_answer_was("500.00")
        )


@pytest.mark.unit
def test_a_span_under_an_hour_is_minutes_and_seconds() -> None:
    Scenario() \
        .given(
            some_gap := timedelta(minutes=2, seconds=40)
        ) \
        .when(
            lambda: as_span(some_gap)
        ) \
        .then(
            the_answer_was("2m 40s")
        )


@pytest.mark.unit
def test_a_span_of_hours_names_every_unit_below_the_first() -> None:
    # A zero in the middle is said, so the units line up with what a reader
    # expects to find in each place.
    Scenario() \
        .given(
            some_duration := timedelta(hours=1, seconds=5)
        ) \
        .when(
            lambda: as_span(some_duration)
        ) \
        .then(
            the_answer_was("1h 0m 5s")
        )


@pytest.mark.unit
def test_a_span_of_days_names_every_unit_down_to_the_second() -> None:
    # Hours roll over into days as seconds roll into minutes; nothing below
    # the largest unit is dropped, however long the span.
    Scenario() \
        .given(
            some_duration := timedelta(days=7, minutes=3, seconds=5)
        ) \
        .when(
            lambda: as_span(some_duration)
        ) \
        .then(
            the_answer_was("7d 0h 3m 5s")
        )


@pytest.mark.unit
def test_a_span_under_a_minute_is_seconds() -> None:
    Scenario() \
        .given(
            some_gap := timedelta(seconds=45)
        ) \
        .when(
            lambda: as_span(some_gap)
        ) \
        .then(
            the_answer_was("45s")
        )


@pytest.mark.unit
def test_a_span_is_cut_to_the_whole_seconds_that_have_passed() -> None:
    # Cut, not rounded, as the prose's own figure is: the same span written
    # once on a tile and once in a sentence must name the same second, and a
    # second that has not fully passed is not one to claim.
    Scenario() \
        .given(
            some_duration := timedelta(seconds=9.6)
        ) \
        .when(
            lambda: as_span(some_duration)
        ) \
        .then(
            the_answer_was("9s")
        )


@pytest.mark.unit
def test_a_span_under_a_second_is_said_as_less_than_one() -> None:
    # "0s" would say nothing passed; the prose says what did.
    Scenario() \
        .given(
            some_gap := timedelta(seconds=0.4)
        ) \
        .when(
            lambda: as_span(some_gap)
        ) \
        .then(
            the_answer_was("less than a second")
        )


@pytest.mark.unit
def test_a_commit_is_shown_by_its_first_seven_characters() -> None:
    # As git shows one: forty characters is a line of noise, and seven is what
    # a reader pastes into git to find it.
    Scenario() \
        .given(
            some_commit := "26f1d7e2c82ce2abff8f9b6424dc226f4f37fed2"
        ) \
        .when(
            lambda: as_revision(some_commit)
        ) \
        .then(
            the_answer_was("26f1d7e")
        )


@pytest.mark.unit
@pytest.mark.parametrize("revision", ["v2.4.1", "26f1d7e", "release-2026-10-05"])
def test_a_revision_that_is_not_a_whole_commit_is_shown_as_written(revision: str) -> None:
    # A deployment's state is whatever the investigation called it. Cut to
    # seven, a tag or an already-short commit would lose what names it.
    Scenario() \
        .given(
            revision
        ) \
        .when(
            lambda: as_revision(revision)
        ) \
        .then(
            the_answer_was(revision)
        )


@pytest.mark.unit
def test_a_moment_in_another_zone_is_said_in_utc_and_says_so() -> None:
    # Converted rather than trusted: a time arriving in the connection's zone
    # and printed as it came would make the label a guess.
    Scenario() \
        .given(
            some_moment := datetime(2026, 10, 14, 16, 3, tzinfo=timezone(timedelta(hours=2)))
        ) \
        .when(
            lambda: in_utc(some_moment)
        ) \
        .then(
            the_answer_was("2026-10-14 14:03 UTC")
        )


@pytest.mark.unit
def test_a_moment_is_said_in_whatever_pattern_it_is_asked_for() -> None:
    Scenario() \
        .given(
            some_moment := datetime(2026, 10, 14, 14, 3, tzinfo=UTC)
        ) \
        .when(
            lambda: in_utc(some_moment, "%b %d, %Y, %H:%M")
        ) \
        .then(
            the_answer_was("Oct 14, 2026, 14:03 UTC")
        )


@pytest.mark.unit
def test_a_moment_on_the_clock_is_converted_and_left_unlabelled() -> None:
    # For a column whose heading says UTC once, rather than every row of it.
    Scenario() \
        .given(
            some_moment := datetime(2026, 10, 14, 16, 3, 9, tzinfo=timezone(timedelta(hours=2)))
        ) \
        .when(
            lambda: on_the_clock(some_moment)
        ) \
        .then(
            the_answer_was("14:03:09")
        )
