from __future__ import annotations

import os
from datetime import UTC, datetime
from functools import cache

from core.clock import Clock, the_clock_named_by

TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


@cache
def the_clock() -> Clock:
    """This process's clock, named by the environment the first time it is
    asked for, and the same clock every time after.

    Named once: a stack sets the epoch and speed before it starts anything, and
    a clock that could change under a running walk would have two readings of
    one instant disagree. On first use rather than at import, so that naming
    the kernel reads nothing - and each process's root asks for it first thing
    in `main`, so that a stack configured by half is refused as the process
    starts, not at the first timestamp a walk writes.
    """
    return the_clock_named_by(os.environ)


def utc_now() -> datetime:
    """Now, in UTC - and a seam a test can replace with a clock that does not
    actually wait.

    Here rather than in whichever module first needed to know the time. Two
    agents and a page all measure against the same instant, and a clock kept
    inside one of them is a clock the others import an agent to read.

    The stack's clock rather than the wall's: the real one wherever nothing says
    otherwise, and a faster one where a stack runs on simulated time - see
    `core.clock`.
    """
    return the_clock().now()


def sleep_on_the_clock(seconds: float) -> None:
    """Waits `seconds` of the stack's clock - see `Clock.sleep` for which waits
    those are."""
    the_clock().sleep(seconds)


def in_real_time(seconds: float) -> float:
    """How long `seconds` of the stack's clock lasts on the real one - see
    `Clock.in_real_time`."""
    return the_clock().in_real_time(seconds)


def to_iso(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime(TIMESTAMP_FORMAT)


def to_iso_minute(moment: datetime) -> str:
    """The minute `moment` falls in, in wire format - the instant truncated.
    """
    return to_iso(moment.replace(second=0, microsecond=0))


def parse_iso(value: str) -> datetime:
    """Reads an ISO-8601 instant, treating a naive one as UTC.

    Raises `ValueError` when `value` is not a timestamp at all.
    """
    parsed = datetime.fromisoformat(value)

    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
