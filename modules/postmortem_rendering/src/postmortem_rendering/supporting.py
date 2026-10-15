"""Where to read more: every address Argus keeps for the incident, how much
evidence was read, the changes and log messages the prose cites, and what was
assumed.

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
    """The links and the evidence count, one line each; the changes and the
    log messages read, each a labelled row; the assumptions; and the word said
    in place of each list where it is empty - `None` where it is not.

    The changes and log messages are the two kinds of evidence no other
    section is a row for, so without them a citation of one would lead
    nowhere. The log messages' heading names the zone their times are in,
    since each row says a time as the model was shown it; a change's row says
    its moment with its zone.
    """

    model_config = ConfigDict(frozen=True)

    links: tuple[Line, ...]
    changes_heading: str = "Changes to production read"
    changes: tuple[EvidenceRow, ...]
    changes_absent: str | None
    log_messages_heading: str = "Log messages read (UTC)"
    log_messages: tuple[EvidenceRow, ...]
    log_messages_absent: str | None
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

    read = postmortem.evidence_read
    counted = read if read is not None else "not counted"
    links.append(Line(runs=(Run(text=f"Evidence read: {counted}"),)))

    changes = tuple(EvidenceRow(label=cited.label, said=_a_change(cited))
                    for cited in postmortem.changes_read)
    log_messages = _rows(postmortem.log_messages_read)
    assumptions = tuple(Line(runs=(Run(text=assumption, role=Role.PROSE),))
                        for assumption in postmortem.assumptions)

    return SupportingSection(links=tuple(links),
                             changes=changes,
                             changes_absent=None if changes else _NONE_READ,
                             log_messages=log_messages,
                             log_messages_absent=None if log_messages else _NONE_READ,
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
    source = change.revision_source
    reference = (Run(text=cited.short_reference, role=Role.LINK, address=source.revision_address)
                 if source is not None else Run(text=cited.short_reference, role=Role.CODE))

    return Line(runs=(Run.a_moment(parse_iso(change.occurred_at)),
                      Run(text=f" {_A_KIND_IN_WORDS[change.kind]} "),
                      reference,
                      Run(text=f" by {change.actor or _NOBODY_NAMED}: "),
                      *Run(text=change.summary).with_links(_the_addresses_of(change))))


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


def _rows(evidence: list[CitedEvidence]) -> tuple[EvidenceRow, ...]:
    return tuple(EvidenceRow(label=cited.label, said=Line(runs=(Run(text=cited.text),)))
                 for cited in evidence)
