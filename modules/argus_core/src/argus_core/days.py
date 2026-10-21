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
from datetime import UTC, datetime
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


def said_as_a_time(at: datetime) -> str:
    """The time of day `at` falls at in UTC, to the minute, and to the second
    only where it has one: "19:12", "19:12:55". A minute said "19:12:00"
    claims a precision nothing measured, and one said "19:12" of 19:12:55
    reads a span from it as a minute short."""
    at = at.astimezone(UTC)

    return f"{at:%H:%M:%S}" if at.second else f"{at:%H:%M}"
