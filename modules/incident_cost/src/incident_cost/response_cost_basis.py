"""How the response cost was arrived at - kept beside the figure.

The postmortem shows no pay: its readers are the people it would price, and a
cost beside their minutes and titles is a rate of pay. The figure is priced for
the executive synopsis, and a figure is only as honest as the steps between the
source and it: the working year the annual bands were divided by, the band each
title was priced at, the title nothing could price. Those steps are said here,
one line each, for whoever is shown the figure.

The wording is here too, as a constant per line, for the reason the
postmortem's assumptions keep their own: whatever reads a line back has to
agree on how it was said.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from incident_cost.responder_cost import TitleShare
from incident_cost.sources import PayBand

# How the divisor behind the response cost announces itself. An annual band
# becomes a per-minute rate only by being divided by a working year, and that
# year is a convention somebody configured rather than anything measured - so a
# reader reproducing the figure needs it stated beside the figure.
WORKING_YEAR_ASSUMPTION_LABEL = "Working year"

# How each band the figure rests on announces itself, one line per title. The
# figure is a midpoint, which is a range collapsed to a point: saying so is what
# stops the point being read as a measurement. The band's own figures are not
# said.
PAY_BAND_ASSUMPTION_LABEL = "Pay band"

# How a title nothing could price announces itself. The cost is absent rather
# than short, and the absence is only honest while it can say which title
# caused it.
UNPRICED_TITLE_ASSUMPTION_LABEL = "Unpriced title"

PAY_BANDS_UNAVAILABLE_ASSUMPTION = (
    "No responder cost: the pay band source could not be read"
)


def response_cost_basis(shares: Sequence[TitleShare],
                        bands: Mapping[str, PayBand] | None,
                        working_hours_a_year: float) -> list[str]:
    """How the response cost was arrived at, or why there is none.

    `shares` are the response's titles, one each, in the order they responded;
    `bands` is `None` where they could not be read.

    A published figure says both things that are not measurements: the working
    year the annual bands were divided by, and the band each title was priced
    at. A figure that could not be published names what stopped it - a title no
    band covers, a responder with no title, or a source nobody could read - so
    the gap reads as what it is rather than as a fault in Argus. Nothing where
    nobody responded, since there is no response to price.
    """
    if not shares:
        return []

    if bands is None:
        return [PAY_BANDS_UNAVAILABLE_ASSUMPTION]

    unpriced = [share.title for share in shares
                if share.title is None or share.title not in bands]
    if unpriced:
        # A responder with no title is said as one: naming a placeholder in
        # brackets blames a band for a title nobody recorded.
        return [
            *(f"{UNPRICED_TITLE_ASSUMPTION_LABEL}: no responder cost, because no "
              f"pay band covers [{title}]"
              for title in unpriced if title is not None),
            *([f"{UNPRICED_TITLE_ASSUMPTION_LABEL}: no responder cost, because no title "
               f"was recorded for a responder, so no pay band could price them"]
              if None in unpriced else [])
        ]

    return [
        f"{WORKING_YEAR_ASSUMPTION_LABEL}: annual pay bands divided by "
        f"{working_hours_a_year:g} hours",
        *(f"{PAY_BAND_ASSUMPTION_LABEL}: {share.title} priced at the midpoint of "
          f"the title's band"
          for share in shares)
    ]
