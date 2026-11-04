"""When a log line was logged, read from the stamp it opens with.

Its own module because two readers need it and one of them is read by the
other: the log groups say each message once and name which reach into a
stretch the metrics did not cover, and the figures name how far they reach - and
the log groups already read the figures to tell a quantity from a name.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Final

from argus_core import parse_iso

# The instant a log line opens with, in the service's own wire format: to the
# minute, the second or a fraction of one, in UTC or at an offset - as the read
# tier reads a stamp. A date alone is no stamp.
_STAMPED: Final = re.compile(
    r"^(\d{4}-\d\d-\d\dT\d\d:\d\d(?::\d\d(?:\.\d+)?)?(?:Z|[+-]\d\d:\d\d)?)\s+")


def stamped(line: str) -> tuple[datetime | None, str]:
    """When a line was logged, and what it said.

    Read as the instant the stamp names, a minute alone naming its start, and
    one written with no zone as UTC's, as the read tier reads it: a service
    logging to the millisecond, or with an offset, had lines with no stamp at
    all."""
    opening = _STAMPED.match(line)
    if opening is None:
        return None, line

    return parse_iso(opening.group(1)), line[opening.end():]


def the_minute_inside(logged_at: datetime | None, since: datetime) -> datetime | None:
    """The minute a line was stamped with, where that minute is inside a
    stretch that began at `since` and has not ended - or `None` for one before
    it, or one with no stamp.

    A line is stamped with its minute and taken as the whole of it, so one from
    the minute `since` falls in is inside. Exact for the stretch it is asked
    about, whose start is the first minute the metrics did not cover. No end is
    asked for because that stretch had none - it was still running when Argus
    stopped. A line with no stamp is inside nothing, since naming it would say
    it was logged inside.
    """
    if logged_at is None:
        return None

    # In UTC: a stamp written at an offset names the same instant, and its
    # minute is the one UTC's clock reads.
    in_utc = (logged_at if logged_at.tzinfo is not None
              else logged_at.replace(tzinfo=UTC)).astimezone(UTC)
    minute = in_utc.replace(second=0, microsecond=0)

    return minute if minute >= since.replace(second=0, microsecond=0) else None


def the_last_minute_logged_inside(log_lines: Sequence[str], since: datetime) -> datetime | None:
    """The latest minute a line was logged in, of the lines logged inside a
    stretch that began at `since` - or `None` where none was.

    The latest stamp rather than the last line, since lines are not read in the
    order they were logged. Decided by `the_minute_inside`, as which groups
    reach in is, so a stretch some group reaches into always has a last minute
    to say.
    """
    inside = [minute for line in log_lines
              if (minute := the_minute_inside(stamped(line)[0], since)) is not None]

    return max(inside, default=None)
