"""Where to read more: every address Argus keeps for the incident, the changes
and log messages the prose cites, and what was assumed.

Every address in full: the document is read away from the screen it came from,
where an address relative to nothing leads nowhere.
"""

from __future__ import annotations

import re
from typing import Final

from argus_core import A_REVISION, parse_iso, said_short
from argus_core.events import PATCH_LINE_INDENT
from argus_core.models import (
    NOTHING_RECORDED_AFTER_IT_WAS_OPENED,
    ChangeEvent,
    ChangeKind,
    ChannelReading,
    CitedChange,
    CitedEvidence,
    PostmortemDocument,
    RevisionSource,
    changes_not_listed,
    no_logs_listed,
)
from argus_narration import the_short_forms
from pydantic import BaseModel, ConfigDict

from postmortem_rendering.lines import Line, Role, Run

# Said in place of a list of evidence on a document written before what came
# of reading it was carried.
_NONE_READ: Final = "None read."

# What became of the proposed fix, as far as the record goes: Argus opens a pull
# request and never reads it again, so whether anybody has merged it since is
# not something the document knows. Said the same wherever the fix is.
OPENED_AS_A_DRAFT: Final = "opened as a draft"

# What Code-Fix read in the source, headed by what came of it: "and proposed"
# only where a pull request holds what it proposed, "its fix" only where there
# is one to have run, and "its test" only where the fix brought one - a fix to
# configuration alone may come without.
_CODE_READ_AND_PROPOSED: Final = ("What Code-Fix read in the source and proposed - "
                                  "nothing ran its test or its fix")
_CODE_READ_AND_PROPOSED_WITHOUT_A_TEST: Final = ("What Code-Fix read in the source and "
                                                 "proposed - nothing ran its fix")
