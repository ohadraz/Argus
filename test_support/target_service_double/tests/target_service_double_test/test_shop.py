"""Where the stand-in reaches into the shop.

The stand-in changes names in the shop's modules, and one of them is the
`utc_now` its state reads when it seeds: pinned for the length of a seed, so a
world seeded from an anchor is seeded at the instant the anchor's world was.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from types import ModuleType

import pytest
from argus_testkit import Assertion, Scenario
from target_service_double.shop import pinning_the_clock_of

SOME_INSTANT = datetime(2026, 10, 14, 3, 50, 43, 502554, tzinfo=UTC)


def _the_shops_own_clock() -> datetime:
    return datetime(2000, 1, 1, tzinfo=UTC)


@pytest.mark.unit
def test_while_pinned_the_shop_reads_its_clock_as_the_instant() -> None:
    # Here rather than only in the contract suite, whose clock lands on the seed
    # instant by its own steps whether or not the shop's was pinned there.
    state = _a_module("target_app.state", utc_now=_the_shops_own_clock)

    Scenario() \
        .given(state) \
        .when(lambda: _read_while_pinned(state, SOME_INSTANT)) \
        .then(_reads(SOME_INSTANT))


def _a_module(name: str, **names: object) -> ModuleType:
    module = ModuleType(name)
    for attribute, value in names.items():
        setattr(module, attribute, value)

    return module


def _read_while_pinned(state: ModuleType, instant: datetime) -> datetime:
    with pinning_the_clock_of(state)(instant):
        clock: Callable[[], datetime] = state.utc_now
        return clock()


def _reads(expected: datetime) -> Assertion[datetime]:
    def assertion(read: datetime) -> bool:
        if read != expected:
            raise AssertionError(
                f"Expected the shop to read [{expected.isoformat()}], "
                f"and it read [{read.isoformat()}]."
            )

        return True

    return assertion
