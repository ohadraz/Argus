"""Where the stand-in reaches into the shop.

Every name it reaches is a public one in the shop's own modules: the `random`
its generator draws each minute from, the `utc_now` its state reads when it
seeds, and the three integrity checks its state asks, which hang purchases on a
grid no clock moves. Everything else the shop does it does as the shop.
"""

from __future__ import annotations

import random
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from types import ModuleType
from typing import Any, Final

from target_service_double.checks import asked_as_recorded
from target_service_double.seeding import PinTheShopsClock

# The integrity checks the shop's state asks, each by the integrity module's own
# name for it. Every reading of the purchase grid goes through one of these.
THE_CHECKS: Final = (
    "what_the_check_found",
    "the_accounts_the_check_examines",
    "the_figures_the_promoted_standby_holds"
)


def what_the_shop_lacks(generator: ModuleType,
                        state: ModuleType,
                        scenarios: ModuleType,
                        integrity: ModuleType) -> list[str]:
    """Each name the stand-in needs to reach and cannot, said as a reason.

    Empty for a shop the stand-in can serve as recorded. Anything else and the
    stand-in must not start: a draw, a clock read or a check it cannot move
    would serve the shop's own world under a recording's answers, and nothing
    would say so.
    """
    lacking = []

    if getattr(generator, "random", None) is not random:
        lacking.append(
            "target_app.generator.random is not the random module, so the "
            "generator's draws cannot be moved"
        )

    if getattr(state, "utc_now", None) is not getattr(scenarios, "utc_now", None):
        lacking.append(
            "target_app.state.utc_now is not target_app.scenarios.utc_now, so the "
            "seed's clock cannot be pinned where the shop reads it"
        )

    for check in THE_CHECKS:
        asked = getattr(state, check, None)

        if asked is None or asked is not getattr(integrity, check, None):
            lacking.append(
                f"target_app.state.{check} is not target_app.integrity.{check}, so "
                f"the check cannot be asked as recorded where the shop asks it"
            )

    return lacking


def asking_the_checks_as_recorded(state: Any, shift: Callable[[], timedelta]) -> None:
    """Rebinds each of the shop's checks in `state` to be asked as recorded,
    `shift()` earlier, and to answer in the replay's time.

    `Any` rather than `ModuleType`, for the reason `pinning_the_clock_of` gives.
    """
    for check in THE_CHECKS:
        setattr(state, check, asked_as_recorded(getattr(state, check), shift))


def pinning_the_clock_of(state: Any) -> PinTheShopsClock:
    """Holds `state.utc_now` at an instant for as long as the block runs, and
    gives the shop its own clock back however the block ends.

    `Any` rather than `ModuleType`, because what this does is rebind a name in
    the shop's module, and a module's names are not known until it is loaded.
    """
    @contextmanager
    def pinned(instant: datetime) -> Iterator[None]:
        own_clock: Callable[[], datetime] = state.utc_now
        state.utc_now = lambda: instant
        try:
            yield
        finally:
            state.utc_now = own_clock

    return pinned
