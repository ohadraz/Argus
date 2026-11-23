"""Holding a run's claim, and knowing when a failure says the run was lost.

The database is what refuses a write whose run has moved on, and the cases that
ask a live one are `postgres`'s. These are the kernel's half: which claim a
process holds and for how long, how a claim is spoken and heard back, and
whether a failure - however it reached the caller, and whichever driver carried
the database's refusal - says the run was lost.
"""

from __future__ import annotations

from typing import Any

import pytest
from argus_testkit import Assertion, Scenario, attempting, calling
from core import Fence, Holding, RunLost, was_lost

# Refused because the run the write was made for is somebody else's now. Stated
# here rather than imported: it is the database's word, and a test sharing the
# kernel's constant would pass through a change that broke the agreement.
RUN_LOST = "AR001"

# Refused because a worker wrote without saying which run it writes for.
NO_RUN_HELD = "AR002"


@pytest.mark.unit
@pytest.mark.parametrize("told", ["directly", "as-the-cause", "while-handling-it"])
def test_a_lost_run_is_recognised_however_it_reached_the_caller(told: str) -> None:
    # A store refusing a write raises inside whatever was writing, and that is
    # often caught and raised again as something of its own.
    Scenario() \
        .given(
            error := _a_lost_run_told(told)
        ) \
        .when(
            lambda: was_lost(error)
        ) \
        .then(
            _the_answer_is(True)
        )


@pytest.mark.unit
def test_a_failure_that_says_nothing_of_the_run_is_not_a_lost_run() -> None:
    Scenario() \
        .given(
            error := RuntimeError("some failure nobody planned for")
        ) \
        .when(
            lambda: was_lost(error)
        ) \
        .then(
            _the_answer_is(False)
        )


@pytest.mark.unit
def test_a_refusal_carrying_the_lost_runs_state_is_a_lost_run() -> None:
    # The kernel names no driver: what it reads is the database's own word for
    # the refusal, off whatever carried it.
    Scenario() \
        .given(
            error := _ADriversRefusal(RUN_LOST)
        ) \
        .when(
            lambda: was_lost(error)
        ) \
        .then(
            _the_answer_is(True)
        )


@pytest.mark.unit
def test_a_refusal_carrying_another_state_is_not_a_lost_run() -> None:
    # A worker writing for no run is refused too, and that is a bug rather than
    # a lost run - so the state is read, not merely found to be there.
    Scenario() \
        .given(
            error := _ADriversRefusal(NO_RUN_HELD)
        ) \
        .when(
            lambda: was_lost(error)
        ) \
        .then(
            _the_answer_is(False)
        )


@pytest.mark.unit
def test_a_run_is_held_only_for_as_long_as_it_is_walked() -> None:
    some_fence = Fence(run_id="6f1c1d2e-0000-4000-8000-000000000001", epoch=3)
    holding = Holding()
    seen: list[Fence | None] = []

    def walked_until_it_fails() -> None:
        with holding.of(some_fence):
            seen.append(holding.current())

            raise RuntimeError("dont care")

    Scenario() \
        .given(
            calling(lambda: seen.append(holding.current()))
        ) \
        .when(attempting(walked_until_it_fails)) \
        .then(
            lambda _: _held_in_turn(seen + [holding.current()], [None, some_fence, None])
        )


@pytest.mark.unit
def test_a_run_s_last_try_is_known_only_for_as_long_as_it_is_walked() -> None:
    # What the walk writes on a run's last try has no later try to wait for;
    # said after it, the next run would be taken for its last.
    some_fence = Fence(run_id="6f1c1d2e-0000-4000-8000-000000000001", epoch=3)
    holding = Holding()
    seen: list[bool] = []

    def walked_on_its_last_try_until_it_fails() -> None:
        with holding.of(some_fence, last_try=True):
            seen.append(holding.on_its_last_try())

            raise RuntimeError("dont care")

    Scenario() \
        .given(
            calling(lambda: seen.append(holding.on_its_last_try()))
        ) \
        .when(attempting(walked_on_its_last_try_until_it_fails)) \
        .then(
            lambda _: _last_try_in_turn(seen + [holding.on_its_last_try()],
                                        [False, True, False])
        )


@pytest.mark.unit
def test_an_action_is_acted_for_only_for_as_long_as_it_is_being_taken() -> None:
    # Whatever the write tier is asked while it is taken carries its id, and
    # nothing asked after it does - however the taking ended. An action left
    # acted for would put its id on the next one's writes.
    some_action_id = "6f1c1d2e-0000-4000-8000-0000000000a1"
    holding = Holding()
    seen: list[str | None] = []

    def taken_until_it_fails() -> None:
        with holding.acting_for(some_action_id):
            seen.append(holding.current_action())

            raise RuntimeError("dont care")

    Scenario() \
        .given(
            calling(lambda: seen.append(holding.current_action()))
        ) \
        .when(attempting(taken_until_it_fails)) \
        .then(
            lambda _: _acted_for_in_turn(seen + [holding.current_action()],
                                         [None, some_action_id, None])
        )