_CODE_READ_ALONE: Final = "What Code-Fix read in the source - nothing ran to check it"

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
    where it is empty - `None` where it is not. The changes' word is said
    beneath their rows as well, of each kind of change that has none.

    The changes, the log messages and what each deployment looked into
    changed are the kinds of evidence no other section is a row for, so
    without them a citation of one would lead nowhere. A deployment's row is
    its diff, a line of the document to each line of it, and is no row at all
    where no deployment was looked into - most incidents look into none, and
    "none read" under a heading for them would say a read was missed. What
    Code-Fix read in the source is a row of its own for the same reason, and
    headed as a reading nothing ran - which is how a cause resting on it is
    weighed - and as proposed only where a pull request holds what it
    proposed. Each file it names that ran as other text than it read is a row
    too, named by its path at the revision and leading to the file there -
    what settles a reading made on other text. And what the metrics show of a
    cause confirmed to be the load, a series to a row, measured by Argus. The log
    messages' heading names the zone their times are in, since each row says a
    time as the model was shown it; a change's row says its moment with its
    zone.

    `revision_addresses` is each revision the changes read name - short, as
    the prose writes one, and whole - and where it opens: the prose names a
    deploy by its revision as well as by its label, and a reader follows
    either. `prose_addresses` is those and the proposed fix, by the name the
    document gives it: an action item naming "PR #7" leads where the fix
    opens. Only the document's own - a pull request it holds nothing of has
    nowhere true to lead.
    """

    model_config = ConfigDict(frozen=True)

    links: tuple[Line, ...]
    changes_heading: str = "Changes to production read"
    changes: tuple[EvidenceRow, ...]
    changes_absent: str | None
    revision_addresses: dict[str, str]
    prose_addresses: dict[str, str]
    log_messages_heading: str = "Log messages read (UTC)"
    log_messages: tuple[EvidenceRow, ...]
    log_messages_absent: str | None
    deployment_changes_heading: str = "What each deployment looked into changed"
    deployment_changes: tuple[EvidenceRow, ...] = ()
    code_read_heading: str = _CODE_READ_AND_PROPOSED
    code_read: tuple[EvidenceRow, ...] = ()
    as_it_ran_heading: str = "What ran, read at the revision running when the alert fired"
    as_it_ran: tuple[EvidenceRow, ...] = ()
    uses_outside_heading: str = ("How the code outside Code-Fix's patch uses what it changes, "
                                 "read off the code")
    uses_outside: tuple[EvidenceRow, ...] = ()
    cause_measured_heading: str = ("What the metrics show of the confirmed cause, measured by "
                                   "Argus")
    cause_measured: tuple[EvidenceRow, ...] = ()
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
                                Run.a_pull_request(fix),
                                Run(text=" ("),
                                Run.an_address(fix.url),
                                Run(text=") "),
                                Run(text=OPENED_AS_A_DRAFT, role=Role.STATUS),
                                Run(text=f". {NOTHING_RECORDED_AFTER_IT_WAS_OPENED}."))))

    changes = tuple(EvidenceRow(label=cited.label, said=_a_change(cited))
                    for cited in postmortem.changes_read)
    log_messages = _rows(postmortem.log_messages_read)
    revision_addresses = the_revision_addresses(postmortem.changes_read)
    shorts = the_short_forms(postmortem.changes_read)
    deployment_changes = tuple(_a_diff_row(cited, revision_addresses, shorts)
                               for cited in postmortem.deployment_changes_read)
    assumptions = tuple(Line(runs=(Run(text=assumption, role=Role.PROSE),))
                        for assumption in postmortem.assumptions)

    return SupportingSection(links=tuple(links),
                             changes=changes,
                             changes_absent=_no_changes(postmortem),
                             revision_addresses=revision_addresses,
                             prose_addresses={**revision_addresses,
                                              **({fix.name: fix.url}
                                                 if fix is not None else {})},
                             log_messages=log_messages,
                             log_messages_absent=(None if log_messages
                                                  else _no_log_messages(postmortem.logs_reading)),
                             deployment_changes=deployment_changes,
                             code_read_heading=(_CODE_READ_ALONE if fix is None
                                                else _CODE_READ_AND_PROPOSED if fix.brings_a_test
                                                else _CODE_READ_AND_PROPOSED_WITHOUT_A_TEST),
                             code_read=tuple(EvidenceRow(label=cited.label,
                                                         said=_as_its_markdown_sets_it(
                                                             cited.text, shorts,
                                                             revision_addresses))
                                             for cited in postmortem.code_read),
                             as_it_ran=tuple(_a_file_row(cited, revision_addresses, shorts)
                                             for cited in postmortem.as_it_ran_read),
                             uses_outside_heading=_the_uses_outside_heading(
                                 postmortem.fix_branch_read),
                             uses_outside=_rows(postmortem.uses_outside_read),
                             cause_measured=_rows(postmortem.cause_measured),
                             assumptions=assumptions,
                             assumptions_absent=None if assumptions else "None.")


def _the_uses_outside_heading(branch: str | None) -> str:
    """What the lines outside Code-Fix's patch are headed by: the branch they
    were read on, where it is known - not the revision that ran, which a reader
    takes rows for unless the heading says otherwise."""
    read = f"read on {branch}" if branch is not None else "read off the code"

    return f"How the code outside Code-Fix's patch uses what it changes, {read}"


def _no_changes(postmortem: PostmortemDocument) -> str | None:
    """What came of reading each kind of change that has no row, each said
    apart: the walk reads the flags every time and the deploys only when the
    investigation asks, so one word for both would say the deploys were read
    whenever the flags were.

    A document written before the readings were carried says "none read" where
    nothing is listed, and nothing beneath rows it does list - what came of
    reading the other kind is not known to it."""
    listed = {cited.change.kind for cited in postmortem.changes_read}
    deploys, flags = postmortem.deploys_reading, postmortem.flags_reading
    if deploys is None or flags is None:
        return None if listed else _NONE_READ

    return changes_not_listed(deploys, flags, listed)


def _no_log_messages(reading: ChannelReading | None) -> str:
    """What came of reading the logs, where none are listed."""
    return _NONE_READ if reading is None else no_logs_listed(reading)


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


def _a_diff_row(cited: CitedEvidence, addresses: dict[str, str],
                shorts: dict[str, str]) -> EvidenceRow:
    """What a deployment changed, as its row says it: each revision said short
    and leading to its commit - the one it was compared against too."""
    beside, beside_short = _the_revisions_beside(cited.text, addresses, shorts)

    return EvidenceRow(label=cited.label,
                       said=Line(runs=_shortened(
                           Run(text=cited.text).with_links({**addresses, **beside}),
                           {**shorts, **beside_short})))


def _a_file_row(cited: CitedEvidence, addresses: dict[str, str],
                shorts: dict[str, str]) -> EvidenceRow:
    """A file as it ran, as its row says it: its path at the revision, the
    path leading to the file there and the revision to its commit, where each
    opens.

    Named, not printed: the file's text is the model's to read, and printed
    whole two files took six pages of a write-up's fourteen."""
    named = cited.text.split("\n", 1)[0]
    path = named.rsplit(_AT_THE_REVISION, 1)[0]
    opens = {path: cited.address} if cited.address is not None else {}

    return EvidenceRow(label=cited.label,
                       said=Line(runs=_shortened(
                           Run(text=named).with_links({**addresses, **opens}), shorts)))


