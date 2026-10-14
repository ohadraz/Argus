"""The incident in order: every line of its narration in UTC, with the four
markers Argus placed.

The date where the day changes, and only there: a time of day alone reads in
order within one day, and an incident spanning days would read as time running
backwards.
"""

from __future__ import annotations

from typing import Final

from argus_core.models import PostmortemDocument
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
    """The account as the agent laid it out, its markers already in place."""
    rows = []
    day = None

    for entry in postmortem.timeline:
        said_day = on_the_clock(entry.at, _THE_DAY)
        at = on_the_clock(entry.at) if said_day == day else f"{said_day} {on_the_clock(entry.at)}"
        day = said_day

        rows.append(TimelineRow(label=entry.label,
                                at=at,
                                marker=entry.marker.value.upper() if entry.marker else None,
                                who=entry.who,
                                text=Line(runs=(Run(text=entry.text, role=Role.NARRATION),))))

    return TimelineSection(zone="(UTC)",
                           rows=tuple(rows),
                           absent=None if rows else "No timeline was recorded.")
