"""Where to read more: every address Argus keeps for the incident, the changes
and log messages the prose cites, and what was assumed.

Every address in full: the document is read away from the screen it came from,
where an address relative to nothing leads nowhere.
"""

from __future__ import annotations

import re
from typing import Final

from argus_core import parse_iso, said_short
from argus_core.events import PATCH_LINE_INDENT
from argus_core.models import (
    ChangeEvent,
    ChangeKind,
    CitedChange,
    CitedEvidence,
    PostmortemDocument,
    RevisionSource,
)
from pydantic import BaseModel, ConfigDict

from postmortem_rendering.lines import Line, Role, Run

# Said in place of a list of evidence the walk read none of.
_NONE_READ = "None read."

# Who a change no one is named for was made by, as the model is told it too.
_NOBODY_NAMED: Final = "someone unnamed"

# Each kind of change as a reader says it, rather than as its value is spelled.
_A_KIND_IN_WORDS: Final[dict[ChangeKind, str]] = {
    ChangeKind.DEPLOY: "deploy",
    ChangeKind.FLAG_TOGGLE: "flag toggle"
}


class EvidenceRow(BaseModel):
    """A piece of evidence the model was shown, under the label the prose
    cites it by, said as it was shown."""

    model_config = ConfigDict(frozen=True)

    label: str
    said: Line


class SupportingSection(BaseModel):
    """The links, one line each; the changes and the log messages read, each a
    labelled row; the assumptions; and the word said in place of each list
    where it is empty - `None` where it is not.

    The changes, the log messages and what each deployment looked into
    changed are the kinds of evidence no other section is a row for, so
    without them a citation of one would lead nowhere. A deployment's row is
    its diff, a line of the document to each line of it, and is no row at all
    where no deployment was looked into - most incidents look into none, and
    "none read" under a heading for them would say a read was missed. What
    Code-Fix read in the source is a row of its own for the same reason, and
    headed as a reading nothing ran, which is how a cause resting on it is
    weighed. The log messages' heading names the zone their times are in,
    since each row says a time as the model was shown it; a change's row says
    its moment with its zone.

    `revision_addresses` is each revision the changes read name - short, as
    the prose writes one, and whole - and where it opens: the prose names a
    deploy by its revision as well as by its label, and a reader follows
    either.
    """

    model_config = ConfigDict(frozen=True)

    links: tuple[Line, ...]
    changes_heading: str = "Changes to production read"
    changes: tuple[EvidenceRow, ...]
    changes_absent: str | None
    revision_addresses: dict[str, str]
    log_messages_heading: str = "Log messages read (UTC)"
    log_messages: tuple[EvidenceRow, ...]
    log_messages_absent: str | None
    deployment_changes_heading: str = "What each deployment looked into changed"
    deployment_changes: tuple[EvidenceRow, ...] = ()
    code_read_heading: str = "What Code-Fix read in the source - a static reading, nothing ran it"
    code_read: tuple[EvidenceRow, ...] = ()
    assumptions_heading: str = "Assumptions"
    assumptions: tuple[Line, ...]
    assumptions_absent: str | None


def the_supporting_information(postmortem: PostmortemDocument,
                               incident_address: str) -> SupportingSection:
    """The section, linking the incident's walk at `incident_address` - the
    page's full address, which only whoever serves it knows."""
    links = [Line(runs=(Run(text="The incident's walk: "), Run.an_address(incident_address)))]

    fix = postmortem.pull_request
    if fix is not None:
        links.append(Line(runs=(Run(text="The fix it proposed: "),
                                # The name captions the address beside it, so
                                # only the address is a link: two to one place
                                # side by side are one too many.
                                Run.a_pull_request(fix.number),
                                Run(text=" ("),
                                Run.an_address(fix.url),
                                Run(text=") "),
                                Run(text="draft - nobody has merged it", role=Role.STATUS))))

    changes = tuple(EvidenceRow(label=cited.label, said=_a_change(cited))
                    for cited in postmortem.changes_read)
    log_messages = _rows(postmortem.log_messages_read)
    revision_addresses = the_revision_addresses(postmortem.changes_read)
    shorts = the_short_forms(postmortem.changes_read)
    deployment_changes = tuple(
        EvidenceRow(label=cited.label,
                    said=Line(runs=_shortened(Run(text=cited.text).with_links(revision_addresses),
                                              shorts)))
        for cited in postmortem.deployment_changes_read)
    assumptions = tuple(Line(runs=(Run(text=assumption, role=Role.PROSE),))
                        for assumption in postmortem.assumptions)

    return SupportingSection(links=tuple(links),
                             changes=changes,
                             changes_absent=None if changes else _NONE_READ,
                             revision_addresses=revision_addresses,
                             log_messages=log_messages,
                             log_messages_absent=None if log_messages else _NONE_READ,
                             deployment_changes=deployment_changes,
                             code_read=tuple(EvidenceRow(label=cited.label,
                                                         said=_with_code_set_apart(
                                                             cited.text, shorts,
                                                             revision_addresses))
                                             for cited in postmortem.code_read),
                             assumptions=assumptions,
                             assumptions_absent=None if assumptions else "None.")


def _a_change(cited: CitedChange) -> Line:
    """A change as its row says it: when, what kind, to what, by whom, and what
    it did.

    Its reference short, as the prose names it, and what it did in the words
    the model read - but the revision those words name whole said short too,
    since one revision said two ways reads as two. Where it can be opened, the
    revision, the repository and the directory each lead there; where it
    cannot, the reference is a name, said as one.
    """
    change = cited.change

    return Line(runs=(Run.a_moment(parse_iso(change.occurred_at)),
                      Run(text=f" {_A_KIND_IN_WORDS[change.kind]} "),
                      a_reference(change, cited.short_reference),
                      Run(text=f" by {change.actor or _NOBODY_NAMED}: "),
                      *what_a_change_did(change, cited.short_reference)))


