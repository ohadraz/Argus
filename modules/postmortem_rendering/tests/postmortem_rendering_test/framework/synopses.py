"""A synopsis as a reader reads it, with something in every part, and the words
the Slack message has to say, in the order it has to say them.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Final, NamedTuple

from postmortem_rendering import Card, Line, Run
from postmortem_rendering.synopsis import CostRow, HumanCost, SynopsisLines


class TitleSpent(NamedTuple):
    """One title's response, as the figures its row is written from."""

    title: str
    people: int
    minutes: int
    midpoint: Decimal


SOME_POSTMORTEM_ADDRESS: Final = "https://argus.example/incidents/kuki/postmortem"
SOME_CURRENCY: Final = "USD"
SOME_FLAG: Final = "monthly-spend-feature"
SOME_TITLE: Final = f"Checkout failed while {SOME_FLAG} was on"
SOME_HEADINGS: Final = {"overview": "Overview", "when": "When", "impact": "Impact",
                        "resolution": "Resolution", "human-cost": "Human cost"}
SOME_WINDOW: Final = "2026-11-09 14:03 to 14:10 UTC"
SOME_STEPS: Final = (f"Turned {SOME_FLAG} off - recovered",
                     "Draft pull request #12 left for review")

A_DURATION_CARD: Final = Card(value="7m 12s", label="onset until back to normal")
A_LOSS_CARD: Final = Card(value=f"1,840.01 {SOME_CURRENCY}", label="customer loss (estimated)",
                          loss_is="measured")

TWO_TITLES_SPENT: Final = (
    TitleSpent("Senior Kuki", people=2, minutes=30, midpoint=Decimal("25.00")),
    TitleSpent("Junior Buki", people=1, minutes=12, midpoint=Decimal("6.00"))
)
THEIR_TOTAL_SPENT: Final = TitleSpent(
    "Total",
    people=sum(spent.people for spent in TWO_TITLES_SPENT),
    minutes=sum(spent.minutes for spent in TWO_TITLES_SPENT),
    midpoint=sum((spent.midpoint for spent in TWO_TITLES_SPENT), Decimal(0))
)

SOME_NOTES: Final = ("Working year: annual pay bands divided by 2000 hours",
                     f"Pay band: {TWO_TITLES_SPENT[0].title} priced at the midpoint of the "
                     f"title's band")


def _minutes_said(minutes: int) -> str:
    return f"{minutes} min"


def _money_said(amount: Decimal) -> str:
    return f"{amount:.2f} {SOME_CURRENCY}"


def _range_said(midpoint: Decimal) -> str:
    """Half the midpoint to twice it, as a band's bottom and top sit about it."""
    return f"{midpoint / 2:.2f} to {midpoint * 2:.2f} {SOME_CURRENCY}"


def a_cost_row(spent: TitleSpent) -> CostRow:
    """The row `spent` is written as, its range half its midpoint to twice it."""
    return CostRow(title=spent.title, people=spent.people,
                   minutes=_minutes_said(spent.minutes),
                   midpoint=_money_said(spent.midpoint),
                   range=_range_said(spent.midpoint))


TWO_ROWS: Final = tuple(a_cost_row(spent) for spent in TWO_TITLES_SPENT)
A_TOTAL_ROW: Final = a_cost_row(THEIR_TOTAL_SPENT)

SOME_OVERVIEW: Final = (f"Checkout failed for {A_DURATION_CARD.value} after a flag change, "
                        f"costing the shop {A_LOSS_CARD.value}; the response cost "
                        f"{_money_said(THEIR_TOTAL_SPENT.midpoint)}.")


def a_synopsis_read(postmortem_at: str | None = SOME_POSTMORTEM_ADDRESS,
                    overview: str = SOME_OVERVIEW) -> SynopsisLines:
    """Something in every part: two impact cards, two steps, two titles, a
    total and the basis beneath them."""
    return SynopsisLines(
        incident_id="5d1c0a2e-0b8f-4e57-9d61-3a2f0c7b9e14",
        title=Line(runs=(Run(text=SOME_TITLE),)),
        headings=SOME_HEADINGS,
        overview=Line(runs=(Run(text=overview),)),
        window=Line(runs=(Run(text=SOME_WINDOW),)),
        impact=(A_DURATION_CARD, A_LOSS_CARD),
        resolution=SOME_STEPS,
        human_cost=HumanCost(rows=TWO_ROWS, total=A_TOTAL_ROW, notes=SOME_NOTES),
        postmortem_at=postmortem_at)


def _every_figure_of(spent: TitleSpent) -> tuple[str, ...]:
    return (spent.title, str(spent.people), _minutes_said(spent.minutes),
            _money_said(spent.midpoint), _range_said(spent.midpoint))


# What the synopsis says, in this order: the title, then each part under its
# heading - the overview, every card's figure and label, every step, every row
# with its people, minutes, midpoint and range, the total, the basis - and the
# address.
EVERY_PART_IN_ORDER: Final = (
    SOME_TITLE,
    SOME_HEADINGS["overview"], SOME_OVERVIEW,
    SOME_HEADINGS["when"], SOME_WINDOW,
    SOME_HEADINGS["impact"], A_DURATION_CARD.value, A_DURATION_CARD.label,
    A_LOSS_CARD.value, A_LOSS_CARD.label,
    SOME_HEADINGS["resolution"], *SOME_STEPS,
    SOME_HEADINGS["human-cost"],
    *(figure for spent in (*TWO_TITLES_SPENT, THEIR_TOTAL_SPENT)
      for figure in _every_figure_of(spent)),
    *SOME_NOTES,
    SOME_POSTMORTEM_ADDRESS
)


def the_parts_missing_or_out_of_order(said: str) -> list[str]:
    """Each of `EVERY_PART_IN_ORDER` not found after the one before it - empty
    where the form says every part, in order."""
    missing: list[str] = []
    after = 0
    for part in EVERY_PART_IN_ORDER:
        found = said.find(part, after)
        if found < 0:
            missing.append(part)
        else:
            after = found + len(part)

    return missing
