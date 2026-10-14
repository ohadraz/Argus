"""The shop's checks, asked the question the recording asked them.

The shop's integrity checks hang every purchase on a grid anchored at a fixed
instant, so a world moved by the shift would find other purchases than the
recorded one found: another shopper, another amount, an onset off the flag's
minute. Asked with every instant handed in moved back by the shift, a check
answers as it answered when the set was recorded, and that answer is moved
forward into the replay's time. Only instants move - never a shopper, an amount
or a count.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from argus_testkit import Assertion, Scenario, calling
from target_service_double.checks import asked_as_recorded

SOME_SHIFT = timedelta(days=15, hours=2, minutes=7)
SOME_INSTANT = datetime(2026, 10, 14, 3, 50, 43, 502554, tzinfo=UTC)
SOME_EARLIER_INSTANT = datetime(2026, 10, 14, 2, 50, 43, 502554, tzinfo=UTC)
SOME_EARLIEST_INSTANT = datetime(2026, 10, 14, 1, 10, tzinfo=UTC)


@dataclass(frozen=True)
class _APurchase:
    """Stands for the shop's `Purchase`: what it cost and when it was recorded."""

    price_cents: int
    recorded_at: datetime


@dataclass(frozen=True)
class _AnAccount:
    """Stands for the shop's `Account`: a shopper and their purchases."""

    shopper_id: str
    purchases: tuple[_APurchase, ...]


@dataclass(frozen=True)
class _AStretch:
    """Stands for the shop's `FlagTimeline`: when a flag went on and off, and the
    stretches before this one."""

    turned_on_at: datetime
    turned_off_at: datetime | None = None
    earlier: tuple[_AStretch, ...] = ()


class _ACheck:
    """A check that keeps what it was asked and answers with what it was given."""

    def __init__(self, answer: Any = None) -> None:
        self.asked: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        self._answer = answer

    def __call__(self, *arguments: Any, **keywords: Any) -> Any:
        self.asked.append((arguments, keywords))

        return self._answer


@pytest.mark.unit
def test_the_check_is_asked_at_the_recorded_instant() -> None:
    check = _ACheck()

    Scenario() \
        .given(asked := asked_as_recorded(check, lambda: SOME_SHIFT)) \
        .when(lambda: _what_it_was_asked(check, asked, None, now=SOME_INSTANT)) \
        .then(_was_asked((None,), {"now": SOME_INSTANT - SOME_SHIFT}))


@pytest.mark.unit
def test_a_stretch_handed_in_is_asked_about_as_recorded() -> None:
    # The flag the cheaper write path rode on went on in the replay's time; the
    # check is asked about the stretch the recording saw, every turn of it.
    check = _ACheck()
    stretch = _AStretch(turned_on_at=SOME_EARLIER_INSTANT,
                        earlier=(_AStretch(turned_on_at=SOME_EARLIEST_INSTANT,
                                           turned_off_at=SOME_EARLIER_INSTANT),))

    Scenario() \
        .given(asked := asked_as_recorded(check, lambda: SOME_SHIFT)) \
        .when(lambda: _what_it_was_asked(check, asked, stretch, SOME_INSTANT)) \
        .then(_was_asked(
            (_AStretch(turned_on_at=SOME_EARLIER_INSTANT - SOME_SHIFT,
                       earlier=(_AStretch(
                           turned_on_at=SOME_EARLIEST_INSTANT - SOME_SHIFT,
                           turned_off_at=SOME_EARLIER_INSTANT - SOME_SHIFT
                       ),)),
             SOME_INSTANT - SOME_SHIFT),
            {}
        ))


@pytest.mark.unit
def test_every_instant_in_the_answer_is_moved_into_the_replays_time() -> None:
    # The answer is the recording's purchases: the same shoppers and amounts,
    # recorded the shift later.
    some_answer = [_AnAccount(shopper_id="shopper-30", purchases=(
        _APurchase(price_cents=129731, recorded_at=SOME_EARLIEST_INSTANT),
        _APurchase(price_cents=500, recorded_at=SOME_EARLIER_INSTANT)
    ))]

    Scenario() \
        .given(asked := asked_as_recorded(_ACheck(some_answer), lambda: SOME_SHIFT)) \
        .when(lambda: asked(None, SOME_INSTANT)) \
        .then(_answers([_AnAccount(shopper_id="shopper-30", purchases=(
            _APurchase(price_cents=129731,
                       recorded_at=SOME_EARLIEST_INSTANT + SOME_SHIFT),
            _APurchase(price_cents=500, recorded_at=SOME_EARLIER_INSTANT + SOME_SHIFT)
        ))]))


@pytest.mark.unit
def test_an_answer_held_by_shopper_keeps_its_shoppers() -> None:
    some_answer = {"shopper-30": _APurchase(price_cents=842, recorded_at=SOME_INSTANT)}

    Scenario() \
        .given(asked := asked_as_recorded(_ACheck(some_answer), lambda: SOME_SHIFT)) \
        .when(lambda: asked(SOME_INSTANT)) \
        .then(_answers({"shopper-30": _APurchase(price_cents=842,
                                                 recorded_at=SOME_INSTANT + SOME_SHIFT)}))


@pytest.mark.unit
def test_with_no_shift_the_check_is_asked_and_answers_untouched() -> None:
    # What a fresh recording and an unstaged seed see: the shop, unchanged.
    some_answer = [_AnAccount(shopper_id="shopper-30", purchases=())]

    Scenario() \
        .given(asked := asked_as_recorded(_ACheck(some_answer), lambda: timedelta(0))) \
        .when(lambda: asked(None, SOME_INSTANT)) \
        .then(_is(some_answer))


@pytest.mark.unit
def test_the_shift_is_the_one_in_force_when_the_check_is_asked() -> None:
    # The stand-in wraps the checks when it starts, before any seed has moved
    # the world - so a shift read then would be nothing, for good.
    check = _ACheck()
    shift = [timedelta(0)]
    asked = asked_as_recorded(check, lambda: shift[0])

    Scenario() \
        .given(calling(lambda: shift.__setitem__(0, SOME_SHIFT))) \
        .when(lambda: _what_it_was_asked(check, asked, None, SOME_INSTANT)) \
        .then(_was_asked((None, SOME_INSTANT - SOME_SHIFT), {}))


def _what_it_was_asked(check: _ACheck,
                       asked: Callable[..., Any],
                       *arguments: Any,
                       **keywords: Any) -> tuple[tuple[Any, ...], dict[str, Any]]:
    asked(*arguments, **keywords)

    return check.asked[-1]


def _was_asked(arguments: tuple[Any, ...],
               keywords: dict[str, Any]) -> Assertion[tuple[tuple[Any, ...], dict[str, Any]]]:
    def assertion(asked: tuple[tuple[Any, ...], dict[str, Any]]) -> bool:
        if asked != (arguments, keywords):
            raise AssertionError(
                f"Expected the check asked with {arguments} and {keywords}, and it "
                f"was asked with {asked[0]} and {asked[1]}."
            )

        return True

    return assertion


def _answers(expected: Any) -> Assertion[Any]:
    def assertion(answer: Any) -> bool:
        if answer != expected:
            raise AssertionError(f"Expected the answer {expected}, and it was {answer}.")

        return True

    return assertion


def _is(expected: Any) -> Assertion[Any]:
    def assertion(actual: Any) -> bool:
        if actual is not expected:
            raise AssertionError(f"Expected [{expected!r}] itself, got [{actual!r}].")

        return True

    return assertion
