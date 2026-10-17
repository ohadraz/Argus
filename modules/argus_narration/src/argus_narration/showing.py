"""A line of the account as it is shown: the square brackets a name is quoted
in, left off, and a revision the incident read said short, leading to its
commit.

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
one its postmortem says it by (`short_form`), whether the line named it whole
or by a start of it only it begins - and only there: what a model is told
keeps what was written, which is what it reads and quotes back. Said short, it
is a name a reader cannot look up by hand, so the line carries where it opens.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Final

from argus_core import A_REVISION, short_form, the_revision_named
from argus_core.events import ChangesRetrieved, IncidentEvent
from pydantic import BaseModel, ConfigDict

from argus_narration.narrating import NarrationLine

# A name quoted in brackets: not straight after a word, as an index is; nothing
# inside that a phrase or another bracket would have; and not a link's text.
_A_QUOTED_NAME: Final = re.compile(r"(?<![\w\[])\[([^\s\[\]]+)\](?![(\]])")


class ShownRevision(BaseModel):
    """A revision the incident read, as a shown line says it: by its short
    form, opening where it was committed."""

    model_config = ConfigDict(frozen=True)

    short: str
    address: str


def as_shown(text: str) -> str:
    """`text` with the brackets around each name it quotes left off."""
    return _A_QUOTED_NAME.sub(r"\1", text)


def shown(line: NarrationLine, revisions: Mapping[str, ShownRevision]) -> NarrationLine:
    """A line of the account as a destination shows it - every part of it
    alike, since the marked word and the words either side are one sentence
    split for a destination that sets the word apart - each revision in
    `revisions` said by its short form, and leading where it opens. A line
    written outside the walk is shown as it was written.

    Its links are read off what the shown line names rather than off what this
    call re-said, so a line shown twice leads where it led shown once."""
    if line.outside_the_walk:
        return line

    whole = frozenset(revisions)

    def said(text: str) -> str:
        return as_shown(_shortened(text, whole, revisions))

    parts = {"text": said(line.text),
             "before_emphasis": said(line.before_emphasis),
             "emphasis": said(line.emphasis),
             "after_emphasis": said(line.after_emphasis)}

    return line.model_copy(update={**parts, "links": _the_links_in(parts.values(), revisions)})


def the_revisions(events: Sequence[IncidentEvent]) -> dict[str, ShownRevision]:
    """Each revision the incident read, and how a shown line says it: every
    deploy among the changes read that can be opened, said as short as names
    it alone among them, opening at its commit.

    Built from the events read so far, so a line shown before a later read
    that starts alike keeps fewer characters than one shown after it."""
    opened_at = {change.reference: change.revision_source.revision_address
                 for event in events if isinstance(event, ChangesRetrieved)
                 for change in event.changes if change.revision_source is not None}
    revisions = frozenset(opened_at)

    return {revision: ShownRevision(short=short_form(revision, revisions), address=address)
            for revision, address in opened_at.items()}


def _shortened(text: str,
               whole: frozenset[str],
               revisions: Mapping[str, ShownRevision]) -> str:
    """`text` with each revision it names - whole, or by a start only it
    begins - said by its short form. A start several begin names none of them,
    and is left as written."""
    if not revisions:
        return text

    def as_said(named: re.Match[str]) -> str:
        meant = the_revision_named(named.group(0), whole)
        return revisions[meant].short if meant is not None else named.group(0)

    return A_REVISION.sub(as_said, text)


def _the_links_in(parts: Iterable[str], revisions: Mapping[str, ShownRevision]) -> dict[str, str]:
    """Each revision's short form a shown line names, matched whole, and where
    it opens.

    Each short looked for by name rather than by `A_REVISION`, which will not
    take a run of hex with no letter in it for a revision - right for spotting
    a revision nobody named, and wrong for one already known: seven characters
    are all digits for about one revision in twenty-seven."""
    said = list(parts)

    return {revision.short: revision.address for revision in revisions.values()
            if any(re.search(rf"(?<![\w-]){re.escape(revision.short)}(?![\w-])", part)
                   for part in said)}
