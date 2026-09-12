"""A model's sentence, said the way the rest of the page says things.

Two repairs, both of them presentation, neither changing what was claimed: the
line breaks, which the model puts mid-clause and the page lays out itself; and
the times, which it writes in the wire format the tools speak. Two spellings of
one instant on one screen is a reader wondering whether they are two facts.

A flag's position used to be repaired here too - four patterns deciding which
of the `on`s and `off`s in a sentence were states and which were English, which
is a judgement no pattern can make. The model states the two ends of a
transition as fields now, and `said_as_a_state` says them; nothing is left to
recover from the sentence.

Nothing here decodes what the model wrote. A character it escaped rather than
typed is resolved where its answer is accepted, so that the page, the postmortem
and whoever is paged all read the same sentence.

Gathered into one module because it is one decision, and one worth being able
to look at whole: every pattern here is a fact about how a language model
happens to write, and a renderer is a strange place to keep such a fact. Until
they are repaired somewhere better, they are at least repaired in one place.
"""

from __future__ import annotations

import re

from argus_web.views.clock import a_minute

# A time inside a sentence, in either of the two shapes this system writes:
# the wire format the tools speak to each other, and the clock time the model
# uses when it writes for a person.
_A_TIME_IN_PROSE = re.compile(
    r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?Z?)"
    r"|(?<!\d)(\d{2}:\d{2}(?::\d{2})?Z)"
    r"|(?<!\d)(\d{2}:\d{2})(?!:?\d)"
)

# Any run of whitespace that contains a line break.
_A_LINE_BREAK = re.compile(r"[ \t]*\n\s*")

# A clock time on its own, with or without the wire format's seconds and zone.
_A_BARE_CLOCK = re.compile(r"\d{2}:\d{2}(?::\d{2})?Z?")


def said_plainly(prose: str) -> str:
    """A model's sentence, arranged the way the page arranges everything else.

    The line breaks go before the times are read, because a model that broke
    its line around an instant would otherwise leave a shape no pattern here
    matches.
    """
    return _with_readable_times(_on_one_line(prose))


def _on_one_line(prose: str) -> str:
    """A sentence, said as a sentence.

    The model writes a paragraph and occasionally breaks it mid-clause; the
    page lays its own text out. A line break arriving inside a claim is
    typesetting the model did not mean and the page did not ask for, so it
    becomes the space it stands for.
    """
    return _A_LINE_BREAK.sub(" ", prose).strip()


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