# What sits between a file's path and the revision it ran at, as its row is
# named: "deploy/scrape.yaml at 53f02e9".
_AT_THE_REVISION: Final = " at "


def _the_revisions_beside(said: str, addresses: dict[str, str],
                          shorts: dict[str, str]) -> tuple[dict[str, str], dict[str, str]]:
    """The revisions a diff's first line names that no change read is - the
    one a deploy was compared against - each where it opens and its short
    form: in the deploy's own repository, opened where the deploy's revision
    is but for the revision, and as short as the deploy's is said.

    Only where the deploy's revision is in its own address once: elsewhere
    there is no place to put the other in, and a link to the deploy's commit
    under the other's name would lead somewhere else without saying so. A
    revision with nowhere to open stays as it is, whole."""
    header = said.split("\n", 1)[0]
    named = [found.group() for found in A_REVISION.finditer(header)]
    own = next((revision for revision in named
                if revision in shorts and addresses[revision].count(revision) == 1), None)
    if own is None:
        return {}, {}

    others = [revision for revision in named
              if revision not in addresses and len(revision) == len(own)]
    return ({other: addresses[own].replace(own, other) for other in others},
            {other: other[:len(shorts[own])] for other in others})


def the_revision_addresses(changes: list[CitedChange]) -> dict[str, str]:
    """Each revision a change that can be opened names, short and whole, and
    where it opens.

    Public because the timeline and the hypotheses lead a revision to its
    commit too, and by the same addresses."""
    return {reference: cited.change.revision_source.revision_address
            for cited in changes if cited.change.revision_source is not None
            for reference in (cited.short_reference, cited.change.reference)}


def _as_its_markdown_sets_it(text: str, shorts: dict[str, str],
                             addresses: dict[str, str]) -> Line:
    """What Code-Fix read, set as its Markdown says and with the marks left
    out: the code it quotes between backticks set apart as code, what it wrote
    between double asterisks strong, and an item of a list after a bullet in
    place of its dash. A mark printed is one nobody reading the page or the
    paper was meant to see. Only at display - the model is briefed in its words
    as written.

    Its own words name a revision as the rest of the document does - short,
    and leading to its commit - for one revision said two ways reads as two.
    Code it quotes is quoted as it is, inside strong words as anywhere.

    Asterisks are strong in pairs. One left over has nothing to close it, and
    stays in the words as it came."""
    said = _A_LIST_ITEM.sub(_A_BULLET, text)
    marks = list(_A_MARK.finditer(said))
    strong_marks = [mark for mark in marks if mark.group(1) is None]
    left_over = strong_marks[-1] if len(strong_marks) % 2 else None

    runs: list[Run] = []
    strong, written = False, 0
    for mark in marks:
        if mark is left_over:
            continue

        runs += _words(said[written:mark.start()], strong, shorts, addresses)
        if mark.group(1) is not None:
            runs.append(Run(text=mark.group(1), role=Role.CODE))
        else:
            strong = not strong
        written = mark.end()

    return Line(runs=(*runs, *_words(said[written:], strong, shorts, addresses)))


def _words(said: str, strong: bool, shorts: dict[str, str],
           addresses: dict[str, str]) -> tuple[Run, ...]:
    """Code-Fix's words between two marks, strong or not, each revision in them
    said short and leading to its commit."""
    if not said:
        return ()

    return Run(text=said_short(said, shorts),
               role=Role.STRONG if strong else Role.PLAIN).with_links(addresses)


# What Code-Fix's Markdown is set by: code quoted inline, between single
# backticks on one line, and the double asterisk either side of strong words.
_A_MARK: Final = re.compile(r"`([^`\n]+)`|\*\*")

# An item of a list in Markdown, and what the paper sets one after instead.
_A_LIST_ITEM: Final = re.compile(r"^- ", re.MULTILINE)
_A_BULLET: Final = "• "


def _rows(evidence: list[CitedEvidence]) -> tuple[EvidenceRow, ...]:
    return tuple(EvidenceRow(label=cited.label, said=Line(runs=(Run(text=cited.text),)))
                 for cited in evidence)
