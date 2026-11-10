"""What the response cost one title at a time, for the executive synopsis.

The postmortem's own figure (`responder_cost`) adds every responder into one
total, and is not changed by this. The synopsis shows the same minutes at the
same bands kept apart by title - a title rather than a person, since a band
prices a title - so its rows and the postmortem's total add up to the same.

Nothing here reads a source: the minutes and the bands are handed in, as they
are to `responder_cost`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal

from argus_core.models import TitleCost

from agent_postmortem.sources import EngagedResponder, PayBand

# What an annual band is divided by, once the working year is in minutes.
_MINUTES_AN_HOUR = Decimal(60)


def cost_by_title(engaged: Sequence[EngagedResponder],
                  bands: Mapping[str, PayBand],
                  working_hours_a_year: float) -> list[TitleCost]:
    """One row per title, in the order each title first responded: how many
    held it, their minutes, and those minutes at the bottom, middle and top of
    its band.

    Responders with no recorded title are a row of their own, and they and a
    title no band covers are unpriced - no amounts, never zero - so the rows
    still count everyone who responded without pricing anyone short.
    """
    minutes_by_title: dict[str | None, list[int]] = {}
    for responder in engaged:
        minutes_by_title.setdefault(responder.job_title, []).append(responder.minutes)

    a_year = Decimal(str(working_hours_a_year)) * _MINUTES_AN_HOUR

    return [_the_row(title, minutes, bands.get(title) if title is not None else None, a_year)
            for title, minutes in minutes_by_title.items()]


def _the_row(title: str | None,
             minutes: list[int],
             band: PayBand | None,
             a_year: Decimal) -> TitleCost:
    """One title's row, priced where a band covers it."""
    spent = sum(minutes)

    return TitleCost(
        title=title,
        responders=len(minutes),
        minutes=spent,
        midpoint=spent * band.midpoint / a_year if band is not None else None,
        minimum=spent * band.minimum / a_year if band is not None else None,
        maximum=spent * band.maximum / a_year if band is not None else None
    )
