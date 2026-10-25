"""A model's instant, said the way the rest of the page says instants.

One repair, presentation only, changing nothing that was claimed: the times,
which the model writes in the wire format the tools speak. Two spellings of one
instant on one screen is a reader wondering whether they are two facts.

What is left here is what is genuinely the page's own. Everything else this
module used to carry has moved to where the answer is accepted, so that the
page, the postmortem and whoever is paged all read one sentence: a character
the model escaped rather than typed, a line break it wrote mid-clause, and the
two ends of a transition - which were four patterns deciding which of the `on`s
and `off`s in a sentence were states and which were English, a judgement no
pattern can make. The model states them as fields now.

That leaves one rendering rather than a collection of repairs, and it stays
here because it is a rendering: `21:48Z` is not wrong, it is simply not how
this page says the time. It stays *here* rather than following the others to
the acceptance seam for the same reason - rendering an instant on the way in
would store `21:48` in place of the moment it names, throwing the date away,
and a postmortem is entitled to say the date.

Finding the instants is the part every reader of a model's words shares, so it
is public (`the_instants_in`): the postmortem says each as a moment of its own
rather than on this page's clock, and two finders were two answers to which of
a sentence's words are instants.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from typing import Final, NamedTuple

from argus_core import parse_iso, to_iso

from argus_narration.clock import a_moment, is_a_moment

# An instant inside a sentence, in the two shapes that are not already how this
# page says the time: a timestamp in any form ISO 8601 allows - `T` or a space
# between date and time, a fraction of a second, `Z`, an offset or no zone at
# all - and a clock time still carrying the wire's zone marker.
#
# A bare `10:14` is deliberately not among them. It is already what this
# renders to, so matching it only to hand it back is a third pattern that can
# be got wrong and can never be got right. Nor is a clock time's offset: with
# no date beside it, `10:14-10:16` is a window far more often than a time at
# minus ten hours sixteen, and nothing in the words says which.
_A_TIME_IN_PROSE = re.compile(
    r"(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})?)"
    r"|(?<!\d)(\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?Z)"
)

# A clock time on its own, with or without the wire format's seconds and zone.
_A_BARE_CLOCK = re.compile(r"\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?Z?")

# The day a clock time is put on where no line says which: any will do, since
# a time said beside nothing is said without one.
_ANY_DAY: Final = date(1970, 1, 1)


class InstantInProse(NamedTuple):
    """An instant a model wrote in a sentence: where in it, and the moment it
    names."""

    start: int
    end: int
    at: datetime


def the_instants_in(prose: str, day: date | None) -> list[InstantInProse]:
    """Every instant a model wrote in `prose`, in either shape that is not how
    a page says the time, and the moment each names.

    A bare `21:48Z` is a wire-format time with its date left off, which nothing
    can parse into an instant - so it is put on `day`, the day of whatever the
    sentence is read beside, and names none where there is no such day. A full
    timestamp is parsed as it came, because only parsing it can put it in UTC.
    A string shaped like an instant that names no moment is left out, and
    stays in the words as it came.
    """
    found = []
    for match in _A_TIME_IN_PROSE.finditer(prose):
        said = match.group(0)
        if _A_BARE_CLOCK.fullmatch(said):
            if day is None:
                continue
            said = f"{day.isoformat()}T{said.removesuffix('Z')}Z"

        try:
            at = parse_iso(said)
        except ValueError:
            continue

        found.append(InstantInProse(start=match.start(), end=match.end(), at=at))

    return found


def said_plainly(prose: str, beside: str | None = None) -> str:
    """A model's sentence, with its instants said the way the page says them.

    `21:48Z` is what the tools speak to each other; a person reading a page
    beside a wall clock wants `21:48`. Only the format changes - the moment is
    the one the model named, and every other time on the page is rendered the
    same way.

    A claim arrives here already on one line - that is settled where the answer
    is accepted - so an instant is never split across a break by the time these
    patterns read it.

    `beside` is the moment of the line the sentence sits on. A clock time is
    read as that line's day, so an instant on any other keeps its date.
    """
    said, written = [], 0
    for instant in the_instants_in(prose, _the_day_of(beside)):
        said += [prose[written:instant.start], a_moment(to_iso(instant.at), beside=beside)]
        written = instant.end

    return "".join([*said, prose[written:]])


def _the_day_of(beside: str | None) -> date:
    """The UTC day of the line a clock time sits on, or any day where there is
    no such line to read one from - said beside nothing, a time is never dated,
    so the day only places it."""
    if beside is None or not is_a_moment(beside):
        return _ANY_DAY

    return parse_iso(beside).astimezone(UTC).date()
