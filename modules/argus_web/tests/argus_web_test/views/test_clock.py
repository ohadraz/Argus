from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from argus_core.timestamps import to_iso
from argus_testkit import Assertion, Scenario
from argus_web.views.clock import a_minute, a_moment, a_window, is_a_moment

"""Wire-format instants, said the way a person reads them.

The tools speak `2026-08-30T10:14:00Z` to each other; a reader sitting beside a
wall clock wants `10:14`. Only the rendering changes - the moment is whichever
one was recorded - so every expectation here is derived from the instant that
went in rather than written out beside it, and a rendering that quietly moved
an instant would fail rather than agree with a second copy somebody typed.

Which instant it is never matters. What matters is what is done to it: trimmed
to a minute, kept to the second, given its date back when a window crosses one,
or handed back untouched because it was never a time at all.
"""


@pytest.mark.unit
def test_an_instant_is_said_the_way_a_clock_says_it() -> None:
    # The raw value stays reachable in the markup that carries it - it is what
    # the metrics rows are keyed by - so nothing is lost by not printing it.
    some_instant = "2026-08-30T10:14:00Z"
    the_clock_time_it_reads_as = some_instant[11:16]

    Scenario() \
        .given(some_instant) \
        .when(lambda: a_minute(some_instant)) \
        .then(_it_reads(the_clock_time_it_reads_as))


@pytest.mark.unit
def test_a_minute_beside_another_on_the_same_day_needs_no_date() -> None:
    # The ordinary window: both ends inside one day, and a date on either would
    # be noise in a sentence a reader is scanning during an incident.
    some_instant = "2026-08-30T10:14:00Z"
    another_instant_that_day = "2026-08-30T19:16:00Z"
    the_clock_time_it_reads_as = some_instant[11:16]

    Scenario() \
        .given(some_instant) \
        .when(lambda: a_minute(some_instant, beside=another_instant_that_day)) \
        .then(_it_reads(the_clock_time_it_reads_as))


@pytest.mark.unit
def test_a_minute_beside_one_on_another_day_carries_its_date() -> None:
    # The change channel is asked about the twenty-four hours before the onset,
    # and a clock time alone renders that as "18:13 to 18:13" - a window a
    # reader can only read as a bug.
    some_instant = "2026-08-30T19:16:00Z"
    an_instant_the_day_before = "2026-08-29T19:16:00Z"
    the_date_it_falls_on = "30 Aug"
    the_clock_time_it_reads_as = some_instant[11:16]

    Scenario() \
        .given(some_instant) \
        .when(lambda: a_minute(some_instant, beside=an_instant_the_day_before)) \
        .then(_it_reads(f"{the_date_it_falls_on} {the_clock_time_it_reads_as}"))


@pytest.mark.unit
def test_something_that_is_not_a_time_is_shown_exactly_as_it_arrived() -> None:
    # The string came out of a recorded event. Blanked, a page would be hiding
    # the one clue to why it looks wrong; guessed at, it would be inventing an
    # instant nothing recorded.
    some_value_that_is_not_a_time = "whenever the ramp finished"

    Scenario() \
        .given(some_value_that_is_not_a_time) \
        .when(lambda: a_minute(some_value_that_is_not_a_time)) \
        .then(_it_reads(some_value_that_is_not_a_time))


@pytest.mark.unit
def test_a_log_lines_own_stamp_is_kept_to_the_second() -> None:
    # A minute is the granularity a reader reads at; a log line's stamp is the
    # granularity it was written at, and two lines in one minute are still two
    # lines.
    some_instant = "2026-08-30T10:14:37Z"
    the_second_it_reads_as = some_instant[11:19]

    Scenario() \
        .given(some_instant) \
        .when(lambda: a_moment(some_instant)) \
        .then(_it_reads(the_second_it_reads_as))


