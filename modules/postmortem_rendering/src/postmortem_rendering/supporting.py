"""Where to read more: every address Argus keeps for the incident, the changes
and log messages the prose cites, and what was assumed.

Every address in full: the document is read away from the screen it came from,
where an address relative to nothing leads nowhere.
"""

from __future__ import annotations

from typing import Final

from argus_core import parse_iso
from argus_core.models import (
    ChangeEvent,
    ChangeKind,
    CitedChange,
    CitedEvidence,
    PostmortemDocument,
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
                                Run(text=f"#{fix.number} {fix.url}", role=Role.LINK,
                                    address=fix.url),
                                Run(text=" "),
                                Run(text="draft - nobody has merged it", role=Role.STATUS))))

    changes = tuple(EvidenceRow(label=cited.label, said=_a_change(cited))
                    for cited in postmortem.changes_read)
    log_messages = _rows(postmortem.log_messages_read)
    revision_addresses = _the_revision_addresses(postmortem.changes_read)
    deployment_changes = tuple(
        EvidenceRow(label=cited.label,
                    said=Line(runs=Run(text=cited.text).with_links(revision_addresses)))
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
                             code_read=_rows(postmortem.code_read),
                             assumptions=assumptions,
                             assumptions_absent=None if assumptions else "None.")


def _a_change(cited: CitedChange) -> Line:
    """A change as its row says it: when, what kind, to what, by whom, and what
    it did.

    Its reference short, as the prose names it, and what it did in the words
    the model read, which name a revision whole. Where it can be opened, the
    revision - short and whole - the repository and the directory each lead
    there; where it cannot, the reference is a name, said as one.
    """
    change = cited.change

    return Line(runs=(Run.a_moment(parse_iso(change.occurred_at)),
                      Run(text=f" {_A_KIND_IN_WORDS[change.kind]} "),
                      a_reference(cited),
                      Run(text=f" by {change.actor or _NOBODY_NAMED}: "),
                      *Run(text=change.summary).with_links(_the_addresses_of(change))))


def a_reference(cited: CitedChange) -> Run:
    """A change read named as its row names it: short, as the prose writes it,
    leading where it can be opened - and, where it cannot, a name said as one.

    Public because the trigger names the deploy that carried it the same way,
    and a document naming one revision two ways reads as naming two."""
    source = cited.change.revision_source

    return (Run(text=cited.short_reference, role=Role.LINK, address=source.revision_address)
            if source is not None else Run(text=cited.short_reference, role=Role.CODE))


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


def _the_revision_addresses(changes: list[CitedChange]) -> dict[str, str]:
    """Each revision a change that can be opened names, short and whole, and
    where it opens."""
    return {reference: cited.change.revision_source.revision_address
            for cited in changes if cited.change.revision_source is not None
            for reference in (cited.short_reference, cited.change.reference)}


def _rows(evidence: list[CitedEvidence]) -> tuple[EvidenceRow, ...]:
    return tuple(EvidenceRow(label=cited.label, said=Line(runs=(Run(text=cited.text),)))
                 for cited in evidence)
