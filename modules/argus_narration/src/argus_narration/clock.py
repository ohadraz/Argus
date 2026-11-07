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
from typing import Final

from argus_core import parse_iso, said_as_a_day, said_as_a_span, said_as_a_time

# A minute bucket's time of day, which is the minute it is.
_A_MINUTE: Final = "%H:%M"


def a_minute(value: str, beside: str | None = None) -> str:
    """A wire-format minute bucket, said the way a clock says it.

    `2026-08-30T10:14:00Z` is what the tools speak to each other; a person
    reading a page next to a wall clock wants `10:14`. The raw value stays
    reachable in the markup that carries it - it is what the metrics table's
    rows are keyed by - so nothing is lost by not printing it.

    `beside` is the other end of the same window, and the date comes back the
    moment the two fall on different days. The change channel is asked about
    the twenty-four hours before the onset, and a clock time alone renders that
    as "18:13 to 18:13" - a window a reader can only read as a bug.
    """
    return _reformatted(value, _A_MINUTE,
                        dated=beside is not None and not _the_same_day(value, beside))


def a_moment(value: str, beside: str | None = None) -> str:
    """A wire-format instant, said as the kernel says a time: to the minute,
    and to the second only where it has one - every instant on the page and in
    the brief alike, so one instant is never two spellings.

    `beside` is the moment it is read against, and the date comes back the
    moment the two fall on different days, as in `a_minute`: a pod placed a
    week after the onset, said as a time of day alone, reads as one placed the
    same day.
    """
    try:
        at = parse_iso(value).astimezone(UTC)
    except ValueError:
        return value

    dated = beside is not None and not _the_same_day(value, beside)

    return f"{said_as_a_day(at)} {said_as_a_time(at)}" if dated else said_as_a_time(at)


def a_moment_with_its_day(value: str) -> str:
    """A wire-format instant said as `a_moment` says one, always with its day.

    For a moment read against nothing it shares a day with: a line is dated by
    when it was recorded, and a time alone in it reads as that day's - a pod
    started on the onset's day, said bare in a line of the day after, was.
    """
    try:
        at = parse_iso(value).astimezone(UTC)
    except ValueError:
        return value

    return f"{said_as_a_day(at)} {said_as_a_time(at)}"


def is_a_moment(value: str) -> bool:
    """Whether a token is a timestamp rather than the start of the message."""
    try:
        parse_iso(value)
    except ValueError:
        return False

    return True


def a_window(start: str | None, end: str | None, beside: str | None = None) -> str:
    """A retrieval's window, said the way the request actually made it.

    A metrics read is anchored rather than bounded (spec §16), so it has one
    end, and saying "to now" for the other would put a bound in the account
    that the call never had.

    `beside` is the moment of the line the window is said on. A clock time is
    read as that line's day, so a window on any other keeps its date - even
    one whose two ends share a day, a week before the line asking for it.

    Each end an instant, said as one: the span is said exactly, and an end
    said to the minute beside it puts the window's start that many seconds
    from where it was.
    """
    if start and end:
        on_another_day = not _the_same_day(end, start)

        return (f"the {_how_long(start, end)} before "
                f"{a_moment(end, beside=start if on_another_day else beside)}")

    if start:
        return f"anchored on {a_moment(start, beside=beside)}"

    return f"up to {a_moment(end, beside=beside)}" if end else "over no particular window"


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


def _reformatted(value: str, clock: str, dated: bool) -> str:
    """`value` in UTC as `clock` says it, after the kernel's day where `dated`
    - or `value` itself where it is not a time.

    The day is the kernel's spelling rather than one written here, because the
    postmortem has to recognise it in a line it reads for figures.

    Unparseable is shown as it arrived rather than dropped or guessed at: the
    string came out of a recorded event, and a page that silently blanked it
    would be hiding the one clue to why it looks wrong.
    """
    try:
        at = parse_iso(value).astimezone(UTC)
    except ValueError:
        return value

    return f"{said_as_a_day(at)} {at:{clock}}" if dated else f"{at:{clock}}"


def _how_long(start: str, end: str) -> str:
    """How much time a window covers, said as the brief says every span.

    A span read as "29 Aug 19:16 to 30 Aug 19:16" is arithmetic the reader has
    to do to find out it is a day; "the 1 day before 30 Aug 19:16" is the
    same window already understood. The end is kept and the start is not,
    because the end is what the window is anchored on.
    """
    try:
        return said_as_a_span(parse_iso(end) - parse_iso(start))
    except ValueError:
        return f"window {start} to {end}"
