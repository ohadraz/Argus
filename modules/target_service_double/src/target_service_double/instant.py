"""When a replayed scenario is seeded.

The recording's own instant, moved by whole minutes. Whole, because the shop
draws each minute from the minute's own name, so only a world moved by whole
minutes is the recorded one under new names. The seconds and microseconds stay
as recorded, because the shop dates the first minute of an outage by them.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Final

_A_MINUTE: Final = timedelta(minutes=1)


def the_seed_instant(anchor: datetime, now: datetime) -> datetime:
    """The first instant at or after `now` that is `anchor` moved by whole minutes.

    Never behind `now`, because the seed happens at that instant and the clock
    cannot be waited back. Less than a minute ahead of it, because every minute
    more is a minute of the replay spent waiting.
    """
    # Rounded up in whole minutes, in integer arithmetic: a float division here
    # could land a hair either side of an exact match and move it a minute.
    minutes_to_move = -((anchor - now) // _A_MINUTE)

    return anchor + minutes_to_move * _A_MINUTE
