"""What the response cost, out of minutes already measured by title and bands
already published.

Priced by title, because a band prices a title: a total that has already added
a senior engineer's hour to a junior's cannot be priced at all. One pass gives
each title's amounts and the response's in all, so the rows and the total
beside them are one arithmetic rather than two that could disagree.

Three amounts, because a band is a range. The midpoint is what a reader puts
beside the customer loss; the minimum and maximum are what stop that figure
being read as measured to the dollar, since the same incident with the same
people genuinely costs more at the top of the band than at the bottom.

Nothing here reads a source. Both halves - what each title's holders spent and
what the title is worth - are measured elsewhere and handed in, so this is
arithmetic and can be read as such.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Protocol

from pydantic import BaseModel

from incident_cost.sources import PayBand

# What an annual band is divided by, once the working year is in minutes.
_MINUTES_AN_HOUR = Decimal(60)


class TitleShare(Protocol):
    """One title's share of a response, as whatever prices it hands it in: the
    title, `None` where the source recorded none, and the minutes its holders
    spent, added together.

    A protocol rather than a type of this package's, so the rows a document
    stores are priced as they are stored, with nothing copied out of them on
    the way in.
    """

    @property
    def title(self) -> str | None: ...

    @property
    def minutes(self) -> int: ...


class PricedMinutes(BaseModel):
    """Minutes at the middle, bottom and top of the bands that price them."""

    midpoint: Decimal
    minimum: Decimal
    maximum: Decimal


class ResponderCost(BaseModel):
    """What a response cost, title by title and in all.

    `by_title` holds one entry per share handed in, in their order: its
    amounts, or `None` for a share no band prices - a title no band covers, or
    no title at all, since a title nobody knows is a title no band can match.

    `total` is `None` wherever any entry is: a cost missing one of the people
    who responded is not a smaller cost, it is a wrong one - and wrong in the
    flattering direction, which is the one nobody questions. Nobody responding
    is zero rather than `None`: a response nobody made really did cost nothing.
    """

    by_title: list[PricedMinutes | None]
    total: PricedMinutes | None
    # What the bands were quoted in, and `None` where no band priced anything.
    # The first band's, because they come from one source's one table and a
    # source quoting two currencies in one table is a case nothing here has
    # met.
    currency: str | None


def responder_cost(shares: Sequence[TitleShare],
                   bands: Mapping[str, PayBand],
                   working_hours_a_year: float) -> ResponderCost:
    """What those minutes cost at those bands, title by title and in all."""
    a_year = Decimal(str(working_hours_a_year)) * _MINUTES_AN_HOUR
    held = [bands.get(share.title) if share.title is not None else None for share in shares]
    by_title = [_priced(share.minutes, band, a_year) if band is not None else None
                for share, band in zip(shares, held, strict=True)]
    priced = [amounts for amounts in by_title if amounts is not None]

    return ResponderCost(
        by_title=by_title,
        total=(PricedMinutes(midpoint=sum((each.midpoint for each in priced), start=Decimal(0)),
                             minimum=sum((each.minimum for each in priced), start=Decimal(0)),
                             maximum=sum((each.maximum for each in priced), start=Decimal(0)))
               if len(priced) == len(by_title) else None),
        currency=next((band.currency for band in held if band is not None), None)
    )


def _priced(minutes: int, band: PayBand, a_year: Decimal) -> PricedMinutes:
    return PricedMinutes(midpoint=minutes * band.midpoint / a_year,
                         minimum=minutes * band.minimum / a_year,
                         maximum=minutes * band.maximum / a_year)
