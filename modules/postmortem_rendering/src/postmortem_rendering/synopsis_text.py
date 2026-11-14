"""The synopsis in words: each part as the lines it is said in.

The parts are worded here once, so whatever comes to print the synopsis says it
in the same words.
"""

from __future__ import annotations

from typing import NamedTuple

from postmortem_rendering.impact import Card
from postmortem_rendering.synopsis import CostRow, SynopsisLines


class Part(NamedTuple):
    """One part under its heading: its lines, and whether they are a list -
    each said as an item - rather than lines read in turn."""

    heading: str
    lines: tuple[str, ...]
    listed: bool = False


def the_parts(synopsis: SynopsisLines) -> tuple[Part, ...]:
    """Every part, in the order the synopsis reads, each under its heading."""
    cost = synopsis.human_cost
    said = {
        "overview": Part(synopsis.headings["overview"], (synopsis.overview.said,)),
        "when": Part(synopsis.headings["when"], (synopsis.window.said,)),
        "impact": Part(synopsis.headings["impact"],
                       tuple(card_said(card) for card in synopsis.impact)),
        "resolution": Part(synopsis.headings["resolution"], synopsis.resolution, listed=True),
        "human-cost": Part(synopsis.headings["human-cost"],
                           (*(_a_row(row) for row in cost.rows),
                            *((_a_row(cost.total),) if cost.total is not None else ()),
                            *cost.notes))
    }

    return tuple(said[key] for key in synopsis.headings)


def card_said(card: Card) -> str:
    """A figure, what it is, and what supports it where anything does - as the
    synopsis and the postmortem as text both say a tile."""
    note = f" ({card.note})" if card.note else ""

    return f"{card.value} - {card.label}{note}"


def _a_row(row: CostRow) -> str:
    """A title's people, minutes and cost at its band's midpoint with the
    range - or that nothing priced it."""
    people = f"{row.people} {'person' if row.people == 1 else 'people'}"
    cost = f"{row.midpoint} ({row.range})" if row.midpoint is not None else "not priced"

    return f"{row.title}: {people}, {row.minutes}, {cost}"
