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
"""

from __future__ import annotations

import re

from argus_narration.clock import a_minute

# An instant inside a sentence, in the two shapes that are not already how this
# page says the time: the wire format the tools speak to each other, and a
# clock time still carrying the wire's zone marker.
#
# A bare `10:14` is deliberately not among them. It is already what this
# renders to, so matching it only to hand it back is a third pattern that can
# be got wrong and can never be got right.
_A_TIME_IN_PROSE = re.compile(
    r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?Z?)"
    r"|(?<!\d)(\d{2}:\d{2}(?::\d{2})?Z)"
)

# A clock time on its own, with or without the wire format's seconds and zone.
_A_BARE_CLOCK = re.compile(r"\d{2}:\d{2}(?::\d{2})?Z?")


def said_plainly(prose: str) -> str:
    """A model's sentence, with its instants said the way the page says them.

    A claim arrives here already on one line - that is settled where the answer
    is accepted - so an instant is never split across a break by the time these
    patterns read it.
    """
    return _with_readable_times(prose)


def _with_readable_times(prose: str) -> str:
    """Wire-format instants inside a sentence, said as a clock says them.

    `21:48Z` is what the tools speak to each other; a person reading a page
    beside a wall clock wants `21:48`. Only the format changes - the moment is
    the one the model named, and every other time on the page is rendered the
    same way.
    """
    return _A_TIME_IN_PROSE.sub(lambda found: _on_the_clock(found.group(0)), prose)


def _on_the_clock(said: str) -> str:
    """One quoted time as a clock reads it, whatever shape it arrived in.

    A bare `21:48Z` is a wire-format time with its date left off, which nothing
    can parse into an instant - so it is trimmed rather than parsed. A full
    timestamp is parsed, because only parsing it can put it in UTC.
    """
    if _A_BARE_CLOCK.fullmatch(said):
        return said[:5]

    return a_minute(said)
