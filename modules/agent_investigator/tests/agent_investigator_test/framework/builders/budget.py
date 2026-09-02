"""The bounds one investigation runs under, as a test sets them.

Generous by default and narrowed by the one test that is about a bound: a
budget that binds in a test that did not ask for it would end the
investigation for a reason the test never mentions, and the failure would read
as a loop bug.
"""

from __future__ import annotations

from collections.abc import Callable

from agent_investigator.budget import Budget

ROOM_TO_SPARE_IN_TOOL_CALLS = 99
ROOM_TO_SPARE_IN_TOKENS = 1_000_000
ROOM_TO_SPARE_IN_SECONDS = 3600.0
# Past every bound a test can set, so a clock reading it has run out whatever
# budget the test gave - and no test has to pick a number bigger than its own.
LONGER_THAN_ANY_BOUND = ROOM_TO_SPARE_IN_SECONDS + 1


def a_budget(tool_calls: int = ROOM_TO_SPARE_IN_TOOL_CALLS,
             tokens: int = ROOM_TO_SPARE_IN_TOKENS,
             seconds: float = ROOM_TO_SPARE_IN_SECONDS,
             now: Callable[[], float] | None = None) -> Budget:
    return Budget(
        max_tool_calls=tool_calls,
        max_tokens=tokens,
        max_seconds=seconds,
        now=now or a_clock_that_never_moves()
    )


def a_clock_that_never_moves() -> Callable[[], float]:
    """A clock that makes elapsed time zero, so only the test's own bound binds."""
    return lambda: 0.0


def a_clock_that_runs_out_after(looks: int) -> Callable[[], float]:
    """A clock that stays inside every bound for `looks` readings, then reads
    past all of them for ever after.

    The budget takes its first reading when it is built, so `looks` is the
    number of turns an investigation gets before the clock ends it. Counted in
    looks rather than seconds because where in a run the clock ran out is what
    a time-bound test is about; what the readings were is not.
    """
    within_bounds = iter([0.0] * looks)

    def clock() -> float:
        return next(within_bounds, LONGER_THAN_ANY_BOUND)

    return clock


def a_clock_that_runs_out_after_one_look() -> Callable[[], float]:
    """A clock that leaves an investigation one turn and no more.

    Named for the case rather than spelled out at each call site: a test about
    what happens with nothing left to spend should say that, not do the
    arithmetic.
    """
    return a_clock_that_runs_out_after(looks=1)


def a_clock_that_reads(*readings: float) -> Callable[[], float]:
    """A clock returning these readings in order, the last one for ever after.

    The last one repeats rather than running out because how many times the
    budget looks at the clock is the loop's business, not the test's - a test
    that had to count the readings would be asserting an implementation detail
    it does not care about.
    """
    remaining = list(readings)

    def clock() -> float:
        return remaining.pop(0) if len(remaining) > 1 else remaining[0]

    return clock
