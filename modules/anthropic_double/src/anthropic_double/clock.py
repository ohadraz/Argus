"""Clock times inside a recorded answer, found and moved.

A recorded answer names instants frozen at capture, and a replay runs in a
world seeded later. Moving them is shared by two parties: the harness, which
moves every time in an answer by how far the world has moved before it seeds
the answer, and the double, which moves a few marked times again when the
answer is served, by how late its question arrived. One reading of what a
clock time looks like, so the two can never disagree about which strings are
times.

Takes values and returns values; knows no scenario.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any, Final

# A clock time as a recorded answer writes one: a whole instant, a date alone,
# or a time of day alone. The instant is tried first, so its time is never read
# a second time as a time of day standing on its own.
_A_CLOCK_TIME: Final = re.compile(
    r"(?<!\d)(?P<date>\d{4}-\d{2}-\d{2})"
    r"(?:(?P<between>[T ])(?P<time>\d{2}:\d{2}(?::\d{2})?)(?P<fraction>\.\d+)?"
    r"(?P<zone>Z|\+00:00)?)?"
    r"(?![\d:])"
    r"|(?<![\d:.])(?P<time_of_day>\d{2}:\d{2}(?::\d{2})?)(?![\d:])"
)


def moved_in(value: Any, shift: timedelta, only: frozenset[str] | None = None) -> Any:
    """Any value a recorded answer holds, with each clock time in its strings
    moved by `shift` - however deep inside lists and objects it sits.

    `only`, where given, names the times to move, as they are written; every
    other time stays as it is.

    What this cannot tell apart, and moves or leaves regardless:
    - a time of day is read as UTC and moved round the clock, so a duration
      written like one - `00:10` - moves as though it were a time;
    - a date written in words - `28 September` - is not seen, and stays;
    - a date alone moves as its midnight would, so a shift of a day and a half
      moves it by one.
    """
    if isinstance(value, str):
        return _A_CLOCK_TIME.sub(lambda found: _moved(found, shift, only), value)

    if isinstance(value, list):
        return [moved_in(item, shift, only) for item in value]

    if isinstance(value, dict):
        return {name: moved_in(item, shift, only) for name, item in value.items()}

    return value


def instants_in(value: Any) -> list[tuple[str, datetime]]:
    """Every whole instant in a value's strings - a date with a time - as it is
    written, with the instant it names, read as UTC where it carries no zone.

    Not a date alone, nor a time of day alone: neither names an instant, so
    neither can be said to fall before or after one.
    """
    if isinstance(value, str):
        return [(found[0], instant) for found in _A_CLOCK_TIME.finditer(value)
                if (instant := _the_instant(found)) is not None]

    if isinstance(value, list):
        return [pair for item in value for pair in instants_in(item)]

    if isinstance(value, dict):
        return [pair for item in value.values() for pair in instants_in(item)]

    return []


def _the_instant(found: re.Match[str]) -> datetime | None:
    if found["time"] is None:
        return None

    try:
        return datetime.fromisoformat(
            f"{found['date']}T{found['time']}{found['fraction'] or ''}+00:00"
        )
    except ValueError:
        return None


def _moved(found: re.Match[str], shift: timedelta, only: frozenset[str] | None) -> str:
    """One clock time moved, written back in the shape it was found in - with
    the seconds, fraction and zone it had, and nothing it did not.

    Something shaped like a time that is not one - `27:90` - is left as it was,
    and so is a time `only` does not name.
    """
    if only is not None and found[0] not in only:
        return found[0]

    try:
        return _moved_or_refused(found, shift)
    except ValueError:
        return found[0]


def _moved_or_refused(found: re.Match[str], shift: timedelta) -> str:
    if found["time_of_day"] is not None:
        return _a_time_of_day(
            datetime.fromisoformat(f"2000-01-01T{found['time_of_day']}") + shift,
            with_seconds=found["time_of_day"].count(":") == 2
        )

    if found["time"] is None:
        return (datetime.fromisoformat(found["date"]) + shift).date().isoformat()

    fraction = found["fraction"] or ""
    moved = datetime.fromisoformat(f"{found['date']}T{found['time']}{fraction}") + shift

    return (f"{moved.date().isoformat()}{found['between']}"
            f"{_a_time_of_day(moved, with_seconds=found['time'].count(':') == 2)}"
            f"{f'.{moved.microsecond:06d}'[:len(fraction)] if fraction else ''}"
            f"{found['zone'] or ''}")


def _a_time_of_day(moment: datetime, with_seconds: bool) -> str:
    return moment.strftime("%H:%M:%S" if with_seconds else "%H:%M")