@pytest.mark.unit
def test_an_action_is_acted_for_inside_the_run_holding_it_and_leaves_the_run_held() -> None:
    # Two things held, each for its own block: an action ending is not the run
    # ending, and the walk's writes after it are still the run's.
    some_fence = Fence(run_id="6f1c1d2e-0000-4000-8000-000000000001", epoch=3)
    some_action_id = "6f1c1d2e-0000-4000-8000-0000000000a1"
    holding = Holding()
    seen: list[tuple[Fence | None, str | None]] = []

    def walked_and_acting() -> None:
        with holding.of(some_fence):
            with holding.acting_for(some_action_id):
                seen.append((holding.current(), holding.current_action()))

            seen.append((holding.current(), holding.current_action()))

    Scenario() \
        .when(walked_and_acting) \
        .then(
            lambda _: _held_and_acted_for_in_turn(
                seen, [(some_fence, some_action_id), (some_fence, None)]
            )
        )


@pytest.mark.unit
def test_a_fence_is_heard_back_as_the_claim_it_was_spoken_for() -> None:
    # Spoken by a worker onto its connections and into its calls to the write
    # tier, and heard by the tier deciding whether to make a change - two
    # processes, and one spelling between them.
    some_fence = Fence(run_id="6f1c1d2e-0000-4000-8000-000000000001", epoch=3)

    Scenario() \
        .given(
            some_fence
        ) \
        .when(
            lambda: Fence.heard(some_fence.spoken())
        ) \
        .then(
            _heard_as(some_fence)
        )


@pytest.mark.unit
@pytest.mark.parametrize("spoken", ["", "6f1c1d2e-no-epoch", "6f1c1d2e:three", ":3",
                                    "6f1c1d2e:²"],
                         ids=["nothing", "no-epoch", "epoch-not-a-number", "no-run",
                              "epoch-not-an-ascii-digit"])
def test_what_is_not_a_fence_is_heard_as_none(spoken: str) -> None:
    # Heard from whatever a caller sent, so a caller that sent something else
    # is told it named no run rather than having a run made up for it.
    Scenario() \
        .given(
            spoken
        ) \
        .when(
            lambda: Fence.heard(spoken)
        ) \
        .then(
            _heard_as(None)
        )


class _ADriversRefusal(Exception):
    """A refusal as a database driver raises one, carrying the SQLSTATE the
    database refused with - of no real driver's class, so that what is matched
    is the state and not the class."""

    def __init__(self, sqlstate: str) -> None:
        super().__init__(f"refused as [{sqlstate}]")
        self.sqlstate = sqlstate


def _a_lost_run_told(told: str) -> Exception:
    """A lost run as the caller meets it: itself, the cause a wrapper names, or
    what the wrapper was raised while handling."""
    lost = RunLost("a newer claim holds this run")

    if told == "directly":
        return lost

    wrapped = RuntimeError("the node could not record its finding")

    if told == "as-the-cause":
        wrapped.__cause__ = lost
    else:
        wrapped.__context__ = lost

    return wrapped


def _the_answer_is(expected: bool) -> Assertion[Any]:
    def assertion(answer: Any) -> bool:
        if answer is not expected:
            raise AssertionError(f"Expected [{expected}], got [{answer}].")

        return True

    return assertion


def _heard_as(expected: Fence | None) -> Assertion[Fence | None]:
    def assertion(heard: Fence | None) -> bool:
        if heard != expected:
            raise AssertionError(f"Expected it heard as [{expected}], got [{heard}].")

        return True

    return assertion


def _held_in_turn(seen: list[Fence | None], expected: list[Fence | None]) -> bool:
    if seen != expected:
        raise AssertionError(
            f"Expected nothing held before the walk, its run during it and nothing "
            f"after, {expected}; got {seen}."
        )

    return True


def _last_try_in_turn(seen: list[bool], expected: list[bool]) -> bool:
    if seen != expected:
        raise AssertionError(
            f"Expected no last try before the walk, its run's during it and none "
            f"after, {expected}; got {seen}."
        )

    return True


def _acted_for_in_turn(seen: list[str | None], expected: list[str | None]) -> bool:
    if seen != expected:
        raise AssertionError(
            f"Expected no action before it was taken, its id while it was and none "
            f"after, {expected}; got {seen}."
        )

    return True


def _held_and_acted_for_in_turn(seen: list[tuple[Fence | None, str | None]],
                                expected: list[tuple[Fence | None, str | None]]) -> bool:
    if seen != expected:
        raise AssertionError(
            f"Expected the run held throughout and the action only while it was "
            f"taken, {expected}; got {seen}."
        )

    return True
