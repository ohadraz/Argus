"""How a stored value is written for a reader.

Here rather than in the document because formatting belongs to whatever shows a
value: the postmortem keeps every amount at the precision it was computed to,
and only what shows it rounds. Here rather than in the page because the page is
not the only thing that shows one - the PDF writes the same amounts, and an
amount written two ways is two figures to a reader comparing them.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Final

_A_CENT: Final = Decimal("0.01")

# A whole commit as git names one: forty hex digits, lower case.
_A_WHOLE_COMMIT: Final = re.compile(r"[0-9a-f]{40}")

# How much of a commit git shows, and so how much a reader pastes back into it.
_A_SHORT_COMMIT: Final = 7


def as_money(amount: Decimal) -> str:
    """An amount to the cent, its thousands grouped: `1,736.68`.

    Half a cent rounds up, as a reader checking the figure by hand rounds it.
    """
    return f"{amount.quantize(_A_CENT, rounding=ROUND_HALF_UP):,}"


def as_span(span: timedelta) -> str:
    """A stretch of time to the second, from its largest unit down: `2m 40s`,
    `1h 0m 5s`, `7d 0h 3m 5s`, `45s`.

    Every unit below the first is said, zero or not, so each sits where a
    reader expects to find it.
    """
    seconds = round(span.total_seconds())
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)

    if days:
        return f"{days}d {hours}h {minutes}m {seconds}s"

    if hours:
        return f"{hours}h {minutes}m {seconds}s"

    if minutes:
        return f"{minutes}m {seconds}s"

    return f"{seconds}s"


def as_revision(revision: str) -> str:
    """A whole commit by its first seven characters, as git shows one:
    `26f1d7e`. Anything else as written.

    Only a whole commit is cut: a deployment's state is whatever the
    investigation called it, and a tag or a commit already short would lose
    the part that names it.
    """
    if _A_WHOLE_COMMIT.fullmatch(revision):
        return revision[:_A_SHORT_COMMIT]

    return revision


def in_utc(moment: datetime, pattern: str = "%Y-%m-%d %H:%M") -> str:
    """A moment, rendered in UTC and saying so.

    The zone is written out rather than assumed. The Target Service's console
    stamps its minutes in UTC and labels them; an unlabelled time beside it
    reads as local, and the two look as though they disagree about when the
    incident happened.

    Converted rather than trusted: the value arrives from a `TIMESTAMPTZ` in
    whatever zone the connection is set to, and formatting it as it comes would
    make the label a guess.
    """
    return f"{moment.astimezone(UTC).strftime(pattern)} UTC"


def on_the_clock(moment: datetime, pattern: str = "%H:%M:%S") -> str:
    """A moment in UTC, unlabelled - for a column whose heading says UTC once.

    The same conversion `in_utc` does and none of its suffix: a table that
    repeats the zone on every row of forty spends a column's width saying one
    thing forty times, and that width is the message column's.
    """
    return moment.astimezone(UTC).strftime(pattern)
