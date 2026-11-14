"""Seeding the shop's world as a recording found it.

A case stages the recording's anchor, and the next seed uses it up: the stand-in
waits for the first instant that is the anchor moved by whole minutes, seeds the
shop with its clock reading exactly that instant, and moves every draw back by
the same whole minutes. A seed with nothing staged is the shop's own, untouched -
which is what a fresh recording sees.
"""

from __future__ import annotations

import random
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest
from argus_testkit import Assertion, Scenario, all_of
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

    def now(self) -> datetime:
        return self.reading

    def sleep(self, dont_care_seconds: float) -> None:
        self.reading += timedelta(seconds=1)


class _TheShopsClock:
    """Where the shop reads `now` when it seeds, as the stand-in pins it."""

    def __init__(self) -> None:
        self.pinned_at: datetime | None = None

    @contextmanager
    def pinned(self, instant: datetime) -> Iterator[None]:
        self.pinned_at = instant
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


@pytest.mark.unit
def test_a_staged_seed_waits_for_the_anchors_second_and_seeds_the_shop_at_it() -> None:
    # Here rather than only in the contract suite, whose clock reaches the seed
    # instant by its own steps whether or not the stand-in waits for it or pins
    # the shop's clock there - so a seed that did neither would pass it, and
    # show only as a replay now and then citing a figure a second adrift.
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
