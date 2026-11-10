"""The executive synopsis as a reader reads it, worked out once for the Slack
message.

Every figure is the postmortem page's own, worded by the same code - the
window its head says, the cards its Impact shows, the steps its Resolution
lists - so the synopsis and the page it links to never state one figure two
ways. The human cost is the one part the page does not have: per title, with
its range, beside a total that is the stored postmortem's to the cent and the
basis it rests on.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal
from typing import Final

from argus_core.models import Alert, ExecutiveSynopsis, Postmortem, TitleCost, said_as_money
from pydantic import BaseModel, ConfigDict

from postmortem_rendering.head import a_head, a_title
from postmortem_rendering.impact import Card, the_impact
from postmortem_rendering.lines import Line, Role, Run
from postmortem_rendering.resolution import ReportedResolution
from postmortem_rendering.resolution_list import the_resolution_list
from postmortem_rendering.synopsis_figures import the_synopsis_figures

# Every part by the name a destination knows it by, and the heading it is shown
# under, in the order a reader asks: what happened, when, how bad, what was
# done, and what it cost the people who answered.
_HEADINGS: Final = {
    "overview": "Overview",
    "when": "When",
    "impact": "Impact",
    "resolution": "Resolution",
    "human-cost": "Human cost"
}

_NO_TITLE: Final = "No title recorded"
_TOTAL: Final = "Total"
_UNMATCHED: Final = ("The cost by title could not be matched to the postmortem's totals, so "
                     "only the totals are shown.")
_NOBODY_PAGED: Final = "Nobody was paged for this incident."
_NOBODY_ACKNOWLEDGED: Final = ("Somebody was paged for this incident, and nobody acknowledged "
                               "the page.")
_UNREAD: Final = "Who responded could not be read."

_CENTS: Final = Decimal(100)


class CostRow(BaseModel):
    """One row of the human cost: a title, or the total - how many people,
    their minutes, and their cost at the band's midpoint with its range.
    `midpoint` and `range` are `None` together, for a title nothing priced."""

    model_config = ConfigDict(frozen=True)

    title: str
    people: int
    minutes: str
    midpoint: str | None
    range: str | None


class HumanCost(BaseModel):
    """The rows, the total - `None` where nobody responded, or nobody could
    say who did, or one row says it already - and what is said beneath them:
    the basis, a page shared with other incidents, a breakdown left out, or why
    there is no cost at all."""

    model_config = ConfigDict(frozen=True)

    rows: tuple[CostRow, ...]
    total: CostRow | None
    notes: tuple[str, ...]


class SynopsisLines(BaseModel):
    """Everything the synopsis says, worked out once for every destination.

    `headings` names each part, in order, by the key a destination knows it by.
    `postmortem_at` is the full postmortem's address, the one address of
    Argus's the synopsis carries - `None` where none is configured.
    """

    model_config = ConfigDict(frozen=True)

    incident_id: str
    title: Line
    headings: dict[str, str]
    overview: Line
    window: Line
    impact: tuple[Card, ...]
    resolution: tuple[str, ...]
    human_cost: HumanCost
    postmortem_at: str | None


def the_synopsis(synopsis: ExecutiveSynopsis,
                 postmortem: Postmortem,
                 alert: Alert,
                 resolution: ReportedResolution | None,
                 postmortem_at: str | None) -> SynopsisLines:
    """A written synopsis as it is read, beside the postmortem it was written
    from and a person's resolution, read off the record as the page reads it.
    Refuses one given up: there is no overview to read, and nothing is sent for
    it."""
    if synopsis.overview is None:
        raise ValueError(f"the synopsis of incident [{synopsis.incident_id}] was withheld")

    return SynopsisLines(
        incident_id=synopsis.incident_id,
        title=a_title(postmortem, alert),
        headings=dict(_HEADINGS),
        overview=Line(runs=(Run(text=synopsis.overview, role=Role.PROSE),)),
        window=_the_window(postmortem, alert),
        impact=the_impact(postmortem, alert).cards,
        resolution=the_resolution_list(postmortem, resolution),
        human_cost=_the_human_cost(synopsis, postmortem),
        postmortem_at=postmortem_at)


def _the_window(postmortem: Postmortem, alert: Alert) -> Line:
    """From and to as the page's head says them, and how long, as the
    duration's tile says it: from and to alone leave a reader to subtract. A
    disproven alarm had no stretch, so its window says none."""
    window = a_head(postmortem, alert, None).date
    lasted = the_synopsis_figures(postmortem, alert).get("duration")
    if lasted is None:
        return window

    return Line(runs=(*window.runs, Run(text=f" ({lasted})")))


def _the_human_cost(synopsis: ExecutiveSynopsis, postmortem: Postmortem) -> HumanCost:
    """Each title's row and the postmortem's total, with the basis beneath -
    or, where nobody responded, why there is nothing to show."""
    if postmortem.responders is None or postmortem.engineer_minutes is None:
        return HumanCost(rows=(), total=None, notes=(_UNREAD,))

    if postmortem.responders == 0:
        # Nobody both ways: whether a page went out tells which.
        return HumanCost(rows=(), total=None,
                         notes=(_NOBODY_ACKNOWLEDGED if postmortem.paged else _NOBODY_PAGED,))

    currency = postmortem.responder_cost_currency
    total = CostRow(title=_TOTAL,
                    people=postmortem.responders,
                    minutes=_minutes(postmortem.engineer_minutes),
                    midpoint=_money(postmortem.responder_cost_estimate, currency),
                    range=_range(postmortem.responder_cost_minimum,
                                 postmortem.responder_cost_maximum, currency))
    rows = _the_rows(synopsis.cost_by_title, postmortem)

    return HumanCost(
        rows=rows,
        # Beneath one row, a total says the row again: rows add up to it.
        total=total if len(rows) != 1 else None,
        notes=(*postmortem.response_cost_basis,
               *((synopsis.response_shared,) if synopsis.response_shared else ()),
               *((_UNMATCHED,) if synopsis.breakdown_unmatched else ())))


def _the_rows(rows: Sequence[TitleCost], postmortem: Postmortem) -> tuple[CostRow, ...]:
    """Each title's row, its amounts rounded so the column adds up to the
    total shown beside it - the cents a plain rounding leaves over going to
    the rows with the largest remainders. Rounded plainly where the postmortem
    has no total for them to add up to."""
    currency = postmortem.responder_cost_currency
    midpoints = _adding_up([row.midpoint for row in rows], postmortem.responder_cost_estimate)
    minimums = _adding_up([row.minimum for row in rows], postmortem.responder_cost_minimum)
    maximums = _adding_up([row.maximum for row in rows], postmortem.responder_cost_maximum)

    return tuple(CostRow(title=row.title if row.title is not None else _NO_TITLE,
                         people=row.responders,
                         minutes=_minutes(row.minutes),
                         midpoint=_money(midpoint, currency),
                         range=_range(minimum, maximum, currency))
                 for row, midpoint, minimum, maximum
                 in zip(rows, midpoints, minimums, maximums, strict=True))


def _adding_up(amounts: list[Decimal | None], total: Decimal | None) -> list[Decimal | None]:
    """`amounts` to the cent, adding up to `total` to the cent as the total is
    shown - where every amount and the total are known."""
    if total is None or any(amount is None for amount in amounts):
        return amounts

    cents = [amount * _CENTS for amount in amounts if amount is not None]
    kept = [each.to_integral_value(rounding=ROUND_FLOOR) for each in cents]
    short = int((total * _CENTS).quantize(Decimal(1), rounding=ROUND_HALF_UP) - sum(kept))
    # Largest remainder first; equal remainders in the order the rows are read.
    by_remainder = sorted(range(len(cents)), key=lambda place: cents[place] - kept[place],
                          reverse=True)
    for place in by_remainder[:max(short, 0)]:
        kept[place] += 1
    for place in list(reversed(by_remainder))[:max(-short, 0)]:
        kept[place] -= 1

    rounded: list[Decimal | None] = [each / _CENTS for each in kept]

    return rounded


def _minutes(minutes: int) -> str:
    """Minutes as the postmortem's response effort says them."""
    return f"{minutes} min" if minutes else "none"


def _money(amount: Decimal | None, currency: str | None) -> str | None:
    return said_as_money(amount, currency) if amount is not None else None


def _range(minimum: Decimal | None, maximum: Decimal | None, currency: str | None) -> str | None:
    """From the bottom of the band to the top, the currency said once."""
    if minimum is None or maximum is None:
        return None

    return f"{said_as_money(minimum, None)} to {said_as_money(maximum, currency)}"
