"""An amount of money in the one spelling every reader says it in.

Here rather than beside any one reader, for the reason `Refusal`'s sentences
are: the page, the brief and the narration all state the customer loss, and
three spellings of one figure read as three figures - worse where they round it
differently and disagree in the last cent.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Final

_A_CENT: Final = Decimal("0.01")


def said_as_money(amount: Decimal, currency: str | None) -> str:
    """An amount to the cent, its thousands grouped and its currency after it:
    `1,736.68 USD` - or the amount alone where nobody said its currency, since
    a currency guessed for it is a figure in somebody else's money.

    Half a cent rounds up, as a reader checking the figure by hand rounds it.
    """
    said = f"{amount.quantize(_A_CENT, rounding=ROUND_HALF_UP):,}"

    return f"{said} {currency.upper()}" if currency else said
