"""A day said as narration says one beside a time: the day of the month and
the month, "20 Oct".

The kernel's, because two parties have to agree on it: narration writes it, and
the postmortem's reader of figures has to know one when it meets it. Read word by
word, "20 Oct 20:31" is the figure "20", a word and a time, and the brief offered
the day of the month to the model as a number the incident gave.

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
A_DAY_SAID: Final = re.compile(rf"\b\d{{2}} (?:{'|'.join(_MONTHS)})\b")


def said_as_a_day(at: datetime) -> str:
    """The day `at` falls on in UTC, said as the day of the month in two
    digits and the month: "20 Oct", "05 Sep"."""
    at = at.astimezone(UTC)

    return f"{at.day:02d} {_MONTHS[at.month - 1]}"
