"""A line of the account as it is shown: a name quoted in square brackets said
as code, and a revision the incident read said short, leading to its commit.

Argus and its model mark a name off in brackets - "[io-shop]", "[3] replicas"
- which is how a model reading the record tells a name from the words around
it. A reader needs the same: which words read as a sentence and which are a
service, a flag or a count to look up. So where a line is shown the name is
set apart as code, between backticks, which every destination draws as code -
the page, the channel and the postmortem alike. Only there: the narration a
model is told keeps the brackets, and so does the record.

A revision the incident read is the exception. Said short, it is a link to its
commit, and a link inside code is drawn by none of them, so it is shown bare.

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
from collections.abc import Collection, Iterable, Mapping, Sequence
from typing import Final

from argus_core import said_short, short_form
from argus_core.events import ChangesRetrieved, FixAttempted, IncidentEvent
from argus_core.models import CitedChange
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


def as_shown(text: str, bare: Collection[str] = frozenset()) -> str:
    """`text` with each name it quotes in brackets said as code instead, and
    each in `bare` - a revision's short form, which is shown as a link - with
    its brackets left off and nothing in their place.

    Outside code alone: a bracket in a span of code is the code's, and taken
    for a name's, "`<protocol>[-<purpose>]`" read as a purpose no longer
    optional."""
    def said(quoted: re.Match[str]) -> str:
        name = quoted.group(1)
        return name if name in bare else f"`{name}`"

    return "".join(part if _A_CODE_SPAN.fullmatch(part) else _A_QUOTED_NAME.sub(said, part)
                   for part in _A_CODE_SPAN.split(text))


def shown(line: NarrationLine, revisions: Mapping[str, ShownRevision],
          pull_requests: Mapping[str, str]) -> NarrationLine:
    """A line of the account as a destination shows it - every part of it
    alike, since the marked word and the words either side are one sentence
    split for a destination that sets the word apart, and the candidates under
    it with it, the move each blamed among them - each revision in `revisions`
    said by its short form, and each pull request in `pull_requests` by its
    name, each leading where it opens. A line written outside the walk is
    shown as it was written.

    Its links are read off what the shown line names rather than off what this
    call re-said, so a line shown twice leads where it led shown once."""
    if line.outside_the_walk:
        return line

    def said(text: str) -> str:
        return said_as_shown(_by_their_names(text, pull_requests), revisions)

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
                                   | _the_names_said_in(named, pull_requests)})


def the_pull_requests(events: Sequence[IncidentEvent]) -> dict[str, str]:
    """Each pull request the incident opened, by its address, and the name a
    shown line says it by - Argus's one name for it, as the postmortem says
    it."""
    return {event.pull_request.url: event.pull_request.name for event in events
            if isinstance(event, FixAttempted) and event.pull_request is not None}


def _by_their_names(text: str, pull_requests: Mapping[str, str]) -> str:
    """`text` with each address in `pull_requests` it says, matched whole,
    said by its name - so the seventh pull request's is never found in the
    seventieth's."""
    if not pull_requests:
        return text

    addresses = "|".join(re.escape(address)
                         for address in sorted(pull_requests, key=len, reverse=True))

    return re.sub(rf"({addresses})(?![\w/])", lambda found: pull_requests[found.group(1)], text)


def _the_names_said_in(parts: Iterable[str], pull_requests: Mapping[str, str]) -> dict[str, str]:
    """Each pull request's name a shown line says, matched whole, and the
    address it opens."""
    said = list(parts)

    return {name: address for address, name in pull_requests.items()
            if any(re.search(rf"(?<![\w-]){re.escape(name)}(?![\w-])", part) for part in said)}


def said_as_shown(text: str, revisions: Mapping[str, ShownRevision]) -> str:
    """Words of the walk as a shown line says them: each revision in
    `revisions` by its short form and bare, and every other name quoted in
    brackets as code.

    Shortened first: a revision quoted whole is said as code otherwise, before
    it is a short form `bare` knows.

    Public, with `the_links_in`, for what is shown off the page's own rows
    rather than off its lines - the walk's candidates - and says them alike."""
    return as_shown(said_short(text, {whole: revision.short
                                      for whole, revision in revisions.items()}),
                    bare=frozenset(revision.short for revision in revisions.values()))


def the_short_forms(changes: Sequence[CitedChange]) -> dict[str, str]:
    """Each revision a change read that can be opened names whole, and its
    short form - the one the document says it by, in its prose, its timeline,
    its hypotheses and every sentence code says in a row's words.

    Here, beside `said_as_the_document_shows`, because the document and the
    agent that writes it say a row alike only where both take its forms from
    the one map."""
    return {cited.change.reference: cited.short_reference
            for cited in changes if cited.change.revision_source is not None}


def said_as_the_document_shows(text: str, shorts: Mapping[str, str],
                               pull_requests: Mapping[str, str]) -> str:
    """Words of the walk as a postmortem shows them: each pull request in
    `pull_requests`, by its address, said by its name; each revision in
    `shorts`, whole, by its short form and bare; and every other name quoted
    in brackets as code.

    Public because the document's timeline says a row so, and so does every
    sentence code says in a row's words - one spelling of a row wherever the
    document says it, rather than one for each place that says it."""
    return as_shown(said_short(_by_their_names(text, pull_requests), shorts),
                    bare=frozenset(shorts.values()))


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
