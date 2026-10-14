"""Seeding the shop's world as a recording found it.

A case stages the recording's anchor, and the next seed uses it up: the stand-in
waits for the first instant that is the anchor moved by whole minutes, seeds the
shop with its clock reading exactly that instant, and moves every draw back by
the same whole minutes. A seed with nothing staged is the shop's own, untouched -
which is what a fresh recording sees.
"""

from __future__ import annotations

import random
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest
from argus_testkit import Assertion, Scenario, all_of, calling
from target_service_double.draws import ShiftedDraws
from target_service_double.seeding import Seeding

THE_SHOPS_MINUTE_FORMAT = "%Y-%m-%dT%H:%M:%SZ"

SOME_ANCHOR = datetime(2026, 9, 28, 22, 11, 43, 502554, tzinfo=UTC)
SOME_REPLAY_START = datetime(2026, 10, 14, 3, 50, 10, tzinfo=UTC)
# The anchor's own second in the replay's first minute that has not passed yet.
THE_SEED_INSTANT = datetime(2026, 10, 14, 3, 50, 43, 502554, tzinfo=UTC)

DONT_CARE_SEEDED = "seeded"


class _AStackClock:
    """The stack's clock, moved on only by the stand-in's own sleeping."""

    def __init__(self, reading: datetime) -> None:
        self.reading = reading
        self.slept = 0

    def now(self) -> datetime:
        return self.reading

    def sleep(self, dont_care_seconds: float) -> None:
        self.slept += 1
        self.reading += timedelta(seconds=1)


class _TheShopsClock:
    """Where the shop reads `now` when it seeds, as the stand-in pins it."""

    def __init__(self) -> None:
        self.pinned_at: datetime | None = None
        self.pins: list[datetime] = []

    @contextmanager
    def pinned(self, instant: datetime) -> Iterator[None]:
        self.pinned_at = instant
        self.pins.append(instant)
        try:
            yield
        finally:
            self.pinned_at = None


class _TheShop:
    """The shop's own seed, noting what it saw while it ran."""

    def __init__(self, stack: _AStackClock, clock: _TheShopsClock) -> None:
        self.seeded_at_stack_time: datetime | None = None
        self.read_its_clock_as: datetime | None = None
        self._stack = stack
        self._clock = clock

    def seed(self) -> str:
        self.seeded_at_stack_time = self._stack.now()
        self.read_its_clock_as = self._clock.pinned_at

        return DONT_CARE_SEEDED

    def fail_to_seed(self) -> str:
        raise RuntimeError("the shop could not seed")


@pytest.mark.unit
def test_a_staged_seed_waits_for_the_anchors_second_and_seeds_the_shop_at_it() -> None:
    stack = _AStackClock(SOME_REPLAY_START)
    clock = _TheShopsClock()
    shop = _TheShop(stack, clock)

    Scenario() \
        .given(seeding := _a_seeding(stack, clock, staged=SOME_ANCHOR)) \
        .when(lambda: seeding.seed(shop.seed)) \
        .then(all_of(
            _the_shop_seeded_no_earlier_than(shop, THE_SEED_INSTANT),
            _the_shop_read_its_clock_as(shop, THE_SEED_INSTANT)
        ))


@pytest.mark.unit
def test_a_staged_seed_moves_every_draw_back_to_the_recorded_minutes() -> None:
    stack = _AStackClock(SOME_REPLAY_START)
    clock = _TheShopsClock()
    shop = _TheShop(stack, clock)

    Scenario() \
        .given(seeding := _a_seeding(stack, clock, staged=SOME_ANCHOR)) \
        .when(lambda: seeding.seed(shop.seed)) \
        .then(_the_draws_are_shifted_by(seeding, THE_SEED_INSTANT - SOME_ANCHOR))


