"""A day said as Argus says one: the month and the day of the month, "Oct 20".

The kernel's, because every party has to agree on it: narration writes it, the
page dates its own moments with it, and the postmortem's reader of figures has
to know one when it meets it. Read word by word, "Oct 20 20:31" is a word, the
figure "20" and a time, and the brief offered the day of the month to the model
as a number the incident gave.

The months are named here rather than by `strftime`'s `%b`, which follows the
locale: a spelling that moves with the machine is one the pattern below cannot
be sure to know.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from typing import Final

_MONTHS: Final = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
                  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

# A day as `said_as_a_day` says one, wherever a line says it.
A_DAY_SAID: Final = re.compile(rf"\b(?:{'|'.join(_MONTHS)}) \d{{2}}\b")


def said_as_a_day(at: datetime) -> str:
    """The day `at` falls on in UTC, said as the month and the day of the
    month in two digits: "Oct 20", "Sep 05"."""
    at = at.astimezone(UTC)

    return f"{_MONTHS[at.month - 1]} {at.day:02d}"


def the_day_said(said: str, near: date) -> date | None:
    """The day a day said ("Oct 20") names, read back as `said_as_a_day`
    says one - `None` where it is no day said so.

    A day said carries no year, so it is the year that puts it nearest
    `near`: nothing Argus says names a day a year from the incident it is
    about. `None` too where no year near has that day - Feb 29 in most."""
    if not A_DAY_SAID.fullmatch(said):
        return None

    month_said, day_of_the_month = said.split()
    month = _MONTHS.index(month_said) + 1

    return min((on for year in (near.year - 1, near.year, near.year + 1)
                if (on := _a_day(year, month, int(day_of_the_month))) is not None),
               key=lambda on: abs(on - near), default=None)


def _a_day(year: int, month: int, day_of_the_month: int) -> date | None:
    try:
        return date(year, month, day_of_the_month)
    except ValueError:
        return None


def said_as_a_time(at: datetime) -> str:
    """The time of day `at` falls at in UTC, to the minute, and to the second
    only where it has one: "19:12", "19:12:55". A minute said "19:12:00"
    claims a precision nothing measured, and one said "19:12" of 19:12:55
    reads a span from it as a minute short."""
    at = at.astimezone(UTC)

    return f"{at:%H:%M:%S}" if at.second else f"{at:%H:%M}"
