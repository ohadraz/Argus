"""The one spelling of an instant, and the one way back from it.

Every timestamp Argus writes down goes through here, and every one it reads
back off a log line or a bucket id comes back through here. So the questions
worth asking are the two a caller can get wrong without noticing: what happens
to an instant that is not already in UTC, and what happens to precision finer
than the format keeps.

Both answers are "converted, never rejected", which is why they are tested
rather than assumed. A function that quietly wrote a host's local hour would
raise nothing and be wrong everywhere downstream, in a field nobody reads twice.

The expected text is derived from the same parts the instant is built from
rather than written out. A test that restated the answer as a literal would
agree with a formatter that had been changed to match it.

And the clock every instant is read from is read once, when it is first asked
for: naming the kernel reads no environment, and a stack configured by half is
refused where a process's root first asks - asked of a fresh interpreter,
because this one named its clock long ago.
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta, timezone
from typing import Final

import pytest
from argus_testkit import Assertion, Scenario, an_error_was_raised, attempting
from core.timestamps import parse_iso, to_iso, to_iso_minute, utc_now

# The two settings a simulated clock is named by. Stated rather than imported:
# they are what a stack sets, and a test sharing the constants would pass
# through a rename that broke every stack.
CLOCK_EPOCH: Final = "SIM_CLOCK_EPOCH"
CLOCK_SPEED: Final = "SIM_CLOCK_SPEED"


@pytest.mark.component
def test_naming_the_kernel_reads_no_clock() -> None:
    # The environment is a root's to read. A kernel that read the clock as it
    # was imported would refuse a stack configured by half wherever it was
    # first named - a suite, a script, a library's import - and not where the
    # process starts.
    Scenario() \
        .given(
            half_a_clock := _an_environment_naming_half_a_clock()
        ) \
        .when(
            lambda: _what_a_fresh_interpreter_does("import core", half_a_clock)
        ) \
        .then(
            _it_ran_cleanly()
        )


@pytest.mark.component
def test_asking_for_the_clock_of_a_stack_configured_by_half_is_refused() -> None:
    Scenario() \
        .given(
            half_a_clock := _an_environment_naming_half_a_clock()
        ) \
        .when(
            lambda: _what_a_fresh_interpreter_does("import core; core.the_clock()", half_a_clock)
        ) \
        .then(
            _it_was_refused_with(ValueError.__name__)
        )


@pytest.mark.unit
def test_to_iso_writes_a_utc_instant_with_a_trailing_z() -> None:
    some_year = 2026
    some_month = 8
    some_day = 20
    some_hour = 11
    some_minute = 45

    Scenario() \
        .given(
            some_instant_on_the_minute := datetime(
                some_year, some_month, some_day, some_hour, some_minute, 0, tzinfo=UTC
            )
        ) \
        .when(
            lambda: to_iso(some_instant_on_the_minute)
        ) \
        .then(
            _it_was_written_as(
                f"{some_year}-{some_month:02d}-{some_day:02d}"
                f"T{some_hour:02d}:{some_minute:02d}:00Z"
            )
        )


@pytest.mark.unit
def test_to_iso_converts_an_offset_instant_to_utc() -> None:
    some_year = 2026
    some_month = 8
    some_day = 20
    some_local_hour = 14
    some_minute = 45
    some_offset_hours = 3

    Scenario() \
        .given(
            some_instant_on_the_minute := datetime(
                some_year,
                some_month,
                some_day,
                some_local_hour,
                some_minute,
                0,
                tzinfo=timezone(timedelta(hours=some_offset_hours))
            )
        ) \
        .when(
            lambda: to_iso(some_instant_on_the_minute)
        ) \
        .then(
            _it_was_written_as(
                f"{some_year}-{some_month:02d}-{some_day:02d}"
                f"T{some_local_hour - some_offset_hours:02d}:{some_minute:02d}:00Z"
            )
        )


@pytest.mark.unit
def test_to_iso_writes_whole_seconds() -> None:
    some_year = 2026
    some_month = 8
    some_day = 20
    some_hour = 11
    some_minute = 45
    some_second = 37

    Scenario() \
        .given(
            some_instant_with_sub_second_precision := datetime(
                some_year,
                some_month,
                some_day,
                some_hour,
                some_minute,
                some_second,
                123456,
                tzinfo=UTC
            )
        ) \
        .when(
            lambda: to_iso(some_instant_with_sub_second_precision)
        ) \
        .then(
            _it_was_written_as(
                f"{some_year}-{some_month:02d}-{some_day:02d}"
                f"T{some_hour:02d}:{some_minute:02d}:{some_second:02d}Z"
            )
        )


@pytest.mark.unit
def test_parse_iso_reads_what_to_iso_wrote() -> None:
    # The round trip, which is the only claim that binds the two halves: either
    # alone can be self-consistently wrong about the zone.
    Scenario() \
        .given(
            some_instant := datetime(2026, 8, 20, 11, 45, 37, tzinfo=UTC)
        ) \
        .when(
            lambda: parse_iso(to_iso(some_instant))
        ) \
        .then(
            _the_instant_read_was(some_instant)
        )


@pytest.mark.unit
def test_parse_iso_treats_a_naive_instant_as_utc() -> None:
    some_year = 2026
    some_month = 8
    some_day = 20
    some_hour = 11
    some_minute = 45

    Scenario() \
        .given(
            some_naive_text := (
                f"{some_year}-{some_month:02d}-{some_day:02d}"
                f"T{some_hour:02d}:{some_minute:02d}:00"
            )
        ) \
        .when(
            lambda: parse_iso(some_naive_text)
        ) \
        .then(
            _the_instant_read_was(
                datetime(some_year, some_month, some_day, some_hour, some_minute, 0, tzinfo=UTC)
            )
        )


@pytest.mark.unit
def test_parse_iso_reads_an_offset_instant_as_the_same_moment() -> None:
    some_year = 2026
    some_month = 8
    some_day = 20
    some_local_hour = 14
    some_minute = 45
    some_offset_hours = 3

    Scenario() \
        .given(
            some_offset_text := (
                f"{some_year}-{some_month:02d}-{some_day:02d}"
                f"T{some_local_hour:02d}:{some_minute:02d}:00+{some_offset_hours:02d}:00"
            )
        ) \
        .when(
            lambda: parse_iso(some_offset_text)
        ) \
        .then(
            _the_instant_read_was(
                datetime(
                    some_year,
                    some_month,
                    some_day,
                    some_local_hour - some_offset_hours,
                    some_minute,
                    0,
                    tzinfo=UTC
                )
            )
        )


@pytest.mark.unit
def test_parse_iso_rejects_text_that_is_not_a_timestamp() -> None:
    Scenario() \
        .given(
            some_log_line_without_a_timestamp := "ERROR"
        ) \
        .when(
            attempting(lambda: parse_iso(some_log_line_without_a_timestamp))
        ) \
        .then(
            an_error_was_raised(ValueError)
        )


@pytest.mark.unit
def test_to_iso_minute_truncates_an_instant_to_its_minute() -> None:
    some_year = 2026
    some_month = 8
    some_day = 20
    some_hour = 11
    some_minute = 45

    Scenario() \
        .given(
            some_instant_with_sub_second_precision := datetime(
                some_year, some_month, some_day, some_hour, some_minute, 37, 123456, tzinfo=UTC
            )
        ) \
        .when(
            lambda: to_iso_minute(some_instant_with_sub_second_precision)
        ) \
        .then(
            _it_was_written_as(
                f"{some_year}-{some_month:02d}-{some_day:02d}"
                f"T{some_hour:02d}:{some_minute:02d}:00Z"
            )
        )


@pytest.mark.unit
def test_to_iso_minute_normalizes_to_utc() -> None:
    some_year = 2026
    some_month = 8
    some_day = 20
    some_local_hour = 14
    some_minute = 45
    some_offset_hours = 3

    Scenario() \
        .given(
            some_instant_on_the_minute := datetime(
                some_year,
                some_month,
                some_day,
                some_local_hour,
                some_minute,
                0,
                tzinfo=timezone(timedelta(hours=some_offset_hours))
            )
        ) \
        .when(
            lambda: to_iso_minute(some_instant_on_the_minute)
        ) \
        .then(
            _it_was_written_as(
                f"{some_year}-{some_month:02d}-{some_day:02d}"
                f"T{some_local_hour - some_offset_hours:02d}:{some_minute:02d}:00Z"
            )
        )


@pytest.mark.unit
def test_to_iso_minute_is_the_same_for_any_instant_within_that_minute() -> None:
    # What makes a minute usable as an id: every instant inside it has to name
    # the same one, or a log line and the bucket it belongs to would disagree
    # about which minute they were in.
    Scenario() \
        .given(
            some_instant_on_the_minute := datetime(2026, 8, 20, 11, 45, 0, tzinfo=UTC)
        ) \
        .when(
            lambda: (
                to_iso_minute(some_instant_on_the_minute),
                to_iso_minute(some_instant_on_the_minute + timedelta(seconds=59))
            )
        ) \
        .then(
            _both_named_the_same_minute()
        )


@pytest.mark.unit
def test_utc_now_answers_an_instant_that_knows_it_is_in_utc() -> None:
    # One assertion for both halves: a naive instant has no offset to compare,
    # so an answer that is not aware fails here rather than reading as some
    # other zone. Everything that writes a timestamp down goes through `to_iso`,
    # which converts rather than rejects - so a clock that answered naively
    # would not raise, it would quietly write whatever the host's zone made of
    # the number.
    Scenario() \
        .given(
            no_offset_at_all := timedelta(0)
        ) \
        .when(
            lambda: utc_now().utcoffset()
        ) \
        .then(
            _the_offset_was(no_offset_at_all)
        )


def _an_environment_naming_half_a_clock() -> dict[str, str]:
    """This process's environment with a speed and no epoch - everything else
    kept, so the interpreter finds what it was installed with."""
    environment = {name: value for name, value in os.environ.items() if name != CLOCK_EPOCH}
    environment[CLOCK_SPEED] = "10"

    return environment


def _what_a_fresh_interpreter_does(running: str,
                                   environment: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """`running`, in a new interpreter under `environment`."""
    return subprocess.run([sys.executable, "-c", running], env=environment,
                          capture_output=True, text=True, check=False)


def _it_ran_cleanly() -> Assertion[subprocess.CompletedProcess[str]]:
    def assertion(finished: subprocess.CompletedProcess[str]) -> bool:
        if finished.returncode != 0:
            raise AssertionError(
                f"Expected the interpreter to finish cleanly, and it exited "
                f"[{finished.returncode}]: {finished.stderr.strip()}"
            )

        return True

    return assertion


def _it_was_refused_with(error: str) -> Assertion[subprocess.CompletedProcess[str]]:
    def assertion(finished: subprocess.CompletedProcess[str]) -> bool:
        if finished.returncode == 0 or error not in finished.stderr:
            raise AssertionError(
                f"Expected the interpreter refused with [{error}], and it exited "
                f"[{finished.returncode}]: {finished.stderr.strip() or 'saying nothing'}"
            )

        return True

    return assertion


def _it_was_written_as(expected: str) -> Assertion[str]:
    def assertion(written: str) -> bool:
        if written != expected:
            raise AssertionError(f"Expected [{expected}], got [{written}].")

        return True

    return assertion


def _the_instant_read_was(expected: datetime) -> Assertion[datetime]:
    """The instant itself, compared as a moment rather than as text.

    Two aware datetimes are equal when they name the same moment, whatever
    zone each carries - which is the property being claimed here, and the one
    a comparison of their spellings would miss.
    """
    def assertion(read: datetime) -> bool:
        if read != expected:
            raise AssertionError(f"Expected [{expected!r}], got [{read!r}].")

        return True

    return assertion


def _both_named_the_same_minute() -> Assertion[tuple[str, str]]:
    def assertion(named: tuple[str, str]) -> bool:
        on_the_minute, later_in_it = named
        if on_the_minute != later_in_it:
            raise AssertionError(
                f"Expected both instants to name one minute, got [{on_the_minute}] "
                f"and [{later_in_it}]."
            )

        return True

    return assertion


def _the_offset_was(expected: timedelta) -> Assertion[timedelta | None]:
    """That the clock answered something that knows its own zone.

    `None` is the failure this is written for - a naive instant - and it is
    called out separately, because "no offset at all" and "an offset of zero"
    are the two answers this test exists to keep apart.
    """
    def assertion(offset: timedelta | None) -> bool:
        if offset is None:
            raise AssertionError("Expected an instant aware of its zone, got a naive one.")

        if offset != expected:
            raise AssertionError(f"Expected an offset of [{expected}], got [{offset}].")

        return True

    return assertion