@pytest.mark.unit
def test_the_shops_clock_is_pinned_only_while_it_seeds() -> None:
    # Everything after the seed - an action, a read - happens at the stack's
    # own time, which is the time the replay's world runs on.
    stack = _AStackClock(SOME_REPLAY_START)
    clock = _TheShopsClock()
    shop = _TheShop(stack, clock)

    Scenario() \
        .given(seeding := _a_seeding(stack, clock, staged=SOME_ANCHOR)) \
        .when(lambda: seeding.seed(shop.seed)) \
        .then(_the_shops_clock_is_its_own(clock))


@pytest.mark.unit
def test_a_seed_that_fails_still_gives_the_shop_its_clock_back() -> None:
    stack = _AStackClock(SOME_REPLAY_START)
    clock = _TheShopsClock()
    shop = _TheShop(stack, clock)

    Scenario() \
        .given(seeding := _a_seeding(stack, clock, staged=SOME_ANCHOR)) \
        .when(lambda: _what_raised(lambda: seeding.seed(shop.fail_to_seed))) \
        .then(all_of(
            _raised(RuntimeError),
            _the_shops_clock_is_its_own(clock)
        ))


@pytest.mark.unit
def test_a_seed_with_nothing_staged_is_the_shops_own() -> None:
    # No wait, no pinned clock, no moved draw: a fresh recording sees the shop.
    stack = _AStackClock(SOME_REPLAY_START)
    clock = _TheShopsClock()
    shop = _TheShop(stack, clock)

    Scenario() \
        .given(seeding := _a_seeding(stack, clock, staged=None)) \
        .when(lambda: seeding.seed(shop.seed)) \
        .then(all_of(
            _it_never_waited(stack),
            _the_shops_clock_was_never_pinned(clock),
            _the_draws_are_shifted_by(seeding, timedelta(0))
        ))


@pytest.mark.unit
def test_the_anchor_is_used_up_by_the_seed_it_was_staged_for() -> None:
    # A later seed in the same stack - the next case's - is the shop's own
    # unless that case stages an anchor of its own.
    stack = _AStackClock(SOME_REPLAY_START)
    clock = _TheShopsClock()
    shop = _TheShop(stack, clock)

    Scenario() \
        .given(
            seeding := _a_seeding(stack, clock, staged=SOME_ANCHOR),
            calling(lambda: seeding.seed(shop.seed))
        ) \
        .when(lambda: seeding.seed(shop.seed)) \
        .then(_the_draws_are_shifted_by(seeding, timedelta(0)))


@pytest.mark.unit
def test_a_reset_forgets_the_staged_anchor_and_the_shift() -> None:
    stack = _AStackClock(SOME_REPLAY_START)
    clock = _TheShopsClock()
    shop = _TheShop(stack, clock)

    Scenario() \
        .given(
            seeding := _a_seeding(stack, clock, staged=SOME_ANCHOR),
            calling(lambda: seeding.seed(shop.seed)),
            calling(lambda: seeding.stage(SOME_ANCHOR))
        ) \
        .when(lambda: seeding.reset()) \
        .then(all_of(
            _the_draws_are_shifted_by(seeding, timedelta(0)),
            _nothing_is_staged(seeding)
        ))


@pytest.mark.unit
def test_the_seed_says_which_anchor_it_used() -> None:
    # What a case asks, to know the world it is replaying into is the one its
    # recording was captured in.
    stack = _AStackClock(SOME_REPLAY_START)
    clock = _TheShopsClock()
    shop = _TheShop(stack, clock)

    Scenario() \
        .given(seeding := _a_seeding(stack, clock, staged=SOME_ANCHOR)) \
        .when(lambda: seeding.seed(shop.seed)) \
        .then(_the_last_seed_used(seeding, SOME_ANCHOR))


@pytest.mark.unit
def test_a_seed_with_nothing_staged_says_it_used_no_anchor() -> None:
    stack = _AStackClock(SOME_REPLAY_START)
    clock = _TheShopsClock()
    shop = _TheShop(stack, clock)

    Scenario() \
        .given(seeding := _a_seeding(stack, clock, staged=None)) \
        .when(lambda: seeding.seed(shop.seed)) \
        .then(_the_last_seed_used(seeding, None))


