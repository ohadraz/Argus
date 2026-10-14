"""Seeding the shop's world as a recording found it.

A case stages its recording's anchor, and the next seed uses it up. Seeded
from an anchor, the shop's world is the recorded one moved by whole minutes:
its draws are the recorded minutes' own, and its seed instant is the recorded
one to the microsecond, so an outage's first minute is broken for exactly the
share of it the recording saw.

Waiting rather than pretending: the stand-in waits for the stack's clock to
reach the seed instant before it seeds, so that everything the seed does through
other parties - the flags it moves in Unleash - happens a moment after it, as
it did when the set was recorded. Only the shop's own reading of the clock is
pinned, and only for the seed: once seeded, the world runs on the stack's time.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

from target_service_double.draws import ShiftedDraws
from target_service_double.instant import the_seed_instant

# Holds the shop's clock at an instant for as long as the seed takes.
type PinTheShopsClock = Callable[[datetime], AbstractContextManager[None]]

# How long to sleep between looks at the stack's clock while waiting for the
# seed instant: on a clock running ten times fast, a tenth of a stack-second.
_A_LOOK_SECONDS: Final = 0.01


@dataclass(frozen=True)
class SeedingState:
    """What a case may ask: what is staged, how far the world is moved, and
    which anchor the last seed was seeded from - `None` for the shop's own."""

    staged: datetime | None
    shift: timedelta
    last_seeded_from: datetime | None


class Seeding:
    """The stand-in's seeds, and the anchor the next one uses.

    `now` and `sleep` are the stack's clock and a way of letting it move;
    `pin_the_shops_clock` is where the shop reads `now` while it seeds.
    """

    def __init__(self,
                 draws: ShiftedDraws,
                 *,
                 now: Callable[[], datetime],
                 sleep: Callable[[float], None],
                 pin_the_shops_clock: PinTheShopsClock) -> None:
        self._draws = draws
        self._now = now
        self._sleep = sleep
        self._pin_the_shops_clock = pin_the_shops_clock
        self._staged: datetime | None = None
        self._last_seeded_from: datetime | None = None

    def stage(self, anchor: datetime) -> None:
        """The anchor the next seed is seeded from."""
        self._staged = anchor

    def reset(self) -> None:
        """Nothing staged, and the shop's own draws."""
        self._staged = None
        self._last_seeded_from = None
        self._draws.shift = timedelta(0)

    def state(self) -> SeedingState:
        return SeedingState(staged=self._staged,
                            shift=self._draws.shift,
                            last_seeded_from=self._last_seeded_from)

    def seed[T](self, seed_the_shop: Callable[[], T]) -> T:
        """Seeds the shop - as the staged anchor's world where one is staged,
        as the shop's own otherwise - and uses the anchor up."""
        anchor, self._staged = self._staged, None
        self._last_seeded_from = anchor

        if anchor is None:
            self._draws.shift = timedelta(0)

            return seed_the_shop()

        instant = the_seed_instant(anchor, now=self._now())

        while self._now() < instant:
            self._sleep(_A_LOOK_SECONDS)

        self._draws.shift = instant - anchor

        with self._pin_the_shops_clock(instant):
            return seed_the_shop()