def a_reference(change: ChangeEvent, short: str) -> Run:
    """A change read named as its row names it: by `short`, as the prose
    writes it, leading where it can be opened - and, where it cannot, a name
    said as one.

    Public because the trigger names the deploy that carried it the same way,
    and so does the dashboard's table of the changes read: one revision named
    two ways reads as two."""
    source = change.revision_source

    return (Run(text=short, role=Role.LINK, address=source.revision_address)
            if source is not None else Run(text=short, role=Role.CODE))


def what_a_change_did(change: ChangeEvent, short: str) -> tuple[Run, ...]:
    """What a change read did, as the model read it, but the revision those
    words name whole said by `short` - and the revision, the repository and the
    directory each leading where they open.

    A deploy that can be opened is said by where it came from alone: whatever
    shows this names its revision already, and the words the model read name
    it again. A row the model's prose cites may say what the model read in
    other words, or say less of it, and never say more - so the repository and
    the directory come off the change's own source rather than off a parse of
    its words. Every other change is said in the words the model read.

    Public because the dashboard's table of the changes read says it too, and
    in these words rather than in a second wording of its own."""
    source = change.revision_source

    if change.kind is ChangeKind.DEPLOY and source is not None:
        return _where_it_came_from(source)

    shorts = {change.reference: short} if source is not None else {}

    return _shortened(Run(text=change.summary).with_links(_the_addresses_of(change)), shorts)


def _where_it_came_from(source: RevisionSource) -> tuple[Run, ...]:
    """A deploy's repository and the directory it was synced from, each leading
    where it opens - the directory said where there was one."""
    repository = (Run(text="from the "),
                  Run(text=source.repository, role=Role.LINK, address=source.repository_address))

    if source.directory is None:
        return (*repository, Run(text=" repository"))

    directory = (Run(text=source.directory, role=Role.LINK, address=source.directory_address)
                 if source.directory_address is not None else Run(text=source.directory))

    return (*repository, Run(text=" repository's "), directory, Run(text="/ directory"))


def _the_addresses_of(change: ChangeEvent) -> dict[str, str]:
    """Each name a change's summary may say that a reader can open, and where."""
    source = change.revision_source
    if source is None:
        return {}

    addresses = {change.reference: source.revision_address,
                 source.repository: source.repository_address}
    if source.directory is not None and source.directory_address is not None:
        addresses[source.directory] = source.directory_address

    return addresses


def the_short_forms(changes: list[CitedChange]) -> dict[str, str]:
    """Each revision a change that can be opened names whole, and its short
    form - the one the prose writes.

    Public because the timeline and the hypotheses say a revision short too,
    and by the same forms."""
    return {cited.change.reference: cited.short_reference
            for cited in changes if cited.change.revision_source is not None}


def _shortened(runs: tuple[Run, ...], shorts: dict[str, str]) -> tuple[Run, ...]:
    """The runs with every revision linked whole said by its short form, as
    the prose and the timeline say it - the link still to the whole.

    Except on a patch line, set in by `PATCH_LINE_INDENT`: that is the file's
    own content quoted - an image tag pinned to the commit - and said short it
    would misquote the file. Only Argus's own lines are re-said."""
    said: list[Run] = []
    line = ""
    for run in runs:
        quoted = line.startswith(PATCH_LINE_INDENT)
        said.append(run.model_copy(update={"text": shorts[run.text]})
                    if run.role is Role.LINK and run.text in shorts and not quoted else run)
        line = run.text.rsplit("\n", 1)[-1] if "\n" in run.text else line + run.text

    return tuple(said)


def the_revision_addresses(changes: list[CitedChange]) -> dict[str, str]:
    """Each revision a change that can be opened names, short and whole, and
    where it opens.

    Public for the same reason as `the_short_forms`."""
    return {reference: cited.change.revision_source.revision_address
            for cited in changes if cited.change.revision_source is not None
            for reference in (cited.short_reference, cited.change.reference)}


def _with_code_set_apart(text: str, shorts: dict[str, str],
                         addresses: dict[str, str]) -> Line:
    """What Code-Fix read, the code it quotes between backticks set apart as
    code and the backticks left out: it writes Markdown, and a mark printed is
    one nobody reading the page or the paper was meant to see. Only at display -
    the model is briefed in its words as written.

    Its own words name a revision as the rest of the document does - short,
    and leading to its commit - for one revision said two ways reads as two.
    Code it quotes is quoted as it is."""
    pieces = _A_CODE_SPAN.split(text)
    # `split` puts what the group matched at every odd place.
    return Line(runs=tuple(run
                           for place, piece in enumerate(pieces) if piece
                           for run in ((Run(text=piece, role=Role.CODE),) if place % 2
                                       else Run(text=said_short(piece, shorts))
                                       .with_links(addresses))))


# Code quoted inline in Markdown: between single backticks, on one line.
_A_CODE_SPAN: Final = re.compile(r"`([^`\n]+)`")


def _rows(evidence: list[CitedEvidence]) -> tuple[EvidenceRow, ...]:
    return tuple(EvidenceRow(label=cited.label, said=Line(runs=(Run(text=cited.text),)))
                 for cited in evidence)
