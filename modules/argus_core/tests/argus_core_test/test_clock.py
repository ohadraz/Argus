"""The one clock every process of a stack reads, and the rate it runs at.

A stack hands every process the same two numbers - an epoch and a speed - and
each works out the same instant from its own real clock. So the claims worth
pinning are the arithmetic (a clock ten times faster has moved ten seconds for
every real one, counted from the epoch), the wait (a wait on that clock costs a
tenth of itself in real time), and the reading of the two numbers - including
that a process told neither runs on the real clock exactly as it always has.

Real time and real sleep are handed in, so nothing here reads a wall clock or
waits on one.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from argus_core.clock import Clock, the_clock_named_by
from argus_testkit import Assertion, Scenario, an_error_was_raised, attempting


@pytest.mark.unit
def test_a_clock_at_its_default_speed_reads_the_real_time() -> None:
    some_real_time = 1_791_242_820.0

    Scenario() \
        .given(
            a_clock := Clock(real_time=lambda: some_real_time)
        ) \
        .when(
            a_clock.now
        ) \
        .then(
            _the_instant_read_was(datetime.fromtimestamp(some_real_time, UTC))
        )


@pytest.mark.unit
def test_a_clock_ten_times_faster_moves_ten_seconds_for_each_real_one() -> None:
    some_epoch = 1_791_242_820.0
    some_real_seconds_since_the_epoch = 3.0
    some_speed = 10.0

    Scenario() \
        .given(
            a_clock := Clock(
                epoch=some_epoch,
                speed=some_speed,
                real_time=lambda: some_epoch + some_real_seconds_since_the_epoch
            )
        ) \
        .when(
            a_clock.now
        ) \
        .then(
            _the_instant_read_was(
                datetime.fromtimestamp(
                    some_epoch + some_real_seconds_since_the_epoch * some_speed, UTC
                )
            )
        )


@pytest.mark.unit
def test_a_wait_on_a_clock_ten_times_faster_lasts_a_tenth_as_long() -> None:
    # A wait standing for time passing in the world being watched - a re-read of
    # a service's minutes - has to pass at the rate those minutes do, or a
    # faster clock would buy nothing for the waits that are most of a run.
    some_speed = 10.0
    some_wait_seconds = 10.0
    real_waits: list[float] = []

    Scenario() \
        .given(
            a_clock := Clock(speed=some_speed, real_sleep=real_waits.append)
        ) \
        .when(
            lambda: a_clock.sleep(some_wait_seconds)
        ) \
        .then(
            _it_waited_in_real_time(real_waits, [some_wait_seconds / some_speed])
        )


@pytest.mark.unit
def test_a_span_on_a_clock_ten_times_faster_is_a_tenth_of_it_in_real_time() -> None:
    # For a wait that is not this process's to sleep through - a thread woken by
    # an event, renewing a lease some other party measures on the stack's clock.
    # It needs the span in real seconds to hand to whatever does the waiting.
    some_speed = 10.0
    some_span_seconds = 240.0

    Scenario() \
        .given(
            a_clock := Clock(speed=some_speed)
        ) \
        .when(
            lambda: a_clock.in_real_time(some_span_seconds)
        ) \
        .then(
            _the_real_seconds_were(some_span_seconds / some_speed)
        )


@pytest.mark.unit
def test_an_environment_naming_no_clock_names_the_real_one() -> None:
    # The case every process outside an e2e stack is in, and the one that must
    # not move: no epoch and no speed is the real clock, read exactly as before.
    Scenario() \
        .given(
            no_clock_named := {"SOME_OTHER_SETTING": "dont-care"}
        ) \
        .when(
            lambda: the_clock_named_by(no_clock_named)
        ) \
        .then(
            _the_clock_is(Clock())
        )


@pytest.mark.unit
def test_an_environment_naming_a_clock_names_that_clock() -> None:
    some_epoch = 1_791_242_820.5
    some_speed = 10.0

    Scenario() \
        .given(
            a_clock_named := {
                "SIM_CLOCK_EPOCH": str(some_epoch),
                "SIM_CLOCK_SPEED": str(some_speed)
            }
        ) \
        .when(
            lambda: the_clock_named_by(a_clock_named)
        ) \
        .then(
            _the_clock_is(Clock(epoch=some_epoch, speed=some_speed))
        )


@pytest.mark.unit
def test_an_environment_naming_half_a_clock_is_refused() -> None:
    # A speed with no epoch, or an epoch with no speed, is a stack configured by
    # half. Read as the real clock it would leave this process on a different
    # time from every other one in the stack - and the symptom is a verdict
    # gone wrong minutes later, nowhere near the setting that caused it.
    Scenario() \
        .given(
            half_a_clock_named := {"SIM_CLOCK_SPEED": "10"}
        ) \
        .when(
            attempting(lambda: the_clock_named_by(half_a_clock_named))
        ) \
        .then(
            an_error_was_raised(ValueError)
        )


def _the_instant_read_was(expected: datetime) -> Assertion[datetime]:
    """The moment, and that it knows it is in UTC - a naive answer never equals
    an aware one, so it fails here rather than reading as some other zone."""
    def assertion(read: datetime) -> bool:
        if read != expected:
            raise AssertionError(
                f"Expected the clock to read [{expected!r}], and it read [{read!r}]."
            )

        return True

    return assertion


def _it_waited_in_real_time(real_waits: list[float],
                            expected: list[float]) -> Assertion[None]:
    def assertion(_: None) -> bool:
        if real_waits != expected:
            raise AssertionError(
                f"Expected real waits of {expected} seconds, and they were {real_waits}."
            )

        return True

    return assertion


def _the_real_seconds_were(expected: float) -> Assertion[float]:
    def assertion(real_seconds: float) -> bool:
        if real_seconds != expected:
            raise AssertionError(
                f"Expected [{expected}] real seconds, and they were [{real_seconds}]."
            )

        return True

    return assertion


def _the_clock_is(expected: Clock) -> Assertion[Clock]:
    def assertion(named: Clock) -> bool:
        if named != expected:
            raise AssertionError(f"Expected the clock [{expected!r}], and it was [{named!r}].")

        return True

    return assertion
