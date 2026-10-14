"""Where to read more: every address Argus keeps for the incident, how much
evidence was read, and what was assumed.

Every address in full: the document is read away from the screen it came from,
where an address relative to nothing leads nowhere.
"""

from __future__ import annotations

from argus_core.models import PostmortemDocument
from pydantic import BaseModel, ConfigDict

from postmortem_rendering.lines import Line, Role, Run


class SupportingSection(BaseModel):
    """The links and the evidence count, one line each; the assumptions; and
    the word said in their place where there are none - `None` where there
    are."""

    model_config = ConfigDict(frozen=True)

    links: tuple[Line, ...]
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

    assumptions = tuple(Line(runs=(Run(text=assumption, role=Role.PROSE),))
                        for assumption in postmortem.assumptions)

    return SupportingSection(links=tuple(links),
                             assumptions=assumptions,
                             assumptions_absent=None if assumptions else "None.")
