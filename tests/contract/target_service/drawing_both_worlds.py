"""Draws each generated scenario twice - as the shop draws it at an anchor, and as
the stand-in draws it from that anchor later - and says where the two differ.

Run with the shop's own interpreter, from the shop's checkout, with the
stand-in's `src` on `PYTHONPATH`; `test_the_stand_in_draws_the_shops_world.py`
does that and reads the last line printed, which is JSON:
`{"compared": {<label>: [<difference>, ...]}, "excluded": {<scenario>: <why>}}`.

In the shop's process rather than through its door, because the shop's door
seeds at whatever instant it is, and one half of this is the shop seeded at an
instant that has passed. So the shop's clock is replaced by one this script
holds, its flag provider by two flags kept in memory, its cache's writes by
nothing, and its window read where its own `/scenario/metrics` reads it. The
stand-in's half is the stand-in's own code - `ShiftedDraws`, `Seeding`,
`pinning_the_clock_of`, `asking_the_checks_as_recorded` - wired as `serve` wires
it, so what is compared is what a replay runs.

Each reading compares the window and what the shop's two integrity checks found,
because those checks hang purchases on a grid of their own that no minute's
name moves, and the alert a replay's walk starts from is built out of what they
found.

Not every scenario: one the shop does not generate has no window to compare.
"""

from __future__ import annotations

import dataclasses
import importlib
import json
import random
import re
import sys
import traceback
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

from target_service_double.draws import ShiftedDraws
from target_service_double.seeding import Seeding
from target_service_double.shop import (
    THE_CHECKS,
    asking_the_checks_as_recorded,
    pinning_the_clock_of,
    what_the_shop_lacks,
)

# The instant every scenario is seeded at by the shop: a recording's anchor,
# down to its microseconds, because those are what the stand-in keeps.
AN_ANCHOR = datetime(2026, 9, 28, 22, 11, 43, 502554, tzinfo=UTC)

# How much later the stand-in is asked to seed it. Both cross a month, which is
# the one move a minute's name cannot make alone - a scenario whose figures
# belong to a month draws from that month's name as well. The stand-in rounds
# each up to whole minutes, and the first comes to an odd number of them: the
# shop takes an order every two minutes, so a world moved by an odd number is the
# one where the grid alone would put the onset a minute off.
SOME_SHIFTS = (
    timedelta(days=15, hours=2, minutes=8, seconds=17),
    timedelta(days=33, hours=5, minutes=41, seconds=52)
)

# When each window is read, after its seed: the minutes before the onset, the
# incident in progress, and a walk's worth of minutes after.
READ_AFTER = (timedelta(seconds=30), timedelta(minutes=5), timedelta(minutes=20))

# How far a look at the stand-in's clock moves it, while it waits for the seed
# instant.
A_LOOK = timedelta(milliseconds=500)

# An instant as the shop writes one into a minute's name or a log line.
A_WRITTEN_INSTANT = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")

# How many differences are said per comparison. The count is always said whole.
SAID_AT_MOST = 5

the_app: Any = importlib.import_module("target_app.app")
generator: Any = importlib.import_module("target_app.generator")
state: Any = importlib.import_module("target_app.state")
scenarios: Any = importlib.import_module("target_app.scenarios")
integrity: Any = importlib.import_module("target_app.integrity")

NOW = [AN_ANCHOR]


def _the_clock() -> datetime:
    return NOW[0]


class _AFlag:
    """One flag, held in memory and moved on this script's clock."""

    def __init__(self, name: str) -> None:
        self._name = name
        self._enabled = False
        self._moved_at: datetime | None = None

    @property
    def name(self) -> str:
        return self._name

    def is_enabled(self) -> bool:
        return self._enabled

    def last_moved_at(self) -> datetime | None:
        return self._moved_at

    def enable(self) -> None:
        if not self._enabled:
            self._moved_at = _the_clock()
        self._enabled = True

    def disable(self) -> None:
        if self._enabled:
            self._moved_at = _the_clock()
        self._enabled = False

    def ensure_flag_exists(self, dont_care_description: str) -> bool:
        return False

    def ensure_only_one_environment(self) -> None:
        return None


