"""How a stored value is written for a reader.

Formatting belongs to whatever shows the value, never to what stores it: the
document keeps every amount at the precision it was computed to, and only what
shows it rounds. Each case is one value and the words it must come out as.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest
from argus_testkit import Scenario, the_answer_was
from postmortem_rendering.formatting import (
    as_revision,
    as_span,
    in_utc,
    on_the_clock,
    on_the_day,
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
def test_a_moment_with_seconds_is_said_in_utc_to_the_second() -> None:
    # As every instant is said. "Opened 19:12" sat above the walk's first line,
    # the acknowledgement, saying the same instant as 19:12:56.
    Scenario() \
        .given(
            some_moment := datetime(2026, 10, 14, 14, 3, 9, tzinfo=UTC)
        ) \
        .when(
            lambda: in_utc(some_moment)
        ) \
        .then(
            the_answer_was("2026-10-14 14:03:09 UTC")
        )


@pytest.mark.unit
def test_a_moment_on_the_clock_is_converted_and_left_unlabelled() -> None:
    # For markup a script reads, in the pattern it reads: every moment a person
    # reads is said through the kernel's time.
    Scenario() \
        .given(
            some_moment := datetime(2026, 10, 14, 16, 3, 9, tzinfo=timezone(timedelta(hours=2)))
        ) \
        .when(
            lambda: on_the_clock(some_moment, "%Y-%m-%dT%H:%M:%SZ")
        ) \
        .then(
            the_answer_was("2026-10-14T14:03:09Z")
        )


@pytest.mark.unit
def test_a_moment_s_day_is_the_day_it_falls_on_in_utc() -> None:
    # Past midnight in the connection's zone and still the evening before in
    # UTC: the day is the one the rest of the page's UTC times fall on.
    Scenario() \
        .given(
            some_moment := datetime(2026, 10, 15, 1, 3, tzinfo=timezone(timedelta(hours=2)))
        ) \
        .when(
            lambda: on_the_day(some_moment)
        ) \
        .then(
            the_answer_was("Oct 14")
        )


@pytest.mark.unit
def test_a_moment_s_day_is_followed_by_whatever_it_is_asked_for() -> None:
    # The day the kernel's way, which narration's lines on the same page say
    # too, and the rest of the moment in whatever pattern the place wants.
    Scenario() \
        .given(
            some_moment := datetime(2026, 10, 14, 14, 3, tzinfo=UTC)
        ) \
        .when(
            lambda: on_the_day(some_moment, ", %Y, %H:%M")
        ) \
        .then(
            the_answer_was("Oct 14, 2026, 14:03")
        )
