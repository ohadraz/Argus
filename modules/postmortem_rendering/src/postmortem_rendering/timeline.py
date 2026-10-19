"""The incident in order: every line of its narration in UTC, with the four
markers Argus placed.

The date where the day changes, and only there: a time of day alone reads in
order within one day, and an incident spanning days would read as time running
backwards.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from typing import Final

from argus_core import said_short
from argus_core.models import PostmortemDocument, RecordedPlacement
from argus_narration import as_shown
from pydantic import BaseModel, ConfigDict

from postmortem_rendering.formatting import on_the_clock
from postmortem_rendering.lines import Line, Role, Run
from postmortem_rendering.supporting import the_revision_addresses, the_short_forms

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

    A line of the walk names a revision whole, or by as much of it as the
    model liked; either is said by the change's short form, as the dashboard
    and the channel say it. A line from outside the walk - a person's among
    them - is said as it was written: its brackets, its revisions whole, and
    nothing in it a link, which is how the dashboard shows it too.

    A line recording where the replicas ran is said in a line of its own where
    the listing tells nothing apart, laid out from the placement it carries
    rather than from its sentence - which stays as the model was told it.
    """
    candidates = {label for hypothesis in postmortem.hypotheses
                  for label in (hypothesis.label, *hypothesis.also) if label}
    shorts = the_short_forms(postmortem.changes_read)
    addresses = the_revision_addresses(postmortem.changes_read)
    rows = []
    day = None

    for entry in postmortem.timeline:
        said_day = on_the_clock(entry.at, _THE_DAY)
        at = on_the_clock(entry.at) if said_day == day else f"{said_day} {on_the_clock(entry.at)}"
        day = said_day

        collapsed = _one_card_long_before(entry.placement) if entry.placement else None
        if collapsed is not None:
            said = _said(collapsed, candidates, {})
        elif entry.outside_the_walk:
            said = _said(entry.text, candidates, {})
        else:
            said = _said(as_shown(said_short(entry.text, shorts)), candidates, addresses)
        rows.append(TimelineRow(label=entry.label,
                                at=at,
                                marker=entry.marker.value.upper() if entry.marker else None,
                                who=entry.who,
                                text=Line(runs=said)))

    return TimelineSection(zone="(UTC)",
                           rows=tuple(rows),
                           absent=None if rows else "No timeline was recorded.")


def _one_card_long_before(placement: RecordedPlacement) -> str | None:
    """Where the replicas ran said in a line, where the full listing tells
    nothing apart: several pods, every one on the same card, and none come up
    at the onset or since. `None` wherever the listing is the finding - the
    cards differ, a pod came up at the onset, or a node reported no card."""
    cards = {pod.accelerator for pod in placement.pods}

    if len(placement.pods) < 2 or len(cards) != 1 or placement.started_at_the_onset():
        return None

    card = next(iter(cards))
    if card is None:
        return None

    return f"Recorded where the {len(placement.pods)} replicas run - all on {card}"


def _said(text: str, candidates: Collection[str],
          addresses: Mapping[str, str]) -> tuple[Run, ...]:
    """A line of the narration cut at every candidate it cites and every
    revision in `addresses` it names."""
    return tuple(run
                 for cited in Run(text=text, role=Role.NARRATION).with_citations(candidates)
                 for run in (cited.with_links(addresses) if cited.role is Role.NARRATION
                             else (cited,)))