@contextmanager
def _no_cache(dont_care_endpoint: Any) -> Iterator[None]:
    """Where the shop would open its cache: there is none here, and what it
    writes into one is never read back - its cache check reads the staging."""
    yield None


def _nothing_written(*dont_care_arguments: Any) -> None:
    return None


def _a_fresh_shop() -> Any:
    """A shop with nothing staged, flags in memory, and no history to forget."""
    world = state.ScenarioState(
        _AFlag("flag"), _AFlag("fallback"),
        forget_the_flag_history=lambda *arguments, **keywords: None,
        backdate_the_flag_history=lambda *arguments, **keywords: None
    )
    the_app.state = world

    return world


def _what_the_checks_found(world: Any) -> dict[str, Any]:
    """Both checks' findings, as plain values; `None` for a check with nothing
    to ask."""
    found = {"the integrity check": world.the_integrity_check_found(),
             "the cache check": world.the_cache_check_found()}

    return {check: dataclasses.asdict(finding) if finding is not None else None
            for check, finding in found.items()}


def _readings_after(seeded_at: datetime, world: Any) -> list[dict[str, Any]]:
    """The window and the checks' findings at each reading, the window as the
    shop's metrics route would build it."""
    readings = []

    for after in READ_AFTER:
        NOW[0] = seeded_at + after
        readings.append({
            "window": [dataclasses.asdict(minute) for minute in the_app._the_window_now()],
            **_what_the_checks_found(world)
        })

    return readings


def the_shops_world(scenario: Any) -> list[dict[str, Any]]:
    """The scenario seeded by the shop at the anchor."""
    generator.random = random
    world = _a_fresh_shop()
    NOW[0] = AN_ANCHOR
    world.seed(scenario)

    return _readings_after(AN_ANCHOR, world)


def the_stand_ins_world(scenario: Any,
                        anchor: datetime | None,
                        asked_at: datetime) -> tuple[timedelta, list[dict[str, Any]]]:
    """The scenario seeded by the stand-in, asked at `asked_at` with `anchor`
    staged, and how far ahead of the anchor it seeded."""
    draws = ShiftedDraws(random, scenarios.TIMESTAMP_FORMAT)
    own_checks = {check: getattr(state, check) for check in THE_CHECKS}

    def wait(dont_care_seconds: float) -> None:
        NOW[0] += A_LOOK

    try:
        generator.random = draws
        asking_the_checks_as_recorded(state, lambda: draws.shift)
        seeding = Seeding(draws, now=_the_clock, sleep=wait,
                          pin_the_shops_clock=pinning_the_clock_of(state))
        world = _a_fresh_shop()
        NOW[0] = asked_at

        if anchor is not None:
            seeding.stage(anchor)

        seeding.seed(lambda: world.seed(scenario))
        shift = seeding.state().shift

        return shift, _readings_after((anchor or asked_at) + shift, world)
    finally:
        generator.random = random

        for check, own in own_checks.items():
            setattr(state, check, own)


def moved_back(value: Any, shift: timedelta, key: str = "") -> Any:
    """`value` as it would read `shift` earlier."""
    if isinstance(value, datetime):
        return value - shift

    if isinstance(value, str):
        return A_WRITTEN_INSTANT.sub(
            lambda found: (datetime.strptime(found.group(0), scenarios.TIMESTAMP_FORMAT)
                           - shift).strftime(scenarios.TIMESTAMP_FORMAT),
            value
        )

    if isinstance(value, dict):
        return {inner: moved_back(held, shift, inner) for inner, held in value.items()}

    if isinstance(value, list | tuple):
        return type(value)(moved_back(held, shift, key) for held in value)

    if (key.endswith("_time_seconds") and isinstance(value, int | float)
            and not isinstance(value, bool)):
        return value - shift.total_seconds()

    return value


