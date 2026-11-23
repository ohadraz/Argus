"""What the response cost, priced for the synopsis from the postmortem's minutes
by title.

The postmortem stores who responded and for how long, title by title, and
never what that was worth: its readers are the people it would price. The
synopsis is read by the people who lead, so it is where the response is
priced - once, here, the bands read once and every row and total worked out in
one pass (`incident_cost`), before the overview is asked for, so the figure
the overview names is the one the synopsis shows.
"""

from __future__ import annotations

from collections.abc import Sequence

from core.models import PricedResponse, TitleCost, TitleMinutes
from incident_cost import MoneySources, PricedMinutes, responder_cost, response_cost_basis


def the_response_priced(held: Sequence[TitleMinutes], money: MoneySources) -> PricedResponse:
    """Each title's minutes priced at its band, the response in all, and how.

    Nothing is read where nobody responded, or nobody could say who did: there
    is no response to price. Where the bands cannot be read, every row is
    unpriced and the basis says why. The totals are absent wherever any row is
    unpriced.
    """
    if not held:
        return PricedResponse()

    bands = money.bands()
    basis = response_cost_basis(held, bands, money.working_hours_a_year)
    if bands is None:
        return PricedResponse(cost_by_title=[_the_row(row, None) for row in held],
                              response_cost_basis=basis)

    cost = responder_cost(held, bands, money.working_hours_a_year)
    total = cost.total

    return PricedResponse(
        cost_by_title=[_the_row(row, amounts)
                       for row, amounts in zip(held, cost.by_title, strict=True)],
        responder_cost_estimate=total.midpoint if total is not None else None,
        responder_cost_minimum=total.minimum if total is not None else None,
        responder_cost_maximum=total.maximum if total is not None else None,
        responder_cost_currency=cost.currency,
        response_cost_basis=basis)


def _the_row(row: TitleMinutes, amounts: PricedMinutes | None) -> TitleCost:
    return TitleCost(title=row.title,
                     responders=row.responders,
                     minutes=row.minutes,
                     midpoint=amounts.midpoint if amounts is not None else None,
                     minimum=amounts.minimum if amounts is not None else None,
                     maximum=amounts.maximum if amounts is not None else None)
