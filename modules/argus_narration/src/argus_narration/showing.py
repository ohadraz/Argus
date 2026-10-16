"""A line of the account as it is shown: the square brackets a name is quoted
in, left off.

Argus and its model mark a name off in brackets - "[io-shop]", "[7c3ca00]" -
which is how a model reading the record tells a name from the words around
it. A reader of the page or the channel reads them as clutter around a word.
So they are left off where a line is shown, and only there: the narration a
model is told keeps them, and so does the record.

Only the brackets that quote a name: a run with no space in it, at the start
of a word. An index in code (`prices[0]`) keeps its brackets, as do a phrase
with spaces in it, a link's text and anything nested. And only on the walk's
own lines: a line from outside the walk - a person's message, an offer, an
answer to a question - is shown as it was written, since a person's brackets
are theirs and a line not written by the walk need not follow its convention.
"""

from __future__ import annotations

import re
from typing import Final

from argus_narration.narrating import NarrationLine

# A name quoted in brackets: not straight after a word, as an index is; nothing
# inside that a phrase or another bracket would have; and not a link's text.
_A_QUOTED_NAME: Final = re.compile(r"(?<![\w\[])\[([^\s\[\]]+)\](?![(\]])")


def as_shown(text: str) -> str:
    """`text` with the brackets around each name it quotes left off."""
    return _A_QUOTED_NAME.sub(r"\1", text)


def shown(line: NarrationLine) -> NarrationLine:
    """A line of the account as a destination shows it - every part of it
    alike, since the marked word and the words either side are one sentence
    split for a destination that sets the word apart. A line written outside
    the walk is shown as it was written."""
    if line.outside_the_walk:
        return line

    return line.model_copy(update={
        "text": as_shown(line.text),
        "before_emphasis": as_shown(line.before_emphasis),
        "emphasis": as_shown(line.emphasis),
        "after_emphasis": as_shown(line.after_emphasis)
    })