def differences(shops: list[dict[str, Any]],
                stand_ins: list[dict[str, Any]],
                shift: timedelta) -> list[str]:
    """Every field of every minute, and every finding of every check, where the
    stand-in's reading, moved back by `shift`, is not the shop's."""
    found = []

    for after, shop_reading, stand_in_reading in zip(READ_AFTER, shops, stand_ins,
                                                     strict=True):
        found.extend(_window_differences(after, shop_reading["window"],
                                         stand_in_reading["window"], shift))

        for check in ("the integrity check", "the cache check"):
            moved = moved_back(stand_in_reading[check], shift)

            if moved != shop_reading[check]:
                found.append(f"read {after} after the seed, {check}: the shop found "
                             f"[{str(shop_reading[check])[:160]}], the stand-in "
                             f"[{str(moved)[:160]}]")

    return found


def _window_differences(after: timedelta,
                        shop_window: list[dict[str, Any]],
                        stand_in_window: list[dict[str, Any]],
                        shift: timedelta) -> list[str]:
    if len(shop_window) != len(stand_in_window):
        return [f"read {after} after the seed: the shop had "
                f"[{len(shop_window)}] minutes, the stand-in [{len(stand_in_window)}]"]

    found = []

    for shop_minute, stand_in_minute in zip(shop_window, stand_in_window, strict=True):
        moved = moved_back(stand_in_minute, shift)

        for field, held in shop_minute.items():
            if moved.get(field) != held:
                found.append(f"read {after} after the seed, minute "
                             f"[{shop_minute.get('minute_id')}] [{field}]: the shop drew "
                             f"[{str(held)[:80]}], the stand-in [{str(moved.get(field))[:80]}]")

    return found


def compared(label: str,
             drawn: Callable[[], list[str]],
             into: dict[str, list[str]]) -> None:
    """Records what `drawn` found under `label`, or how it failed to draw."""
    try:
        found = drawn()
    except Exception:
        found = [f"raised: {traceback.format_exc().strip().splitlines()[-1]}"]

    into[label] = (found[:SAID_AT_MOST]
                   + ([f"... and {len(found) - SAID_AT_MOST} more"]
                      if len(found) > SAID_AT_MOST else []))


def main() -> int:
    lacking = what_the_shop_lacks(generator, state, scenarios, integrity)
    if lacking:
        print(json.dumps({"lacking": lacking}))
        return 1

    # Every one of the shop's modules that reads the clock, read here instead.
    # `Any`, because what this does is rebind a name in a module of the shop's.
    for name in [name for name in sys.modules if name.startswith("target_app")]:
        shop_module: Any = sys.modules[name]

        if hasattr(shop_module, "utc_now"):
            shop_module.utc_now = _the_clock

    # The cache a failover writes the standby's figures into, written to nowhere.
    state.a_client_for = _no_cache
    state.discard_every_entry = _nothing_written
    state.write_entries = _nothing_written

    found: dict[str, list[str]] = {}
    excluded: dict[str, str] = {}

    for scenario_id, scenario in scenarios.SCENARIOS.items():
        if not scenario.is_generated:
            excluded[scenario_id] = "not generated, so it has no window"
            continue

        def with_nothing_staged(scenario: Any = scenario) -> list[str]:
            shops = the_shops_world(scenario)
            shift, stand_ins = the_stand_ins_world(scenario, None, AN_ANCHOR)

            return differences(shops, stand_ins, shift)

        compared(f"{scenario_id}, nothing staged", with_nothing_staged, found)

        for some_shift in SOME_SHIFTS:
            def from_the_anchor(scenario: Any = scenario,
                                some_shift: timedelta = some_shift) -> list[str]:
                shops = the_shops_world(scenario)
                shift, stand_ins = the_stand_ins_world(
                    scenario, AN_ANCHOR, AN_ANCHOR + some_shift
                )

                return differences(shops, stand_ins, shift)

            compared(f"{scenario_id}, asked {some_shift} later", from_the_anchor, found)

    print(json.dumps({"compared": found, "excluded": excluded}))

    return 0


if __name__ == "__main__":
    sys.exit(main())
