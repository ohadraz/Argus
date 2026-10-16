"""The incident in order: every line of its narration in UTC, with the four
markers Argus placed.

The date where the day changes, and only there: a time of day alone reads in
order within one day, and an incident spanning days would read as time running
backwards.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from typing import Final

from argus_core.models import PostmortemDocument
from argus_narration import as_shown
from pydantic import BaseModel, ConfigDict

from postmortem_rendering.formatting import on_the_clock
from postmortem_rendering.lines import Line, Role, Run

_THE_DAY: Final = "%b %d"


class TimelineRow(BaseModel):
    """One line of the account: when, the marker it carries in capitals, who
    said it, and what. `label` is the row's name for a citation."""

    model_config = ConfigDict(frozen=True)

    label: str | None
    at: str
    marker: str | None
    who: str | None
    text: Line


class TimelineSection(BaseModel):
    """The rows, the zone their times are in - said once rather than on every
    row - and the sentence said in their place where there are none."""

    model_config = ConfigDict(frozen=True)

    zone: str
    rows: tuple[TimelineRow, ...]
    absent: str | None


def the_timeline(postmortem: PostmortemDocument) -> TimelineSection:
    """The account as the agent laid it out, its markers already in place.

    A line naming the candidates it formed cites each one with a row among the
    hypotheses considered, so a reader follows "C1" to what C1 was. A line
    naming a revision a change read can be opened at names it short, as the
    rest of the document does, and leads to it; the record keeps it whole.

    A line of the walk is shown without the brackets it quotes a name in for
    the model - before it is cut, so a revision in brackets is still found
    whole. A line from outside the walk - a person's among them - keeps its
    brackets.
    """
    candidates = {label for hypothesis in postmortem.hypotheses
                  for label in (hypothesis.label, *hypothesis.also) if label}
    revisions = {cited.change.reference: (cited.short_reference, source.revision_address)
                 for cited in postmortem.changes_read
                 if (source := cited.change.revision_source) is not None}
    rows = []
    day = None

    for entry in postmortem.timeline:
        said_day = on_the_clock(entry.at, _THE_DAY)
        at = on_the_clock(entry.at) if said_day == day else f"{said_day} {on_the_clock(entry.at)}"
        day = said_day

        text = entry.text if entry.outside_the_walk else as_shown(entry.text)
        rows.append(TimelineRow(label=entry.label,
                                at=at,
                                marker=entry.marker.value.upper() if entry.marker else None,
                                who=entry.who,
                                text=Line(runs=_said(text, candidates, revisions))))

    return TimelineSection(zone="(UTC)",
                           rows=tuple(rows),
                           absent=None if rows else "No timeline was recorded.")


def _said(text: str, candidates: Collection[str],
          revisions: Mapping[str, tuple[str, str]]) -> tuple[Run, ...]:
    """A line of the narration cut at every candidate it cites and every
    revision it names, each revision said by its short form."""
    addresses = {whole: address for whole, (_short, address) in revisions.items()}
    return tuple(run.model_copy(update={"text": revisions[run.text][0]})
                 if run.role is Role.LINK else run
                 for cited in Run(text=text, role=Role.NARRATION).with_citations(candidates)
                 for run in (cited.with_links(addresses) if cited.role is Role.NARRATION
                             else (cited,)))