def _a_seeding(stack: _AStackClock,
               clock: _TheShopsClock,
               staged: datetime | None) -> Seeding:
    seeding = Seeding(ShiftedDraws(random, THE_SHOPS_MINUTE_FORMAT),
                      now=stack.now,
                      sleep=stack.sleep,
                      pin_the_shops_clock=clock.pinned)

    if staged is not None:
        seeding.stage(staged)

    return seeding


def _what_raised(call: Callable[[], object]) -> Exception | None:
    try:
        call()
    except Exception as raised:  # noqa: BLE001 - the error is the result
        return raised

    return None


def _raised(expected: type[Exception]) -> Assertion[Exception | None]:
    def assertion(raised: Exception | None) -> bool:
        if not isinstance(raised, expected):
            raise AssertionError(
                f"Expected the seed to raise [{expected.__name__}], got [{raised!r}]."
            )

        return True

    return assertion


def _the_shop_seeded_no_earlier_than(shop: _TheShop, instant: datetime) -> Assertion[object]:
    def assertion(_: object) -> bool:
        if shop.seeded_at_stack_time is None or shop.seeded_at_stack_time < instant:
            raise AssertionError(
                f"Expected the shop to seed once the stack's clock reached "
                f"[{instant.isoformat()}], and it seeded at "
                f"[{shop.seeded_at_stack_time}] - before the instant it was told."
            )

        return True

    return assertion


def _the_shop_read_its_clock_as(shop: _TheShop, instant: datetime) -> Assertion[object]:
    def assertion(_: object) -> bool:
        if shop.read_its_clock_as != instant:
            raise AssertionError(
                f"Expected the shop to read its clock as [{instant.isoformat()}] "
                f"while it seeded, and it read [{shop.read_its_clock_as}]."
            )

        return True

    return assertion


def _the_draws_are_shifted_by(seeding: Seeding, expected: timedelta) -> Assertion[object]:
    def assertion(_: object) -> bool:
        if seeding.state().shift != expected:
            raise AssertionError(
                f"Expected the draws to be moved back by [{expected}], and they "
                f"are moved by [{seeding.state().shift}]."
            )

        return True

    return assertion


def _the_shops_clock_is_its_own(clock: _TheShopsClock) -> Assertion[object]:
    def assertion(_: object) -> bool:
        if clock.pinned_at is not None:
            raise AssertionError(
                f"Expected the shop's clock back after the seed, and it is still "
                f"pinned at [{clock.pinned_at.isoformat()}]."
            )

        return True

    return assertion


def _the_shops_clock_was_never_pinned(clock: _TheShopsClock) -> Assertion[object]:
    def assertion(_: object) -> bool:
        if clock.pins:
            raise AssertionError(
                f"Expected the shop's clock left alone, and it was pinned at {clock.pins}."
            )

        return True

    return assertion


def _it_never_waited(stack: _AStackClock) -> Assertion[object]:
    def assertion(_: object) -> bool:
        if stack.slept:
            raise AssertionError(
                f"Expected no wait before a seed with nothing staged, and it slept "
                f"[{stack.slept}] times."
            )

        return True

    return assertion


def _nothing_is_staged(seeding: Seeding) -> Assertion[object]:
    def assertion(_: object) -> bool:
        if seeding.state().staged is not None:
            raise AssertionError(
                f"Expected nothing staged, and [{seeding.state().staged}] is."
            )

        return True

    return assertion


def _the_last_seed_used(seeding: Seeding, expected: datetime | None) -> Assertion[object]:
    def assertion(_: object) -> bool:
        if seeding.state().last_seeded_from != expected:
            raise AssertionError(
                f"Expected the last seed to have used the anchor [{expected}], "
                f"and it used [{seeding.state().last_seeded_from}]."
            )

        return True

    return assertion
