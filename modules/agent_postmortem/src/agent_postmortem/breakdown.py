"""Whether the cost by title, read again for the synopsis, agrees with the
postmortem's stored totals.

The synopsis reads the minutes and bands a second time rather than changing the
postmortem to hand them over. A source that moved in between - a band
republished, a responder who acknowledged late - gives rows that the totals
beside them would contradict, and one figure said two ways is worse than a
breakdown left out.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import Final

from argus_core.models import PostmortemDocument, TitleCost

# Amounts agree to the cent: grouping adds the same terms in another order, and
# 28 digits of Decimal can differ in the last one.
_A_CENT: Final = Decimal("0.01")


def agreeing_breakdown(rows: Sequence[TitleCost],
                       currency: str | None,
                       postmortem: PostmortemDocument) -> list[TitleCost] | None:
    """The rows, where their people, minutes, amounts and currency agree with
    the postmortem's totals - or `None` where any of them does not.

    A postmortem that published no cost agrees with rows only where one of them
    is unpriced too: that row is why there is no cost. One that published a
    cost agrees only with rows that are all priced, in its currency.
    """
    people = sum(row.responders for row in rows)
    minutes = sum(row.minutes for row in rows)
    if people != postmortem.responders or minutes != postmortem.engineer_minutes:
        return None

    unpriced = any(row.midpoint is None for row in rows)
    if postmortem.responder_cost_estimate is None:
        return list(rows) if unpriced else None

    if unpriced or (rows and currency != postmortem.responder_cost_currency):
        return None

    totals = (postmortem.responder_cost_estimate,
              postmortem.responder_cost_minimum,
              postmortem.responder_cost_maximum)
    summed = (_sum_of(rows, "midpoint"), _sum_of(rows, "minimum"), _sum_of(rows, "maximum"))

    agree = all(total is not None and _to_the_cent(total) == _to_the_cent(amount)
                for total, amount in zip(totals, summed, strict=True))

    return list(rows) if agree else None


def _sum_of(rows: Sequence[TitleCost], amount: str) -> Decimal:
    """One amount summed over rows already known to be priced."""
    return sum((getattr(row, amount) for row in rows), start=Decimal(0))


def _to_the_cent(amount: Decimal) -> Decimal:
    return amount.quantize(_A_CENT)
