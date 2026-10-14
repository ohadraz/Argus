"""The shop's random draws, as a replay's world takes them.

The shop names every minute's sequence of draws after the minute itself, so a
world seeded at a different time is a different world. Moved back by the shift,
a minute of the replay draws exactly what the recorded minute drew - and nothing
that is not named after a minute moves at all.
"""

from __future__ import annotations

import random
from datetime import timedelta
from typing import Any

import pytest
from argus_testkit import Assertion, Scenario, all_of
from target_service_double.draws import ShiftedDraws

# The shop's own spelling of a minute (`target_app.scenarios.TIMESTAMP_FORMAT`).
THE_SHOPS_MINUTE_FORMAT = "%Y-%m-%dT%H:%M:%SZ"

SOME_SHIFT = timedelta(days=15, hours=5, minutes=39)
A_REPLAYED_MINUTE = "2026-10-14T03:50:00Z"
THE_RECORDED_MINUTE_IT_IS = "2026-09-28T22:11:00Z"

HOW_MANY_DRAWS_TO_COMPARE = 5


@pytest.mark.unit
def test_a_replayed_minute_draws_what_the_recorded_minute_drew() -> None:
    Scenario() \
        .given(draws := _draws_shifted_by(SOME_SHIFT)) \
        .when(lambda: _the_first_draws(draws.Random(A_REPLAYED_MINUTE))) \
        .then(_are_the_draws_of(THE_RECORDED_MINUTE_IT_IS))


@pytest.mark.unit
def test_a_minutes_named_sequences_keep_their_names_when_moved() -> None:
    # The cache and the rollout each draw from a sequence of their own, named
    # after the minute and a suffix. Moving the minute must not lose the suffix,
    # or the cache would draw the main sequence's numbers.
    Scenario() \
        .given(draws := _draws_shifted_by(SOME_SHIFT)) \
        .when(lambda: [
            _the_first_draws(draws.Random(f"{A_REPLAYED_MINUTE}-cache")),
            _the_first_draws(draws.Random(f"{A_REPLAYED_MINUTE}-rollout"))
        ]) \
        .then(_are_the_draws_of_each(f"{THE_RECORDED_MINUTE_IT_IS}-cache",
                                     f"{THE_RECORDED_MINUTE_IT_IS}-rollout"))


@pytest.mark.unit
def test_a_sequence_named_after_anything_but_a_minute_is_left_alone() -> None:
    # The shop's shoppers draw from their own names, which no clock moves.
    some_shopper = "shopper-7"

    Scenario() \
        .given(draws := _draws_shifted_by(SOME_SHIFT)) \
        .when(lambda: _the_first_draws(draws.Random(some_shopper))) \
        .then(_are_the_draws_of(some_shopper))


@pytest.mark.unit
def test_with_no_shift_every_minute_draws_its_own() -> None:
    # What a fresh recording and an unstaged seed see: the shop, unchanged.
    Scenario() \
        .given(draws := _draws_shifted_by(timedelta(0))) \
        .when(lambda: _the_first_draws(draws.Random(A_REPLAYED_MINUTE))) \
        .then(_are_the_draws_of(A_REPLAYED_MINUTE))


@pytest.mark.unit
def test_everything_but_a_named_sequence_is_the_random_module_itself() -> None:
    Scenario() \
        .given(draws := _draws_shifted_by(SOME_SHIFT)) \
        .when(lambda: draws.choice) \
        .then(_is(random.choice))


def _draws_shifted_by(shift: timedelta) -> ShiftedDraws:
    draws = ShiftedDraws(random, THE_SHOPS_MINUTE_FORMAT)
    draws.shift = shift

    return draws


def _the_first_draws(sequence: random.Random) -> list[float]:
    return [sequence.random() for _ in range(HOW_MANY_DRAWS_TO_COMPARE)]


def _are_the_draws_of(seed: str) -> Assertion[list[float]]:
    def assertion(drawn: list[float]) -> bool:
        expected = _the_first_draws(random.Random(seed))

        if drawn != expected:
            raise AssertionError(
                f"Expected the draws of the sequence named [{seed}], {expected}, "
                f"got {drawn}."
            )

        return True

    return assertion


def _are_the_draws_of_each(*seeds: str) -> Assertion[list[list[float]]]:
    def assertion(drawn: list[list[float]]) -> bool:
        return all_of(*(
            _the_nth_is_the_draws_of(position, seed)
            for position, seed in enumerate(seeds)
        ))(drawn)

    return assertion


def _the_nth_is_the_draws_of(position: int, seed: str) -> Assertion[list[list[float]]]:
    def assertion(drawn: list[list[float]]) -> bool:
        return _are_the_draws_of(seed)(drawn[position])

    return assertion


def _is(expected: Any) -> Assertion[Any]:
    def assertion(actual: Any) -> bool:
        if actual is not expected:
            raise AssertionError(f"Expected [{expected!r}] itself, got [{actual!r}].")

        return True

    return assertion
