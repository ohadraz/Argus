"""A level said as a person says it: to three figures, and never fewer than
its whole part has.

One rule in one place, because the postmortem's prose and its impact cards
each write the series a paging rule watches, and a level written two ways is
two figures to a reader comparing them.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Final

# How many figures a level is written to, as a reader compares two.
_LEVEL_FIGURES: Final = 3


def said_as_a_level(level: float) -> str:
    """A level to three figures, the way a reader compares two levels - and
    never fewer than its whole part has, since "1230" reads as an exact count.
    Never in exponent form."""
    exact = Decimal(str(level))
    if exact == 0:
        return "0"

    places = max(_LEVEL_FIGURES - exact.adjusted() - 1, 0)
    rounded = exact.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)

    return f"{rounded.normalize():f}"
