"""Where the stand-in reaches into the shop, and the check that it still can.

The stand-in changes names in the shop's modules: the `random` its generator
draws from, the `utc_now` its state reads when it seeds, and the integrity
checks its state asks, which hang purchases on a grid no clock moves. A shop
that stopped reaching those through those names - a `from random import Random`,
a clock read by value from somewhere else, a check asked by another name - would
be served unchanged and silently, so the stand-in refuses to start on one
instead.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from types import ModuleType
from typing import Any

import pytest
from argus_testkit import Assertion, Scenario
from target_service_double.shop import (
    asking_the_checks_as_recorded,
    pinning_the_clock_of,
    what_the_shop_lacks,
)

SOME_INSTANT = datetime(2026, 10, 14, 3, 50, 43, 502554, tzinfo=UTC)
SOME_SHIFT = timedelta(days=15, hours=2, minutes=7)

# Where a check's grid puts a purchase, whenever it is asked.
A_PURCHASE_ON_THE_GRID = datetime(2026, 10, 14, 2, 0, tzinfo=UTC)

THE_CHECKS = (
    "what_the_check_found",
    "the_accounts_the_check_examines",
    "the_figures_the_promoted_standby_holds"
)


def _the_scenarios_clock() -> datetime:
    return datetime(2000, 1, 1, tzinfo=UTC)


def _another_clock() -> datetime:
    return datetime(2001, 1, 1, tzinfo=UTC)


def _a_check_on_its_grid(*dont_care_arguments: Any) -> datetime:
    return A_PURCHASE_ON_THE_GRID


def _another_check(*dont_care_arguments: Any) -> datetime:
    return A_PURCHASE_ON_THE_GRID


def _a_module(name: str, **names: object) -> ModuleType:
    module = ModuleType(name)
    for attribute, value in names.items():
        setattr(module, attribute, value)

    return module


def _a_shop_as_the_stand_in_needs_it(
        state_reading: Callable[[], datetime] = _the_scenarios_clock
) -> tuple[ModuleType, ModuleType, ModuleType, ModuleType]:
    scenarios = _a_module("target_app.scenarios", utc_now=_the_scenarios_clock)
    checks = {name: _a_check_on_its_grid for name in THE_CHECKS}
    integrity = _a_module("target_app.integrity", **checks)
    state = _a_module("target_app.state", utc_now=state_reading, **checks)
    generator = _a_module("target_app.generator", random=random)

    return generator, state, scenarios, integrity


@pytest.mark.unit
def test_a_shop_whose_draws_seed_clock_and_checks_the_stand_in_can_reach_lacks_nothing() -> None:
    generator, state, scenarios, integrity = _a_shop_as_the_stand_in_needs_it()

    Scenario() \
        .given(generator) \
        .when(lambda: what_the_shop_lacks(generator, state, scenarios, integrity)) \
        .then(_lacks(nothing=True))


@pytest.mark.unit
def test_a_generator_holding_its_draws_by_another_name_is_reported() -> None:
    # `from random import Random` would leave the generator's draws where the
    # stand-in cannot move them.
    _, state, scenarios, integrity = _a_shop_as_the_stand_in_needs_it()
    generator = _a_module("target_app.generator", Random=random.Random)

    Scenario() \
        .given(generator) \
        .when(lambda: what_the_shop_lacks(generator, state, scenarios, integrity)) \
        .then(_lacks(naming="target_app.generator.random"))


@pytest.mark.unit
def test_a_state_reading_another_clock_is_reported() -> None:
    generator, state, scenarios, integrity = _a_shop_as_the_stand_in_needs_it(
        state_reading=_another_clock
    )

    Scenario() \
        .given(state) \
        .when(lambda: what_the_shop_lacks(generator, state, scenarios, integrity)) \
        .then(_lacks(naming="target_app.state.utc_now"))


@pytest.mark.unit
@pytest.mark.parametrize("check", THE_CHECKS)
def test_a_state_asking_a_check_that_is_not_the_integrity_modules_own_is_reported(
        check: str) -> None:
    # A check moved out of `state`, or asked through a name of its own, would
    # answer on the shop's grid however the stand-in rebinds `state`'s.
    generator, state, scenarios, integrity = _a_shop_as_the_stand_in_needs_it()
    setattr(state, check, _another_check)

    Scenario() \
        .given(state) \
        .when(lambda: what_the_shop_lacks(generator, state, scenarios, integrity)) \
        .then(_lacks(naming=f"target_app.state.{check}"))


@pytest.mark.unit
@pytest.mark.parametrize("check", THE_CHECKS)
def test_a_check_the_shop_no_longer_has_is_reported(check: str) -> None:
    generator, state, scenarios, integrity = _a_shop_as_the_stand_in_needs_it()
    delattr(state, check)
    delattr(integrity, check)

    Scenario() \
        .given(state) \
        .when(lambda: what_the_shop_lacks(generator, state, scenarios, integrity)) \
        .then(_lacks(naming=f"target_app.state.{check}"))


@pytest.mark.unit
@pytest.mark.parametrize("check", THE_CHECKS)
def test_once_asked_as_recorded_a_check_answers_in_the_replays_time(check: str) -> None:
    _, state, _, _ = _a_shop_as_the_stand_in_needs_it()

    Scenario() \
        .given(state) \
        .when(lambda: _asked_after_rebinding(state, check, SOME_SHIFT)) \
        .then(_reads(A_PURCHASE_ON_THE_GRID + SOME_SHIFT))


@pytest.mark.unit
def test_while_pinned_the_shop_reads_its_clock_as_the_instant() -> None:
    _, state, _, _ = _a_shop_as_the_stand_in_needs_it()

    Scenario() \
        .given(state) \
        .when(lambda: _read_while_pinned(state, SOME_INSTANT)) \
        .then(_reads(SOME_INSTANT))


@pytest.mark.unit
def test_once_unpinned_the_shop_reads_its_own_clock_again() -> None:
    _, state, _, _ = _a_shop_as_the_stand_in_needs_it()

    Scenario() \
        .given(state) \
        .when(lambda: _read_after_pinning(state, SOME_INSTANT)) \
        .then(_reads(_the_scenarios_clock()))


@pytest.mark.unit
def test_a_failure_while_pinned_still_gives_the_shop_its_own_clock_back() -> None:
    _, state, _, _ = _a_shop_as_the_stand_in_needs_it()

    Scenario() \
        .given(state) \
        .when(lambda: _read_after_failing_while_pinned(state, SOME_INSTANT)) \
        .then(_reads(_the_scenarios_clock()))


def _asked_after_rebinding(state: ModuleType, check: str, shift: timedelta) -> datetime:
    asking_the_checks_as_recorded(state, lambda: shift)
    asked: Callable[..., datetime] = getattr(state, check)

    return asked(None, SOME_INSTANT)


def _read_while_pinned(state: ModuleType, instant: datetime) -> datetime:
    with pinning_the_clock_of(state)(instant):
        clock: Callable[[], datetime] = state.utc_now
        return clock()


def _read_after_pinning(state: ModuleType, instant: datetime) -> datetime:
    with pinning_the_clock_of(state)(instant):
        pass

    clock: Callable[[], datetime] = state.utc_now
    return clock()


def _read_after_failing_while_pinned(state: ModuleType, instant: datetime) -> datetime:
    try:
        with pinning_the_clock_of(state)(instant):
            raise RuntimeError("the seed failed")
    except RuntimeError:
        pass

    clock: Callable[[], datetime] = state.utc_now
    return clock()


def _lacks(nothing: bool = False, naming: str | None = None) -> Assertion[list[str]]:
    def assertion(lacking: list[str]) -> bool:
        if nothing and lacking:
            raise AssertionError(f"Expected the shop to lack nothing, and it lacks {lacking}.")

        if naming is not None and not any(naming in reason for reason in lacking):
            raise AssertionError(
                f"Expected the shop reported as lacking [{naming}], and it was "
                f"reported as lacking {lacking}."
            )

        return True

    return assertion


def _reads(expected: datetime) -> Assertion[datetime]:
    def assertion(read: datetime) -> bool:
        if read != expected:
            raise AssertionError(
                f"Expected the shop to read [{expected.isoformat()}], "
                f"and it read [{read.isoformat()}]."
            )

        return True

    return assertion
