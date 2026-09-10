"""A model's sentence, said the way the rest of the page says things.

Two repairs, both of them presentation, neither changing what was claimed: the
flag states, which the model quotes as `'on'` and the rest of the page calls
`ON`; and the times, which it writes in the wire format the tools speak. Three
spellings of one fact on one screen is a reader wondering whether they are
three facts.

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

# A flag's name as this system writes them: lower-case words joined by
# hyphens. Spelled out because it is what tells a state from an English word -
# "off" after a flag's name is a position, and "off" in a sentence is prose.
_A_FLAG_NAME = r"[a-z][a-z0-9]*(?:-[a-z0-9]+)+"

# A flag's state as the model writes it: quoted, bare on either side of the
# arrow it draws between two of them, said as a move in words, or written
# straight after the flag it belongs to.
_A_QUOTED_STATE = re.compile(r"""['"](on|off)['"]""", re.IGNORECASE)
_A_TRANSITION = re.compile(r"\b(on|off)\s*(?:→|->)\s*(on|off)\b", re.IGNORECASE)
_A_MOVE_IN_WORDS = re.compile(r"\bfrom (on|off) to (on|off)\b", re.IGNORECASE)
_A_STATE_OF_A_FLAG = re.compile(
    rf"\b({_A_FLAG_NAME})(\s*=\s*|\s+(?:to\s+)?)(on|off)\b", re.IGNORECASE
)

# Any run of whitespace that contains a line break.
_A_LINE_BREAK = re.compile(r"[ \t]*\n\s*")

# A clock time on its own, with or without the wire format's seconds and zone.
_A_BARE_CLOCK = re.compile(r"\d{2}:\d{2}(?::\d{2})?Z?")


def said_plainly(prose: str) -> str:
    """A model's sentence, arranged the way the page arranges everything else.

    The states are repaired before the line breaks are, because a transition
    the model wrote across two lines is still a transition and is read as one
    either way round.
    """
    return _with_readable_times(_on_one_line(_with_plain_states(prose)))


def a_time_named_in(cited: str) -> str | None:
    """The first time this sentence quotes, exactly as it wrote it.

    Here rather than beside the code that follows the link, because what counts
    as a time in prose is a fact about how the model writes and every other such
    fact lives in this module.
    """
    found = _A_TIME_IN_PROSE.search(cited)

    return None if found is None else found.group(0)


def _with_plain_states(prose: str) -> str:
    """`ON` and `OFF`, however the model happened to write them.

    Every shape the model actually writes a flag's position in: quoted, either
    side of an arrow, "from off to on", and straight after the flag it belongs
    to. A page that shouted one of them and whispered the rest would look like
    it was describing several different kinds of thing.

    Only these shapes. Uppercasing every "off" in a sentence would shout at
    prose that merely uses the word, which is the mistake in the other
    direction and the more embarrassing one.
    """
    prose = _A_QUOTED_STATE.sub(lambda found: found.group(1).upper(), prose)
    prose = _A_MOVE_IN_WORDS.sub(
        lambda found: f"from {found.group(1).upper()} to {found.group(2).upper()}", prose
    )
    prose = _A_STATE_OF_A_FLAG.sub(
        lambda found: f"{found.group(1)}{found.group(2)}{found.group(3).upper()}", prose
    )

    return _A_TRANSITION.sub(
        lambda found: f"{found.group(1).upper()} → {found.group(2).upper()}", prose
    )


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
