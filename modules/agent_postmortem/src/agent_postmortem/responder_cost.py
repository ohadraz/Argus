"""What the response cost, out of minutes already measured and bands already
published.

Two figures, because a band is a range. The midpoint is what a reader puts
beside the customer loss; the minimum and maximum are what stop that figure
being read as measured to the dollar, since the same incident with the same
people genuinely costs more at the top of the band than at the bottom.

Nothing here reads a source. Both halves - what each person spent and what
their title is worth - are measured elsewhere and handed in, so this is
arithmetic and can be read as such.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal

from pydantic import BaseModel

from agent_postmortem.sources import EngagedResponder, PayBand

# What an annual band is divided by, once the working year is in minutes.
_MINUTES_AN_HOUR = Decimal(60)


class ResponderCost(BaseModel):
    """What an incident's responders cost, and how wide that figure is.

    `midpoint` is the figure; `minimum` and `maximum` are the same minutes at
    the bottom and top of the same bands. All three, because publishing the
    midpoint alone would let a range of tens of thousands read as one number
    somebody measured.
    """

    midpoint: Decimal
    minimum: Decimal
    maximum: Decimal
    # What the bands were quoted in, and `None` where no band was consulted -
    # an incident nobody responded to. The figure is a real zero; the currency
    # is genuinely unknown, and an empty string would be a label pretending to
    # be one.
    currency: str | None


def responder_cost(engaged: Sequence[EngagedResponder],
                   bands: Mapping[str, PayBand],
                   working_hours_a_year: float) -> ResponderCost | None:
    """What those minutes cost at those bands, or `None` where any of them
    cannot be priced.

    `None`, never a partial sum: a cost missing one of the people who responded
    is not a smaller cost, it is a wrong one - and wrong in the flattering
    direction, which is the one nobody questions. A responder the source held
    no title for is the same case, since a title nobody knows is a title no
    band can match.

    Nobody engaged is zero rather than `None`. An incident that resolved with
    no person on it really did cost nothing in people's time.
    """
    if unpriced_titles(engaged, bands):
        return None

    a_year = Decimal(str(working_hours_a_year)) * _MINUTES_AN_HOUR
    priced = [(responder, bands[str(responder.job_title)])
              for responder in engaged]

    return ResponderCost(
        midpoint=sum((responder.minutes * band.midpoint / a_year
                      for responder, band in priced), start=Decimal(0)),
        minimum=sum((responder.minutes * band.minimum / a_year
                     for responder, band in priced), start=Decimal(0)),
        maximum=sum((responder.minutes * band.maximum / a_year
                     for responder, band in priced), start=Decimal(0)),
        currency=_the_currency_of(priced)
    )


def unpriced_titles(engaged: Sequence[EngagedResponder],
                    bands: Mapping[str, PayBand]) -> list[str]:
    """What the responders held that no band covers, in the order they appear.

    A responder with no title at all is reported as such rather than skipped:
    the document has to say why it published no cost, and "one responder's
    title was not recorded" is a different sentence from "Principal Engineer
    has no band".

    Separate from `responder_cost` because the two answer different questions -
    one is the figure, the other is what the document says instead of it - and
    a single function returning both would make every caller unpack a pair to
    reach the half it wanted.
    """
    return list(dict.fromkeys(
        responder.job_title or _NO_TITLE
        for responder in engaged
        if responder.job_title is None or responder.job_title not in bands
    ))


# What an absent title is called where one has to be named. A responder the
# source held no title for still has to appear in the reason a figure is
# missing, or the document reports a gap it cannot explain.
_NO_TITLE = "(no title recorded)"


def _the_currency_of(
    priced: Sequence[tuple[EngagedResponder, PayBand]]
) -> str | None:
    """The currency the bands are quoted in, or `None` where none were read.

    The first band's, because they come from one source's one table and a
    source quoting two currencies in one table is a case nothing here has met.
    An empty response - nobody engaged - consulted no band, so there is nothing
    to name and nothing is named.
    """
    return priced[0][1].currency if priced else None