@pytest.mark.unit
def test_a_timestamp_is_recognised_as_one() -> None:
    # What tells a log line's stamp from the first word of its message.
    some_instant = "2026-08-30T10:14:00Z"

    Scenario() \
        .given(some_instant) \
        .when(lambda: is_a_moment(some_instant)) \
        .then(_it_is(True))


@pytest.mark.unit
def test_the_first_word_of_a_message_is_not_a_timestamp() -> None:
    # The service is free to write a line with no stamp at all, and Argus still
    # read it.
    some_word_a_line_opens_with = "io-shop:"

    Scenario() \
        .given(some_word_a_line_opens_with) \
        .when(lambda: is_a_moment(some_word_a_line_opens_with)) \
        .then(_it_is(False))


@pytest.mark.unit
def test_a_window_with_both_ends_says_how_long_it_was_and_where_it_ended() -> None:
    # "29 Aug 19:16 to 30 Aug 19:16" is arithmetic the reader has to do to find
    # out it is a day. The span said outright is the same window already
    # understood, and the end is kept because the end is what it is anchored on.
    some_window_minutes = 10
    some_end = datetime(2026, 8, 30, 10, 14, tzinfo=UTC)
    some_start = some_end - timedelta(minutes=some_window_minutes)

    Scenario() \
        .given(some_start) \
        .when(lambda: a_window(to_iso(some_start), to_iso(some_end))) \
        .then(_it_reads(f"the {some_window_minutes} minutes before {some_end:%H:%M}"))


@pytest.mark.unit
def test_a_window_of_whole_hours_is_said_in_hours() -> None:
    # The largest unit that says it whole. A day's window read as "1440
    # minutes" is a number a reader has to convert before it means anything.
    some_window_hours = 24
    some_end = datetime(2026, 8, 30, 19, 16, tzinfo=UTC)
    some_start = some_end - timedelta(hours=some_window_hours)

    Scenario() \
        .given(some_start) \
        .when(lambda: a_window(to_iso(some_start), to_iso(some_end))) \
        .then(_it_reads(f"the {some_window_hours} hours before {some_end:%d %b %H:%M}"))


@pytest.mark.unit
def test_a_window_anchored_on_one_end_says_only_that_end() -> None:
    # A metrics read is anchored rather than bounded (spec §16), so it has one
    # end - and saying "to now" for the other would put a bound in the account
    # that the call never had.
    some_instant = "2026-08-30T10:14:00Z"
    the_clock_time_it_reads_as = some_instant[11:16]

    Scenario() \
        .given(some_instant) \
        .when(lambda: a_window(some_instant, None)) \
        .then(_it_reads(f"anchored on {the_clock_time_it_reads_as}"))


@pytest.mark.unit
def test_a_window_with_only_an_end_says_what_it_reached_up_to() -> None:
    # The other half of the same asymmetry, and a different sentence because it
    # is a different request: this one was bounded and not anchored.
    some_instant = "2026-08-30T10:14:00Z"
    the_clock_time_it_reads_as = some_instant[11:16]

    Scenario() \
        .given(some_instant) \
        .when(lambda: a_window(None, some_instant)) \
        .then(_it_reads(f"up to {the_clock_time_it_reads_as}"))


@pytest.mark.unit
def test_a_window_with_no_ends_at_all_says_so() -> None:
    # A retrieval that named neither end still happened, and the account says
    # what it asked for rather than leaving the clause empty.
    Scenario() \
        .given(no_window_at_all := (None, None)) \
        .when(lambda: a_window(*no_window_at_all)) \
        .then(_it_reads("over no particular window"))


def _it_reads(expected: str) -> Assertion[str]:
    def assertion(said: str) -> bool:
        if said != expected:
            raise AssertionError(f"expected [{expected}], got [{said}]")

        return True

    return assertion


def _it_is(expected: bool) -> Assertion[bool]:
    def assertion(answered: bool) -> bool:
        if answered is not expected:
            raise AssertionError(f"expected [{expected}], got [{answered}]")

        return True

    return assertion
