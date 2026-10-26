"""A line of the account as it is shown: the square brackets a name is quoted
in, left off, and a revision the incident read said short, leading to its
commit.

Argus and its model mark a name off in brackets - "[io-shop]", "[7c3ca00]" -
which is how a model reading the record tells a name from the words around
it. A reader of the page or the channel reads them as clutter around a word.
So they are left off where a line is shown, and only there: the narration a
model is told keeps them, and so does the record.

Only the brackets that quote a name: a run with no space in it, at the start
of a word, outside a span of code. An index in code (`prices[0]`) keeps its
brackets, as does anything between backticks, a phrase with spaces in it, a
link's text and anything nested. And only on the walk's
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

A pull request is said by its address in the record, which is what a model is
told and quotes back. Where a line is shown it is said by Argus's one name for
it, "PR #7", as the postmortem says it, and the name opens the address.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Final

from argus_core import said_short, short_form
from argus_core.events import ChangesRetrieved, IncidentEvent
from pydantic import BaseModel, ConfigDict

from argus_narration.narrating import NarrationLine

# A name quoted in brackets: not straight after a word, as an index is; nothing
# inside that a phrase or another bracket would have; and not a link's text.
_A_QUOTED_NAME: Final = re.compile(r"(?<![\w\[])\[([^\s\[\]]+)\](?![(\]])")

# A span of code, between backticks: kept as written, its brackets included.
_A_CODE_SPAN: Final = re.compile(r"(`[^`]*`)")


class ShownRevision(BaseModel):
    """A revision the incident read, as a shown line says it: by its short
    form, opening where it was committed."""

    model_config = ConfigDict(frozen=True)

    short: str
    address: str


def as_shown(text: str) -> str:
    """`text` with the brackets around each name it quotes left off - outside
    code alone: a bracket in a span of code is the code's, and taken for a
    name's, "`<protocol>[-<purpose>]`" read as a purpose no longer optional."""
    return "".join(part if _A_CODE_SPAN.fullmatch(part) else _A_QUOTED_NAME.sub(r"\1", part)
                   for part in _A_CODE_SPAN.split(text))


def shown(line: NarrationLine, revisions: Mapping[str, ShownRevision]) -> NarrationLine:
    """A line of the account as a destination shows it - every part of it
    alike, since the marked word and the words either side are one sentence
    split for a destination that sets the word apart, and the candidates under
    it with it, the move each blamed among them - each revision in `revisions`
    said by its short form, and the address the line names by the name it is
    shown by, each leading where it opens. A line written outside the walk is
    shown as it was written.

    Its links are read off what the shown line names rather than off what this
    call re-said, so a line shown twice leads where it led shown once."""
    if line.outside_the_walk:
        return line

    def said(text: str) -> str:
        return _the_address_by_its_name(line, said_as_shown(text, revisions))

    parts = {"text": said(line.text),
             "before_emphasis": said(line.before_emphasis),
             "emphasis": said(line.emphasis),
             "after_emphasis": said(line.after_emphasis)}
    candidates = [candidate.model_copy(update={
        "summary": said(candidate.summary),
        "subject": said(candidate.subject) if candidate.subject is not None else None,
        "moved_from": said(candidate.moved_from),
        "moved_to": said(candidate.moved_to),
        "evidence": [finding.model_copy(update={"text": said(finding.text)})
                     for finding in candidate.evidence]})
        for candidate in line.candidates]
    named = [*parts.values(),
             *(part for candidate in candidates
               for part in (candidate.summary, candidate.subject or "",
                            candidate.moved_from, candidate.moved_to,
                            *(finding.text for finding in candidate.evidence)))]

    return line.model_copy(update={**parts, "candidates": candidates,
                                   "links": the_links_in(named, revisions)
                                   | _the_address_s_name_in(line, named)})


def _the_address_by_its_name(line: NarrationLine, text: str) -> str:
    """`text` with the address the line names said by the name it is shown
    by - a pull request as "PR #7" - where it has one."""
    if not line.names_url or not line.shown_url_as:
        return text

    return text.replace(line.names_url, line.shown_url_as)


def _the_address_s_name_in(line: NarrationLine, parts: Iterable[str]) -> dict[str, str]:
    """The name the line's address is shown by, leading there, where a shown
    part says it - matched whole, as a revision's short form is, so "PR #7"
    is never found in "PR #70"."""
    name = line.shown_url_as
    if not line.names_url or not name:
        return {}

    named = any(re.search(rf"(?<![\w-]){re.escape(name)}(?![\w-])", part) for part in parts)

    return {name: line.names_url} if named else {}


def said_as_shown(text: str, revisions: Mapping[str, ShownRevision]) -> str:
    """Words of the walk as a shown line says them: each revision in
    `revisions` by its short form, and the brackets quoting a name left off.

    Public, with `the_links_in`, for what is shown off the page's own rows
    rather than off its lines - the walk's candidates - and says them alike."""
    return as_shown(said_short(text, {whole: revision.short
                                      for whole, revision in revisions.items()}))


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


def the_links_in(parts: Iterable[str], revisions: Mapping[str, ShownRevision]) -> dict[str, str]:
    """Each revision's short form a shown line names, matched whole, and where
    it opens.

    Public because the walk's candidates are shown off the page's own rows
    rather than off its lines, and lead where the same names do in the lines.

    Each short looked for by name rather than by `A_REVISION`, which will not
    take a run of hex with no letter in it for a revision - right for spotting
    a revision nobody named, and wrong for one already known: seven characters
    are all digits for about one revision in twenty-seven."""
    said = list(parts)

    return {revision.short: revision.address for revision in revisions.values()
            if any(re.search(rf"(?<![\w-]){re.escape(revision.short)}(?![\w-])", part)
                   for part in said)}
