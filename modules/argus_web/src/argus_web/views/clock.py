"""Wire-format instants, said the way a person reads them.

The tools speak `2026-08-30T10:14:00Z` to each other; a reader sitting beside a
wall clock wants `10:14`. Only the rendering changes here - the moment is
whichever one was recorded, and every time on the page comes through this
module so that one instant is not written two ways on one screen.

Nothing here parses for a decision. A value that is not a time comes back as it
arrived rather than dropped or guessed at: it came out of a recorded event, and
a page that silently blanked it would be hiding the one clue to why it looks
wrong.
"""

from __future__ import annotations

from datetime import UTC

from argus_core.timestamps import parse_iso


def a_minute(value: str, beside: str | None = None) -> str:
    """A wire-format minute, said the way a clock says it.

    `2026-08-30T10:14:00Z` is what the tools speak to each other; a person
    reading a page next to a wall clock wants `10:14`. The raw value stays
    reachable in the markup that carries it - it is what the metrics table's
    rows are keyed by - so nothing is lost by not printing it.

    `beside` is the other end of the same window, and the date comes back the
    moment the two fall on different days. The change channel is asked about
    the twenty-four hours before the onset, and a clock time alone renders that
    as "18:13 to 18:13" - a window a reader can only read as a bug.
    """
    if beside is not None and not _the_same_day(value, beside):
        return _reformatted(value, "%d %b %H:%M")

    return _reformatted(value, "%H:%M")


def a_moment(value: str) -> str:
    """A wire-format instant to the second, for a log line's own stamp."""
    return _reformatted(value, "%H:%M:%S")


def is_a_moment(value: str) -> bool:
    """Whether a token is a timestamp rather than the start of the message."""
    try:
        parse_iso(value)
    except ValueError:
        return False

    return True


def a_window(start: str | None, end: str | None) -> str:
    """A retrieval's window, said the way the request actually made it.

    A metrics read is anchored rather than bounded (spec §16), so it has one
    end, and saying "to now" for the other would put a bound in the account
    that the call never had.
    """
    if start and end:
        return f"the {_how_long(start, end)} before {a_minute(end, beside=start)}"

    if start:
        return f"anchored on {a_minute(start)}"

    return f"up to {a_minute(end)}" if end else "over no particular window"


def _the_same_day(value: str, other: str) -> bool:
    """Whether two wire-format moments fall on the same date.

    Unparseable counts as the same day: the fallback prints the string as it
    arrived, and a date bolted onto something that is not a time would be a
    guess dressed up as precision.
    """
    try:
        return parse_iso(value).astimezone(UTC).date() == parse_iso(other).astimezone(UTC).date()
    except ValueError:
        return True


def _reformatted(value: str, pattern: str) -> str:
    """`value` in UTC under `pattern`, or `value` itself where it is not a time.

    Unparseable is shown as it arrived rather than dropped or guessed at: the
    string came out of a recorded event, and a page that silently blanked it
    would be hiding the one clue to why it looks wrong.
    """
    try:
        return parse_iso(value).astimezone(UTC).strftime(pattern)
    except ValueError:
        return value


def _how_long(start: str, end: str) -> str:
    """How much time a window covers, in the largest unit that says it whole.

    A span read as "29 Aug 19:16 to 30 Aug 19:16" is arithmetic the reader has
    to do to find out it is a day; "the 24 hours before 30 Aug 19:16" is the
    same window already understood. The end is kept and the start is not,
    because the end is what the window is anchored on.
    """
    try:
        minutes = round((parse_iso(end) - parse_iso(start)).total_seconds() / 60)
    except ValueError:
        return f"window {start} to {end}"

    if minutes >= 60 and minutes % 60 == 0:
        hours = minutes // 60

        return f"{hours} hour{'s' if hours != 1 else ''}"

    return f"{minutes} minute{'s' if minutes != 1 else ''}"
