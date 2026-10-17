"""A line of the account as it is shown: the square brackets a name is quoted
in, left off, and a revision the incident read said short.

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

A revision is said whole in the record - "rolled [io-shop] back off revision
[7c3ca00c75...]" - and forty characters in a sentence read as noise. Where a
line is shown, each revision the incident read is said by its short form, the
one its postmortem says it by (`short_form`), and only there: what a model is
told keeps the whole, which is what it reads and quotes back.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Final

from argus_core import short_form
from argus_core.events import ChangesRetrieved, IncidentEvent

from argus_narration.narrating import NarrationLine

# A name quoted in brackets: not straight after a word, as an index is; nothing
# inside that a phrase or another bracket would have; and not a link's text.
_A_QUOTED_NAME: Final = re.compile(r"(?<![\w\[])\[([^\s\[\]]+)\](?![(\]])")


def as_shown(text: str) -> str:
    """`text` with the brackets around each name it quotes left off."""
    return _A_QUOTED_NAME.sub(r"\1", text)


def shown(line: NarrationLine, shorts: Mapping[str, str]) -> NarrationLine:
    """A line of the account as a destination shows it - every part of it
    alike, since the marked word and the words either side are one sentence
    split for a destination that sets the word apart - each revision in
    `shorts` said by its short form (`the_short_forms`). A line written
    outside the walk is shown as it was written."""
    if line.outside_the_walk:
        return line

    def said(text: str) -> str:
        return as_shown(_shortened(text, shorts))

    return line.model_copy(update={
        "text": said(line.text),
        "before_emphasis": said(line.before_emphasis),
        "emphasis": said(line.emphasis),
        "after_emphasis": said(line.after_emphasis)
    })


def the_short_forms(events: Sequence[IncidentEvent]) -> dict[str, str]:
    """Each revision the incident read, and the short form it is shown by:
    every deploy among the changes read that can be opened, said as short as
    names it alone among them.

    Built from the events read so far, so a line shown before a later read
    that starts alike keeps fewer characters than one shown after it."""
    revisions = frozenset(change.reference
                          for event in events if isinstance(event, ChangesRetrieved)
                          for change in event.changes if change.revision_source is not None)

    return {revision: short_form(revision, revisions) for revision in revisions}


def _shortened(text: str, shorts: Mapping[str, str]) -> str:
    """`text` with each revision in `shorts` it names, matched whole, said by
    its short form."""
    if not shorts:
        return text

    named = "|".join(re.escape(revision) for revision in sorted(shorts, key=len, reverse=True))
    return re.sub(rf"(?<!\w)({named})(?!\w)", lambda found: shorts[found.group(1)], text)
