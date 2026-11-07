"""How the response cost was arrived at - kept beside the figure, never shown.

The postmortem shows no pay: its readers are the people it would price, and a
cost beside their minutes and titles is a rate of pay. The figure is still
computed and stored, for the executive report, and a figure is only as honest
as the steps between the source and it: the working year the annual bands were
divided by, the band each title was priced at, the title nothing could price.
Those steps are said here, one line each, for whoever is shown the figure - and
nowhere in the postmortem's own assumptions.

The wording is here too, as a constant per line, for the reason `assumptions`
keeps its own: whatever reads a line back has to agree on how it was said.
"""

from __future__ import annotations

from agent_postmortem.measuring import Measurements
from agent_postmortem.responder_cost import unpriced_titles
from agent_postmortem.sources import EngagementAnswer

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


def response_cost_basis(measured: Measurements, working_hours_a_year: float) -> list[str]:
    """How the response cost was arrived at, or why there is none.

    A published figure says both things that are not measurements: the working
    year the annual bands were divided by, and the band each title was priced
    at. A figure that could not be published names what stopped it - a title no
    band covers, a responder with no title, or a source nobody could read - so
    the gap reads as what it is rather than as a fault in Argus. Nothing where
    nobody was engaged, since there is no response to price.
    """
    engaged, bands = measured.engaged, measured.bands
    if not isinstance(engaged, EngagementAnswer):
        return []

    if bands is None:
        return [PAY_BANDS_UNAVAILABLE_ASSUMPTION]

    if measured.cost is None:
        # A responder with no title is said as one: naming a placeholder in
        # brackets blames a band for a title nobody recorded.
        held = {responder.job_title for responder in engaged.engaged}

        return [
            *(f"{UNPRICED_TITLE_ASSUMPTION_LABEL}: no responder cost, because no "
              f"pay band covers [{title}]"
              for title in unpriced_titles(engaged.engaged, bands) if title in held),
            *([f"{UNPRICED_TITLE_ASSUMPTION_LABEL}: no responder cost, because no title "
               f"was recorded for a responder, so no pay band could price them"]
              if None in held else [])
        ]

    return [
        f"{WORKING_YEAR_ASSUMPTION_LABEL}: annual pay bands divided by "
        f"{working_hours_a_year:g} hours",
        *(f"{PAY_BAND_ASSUMPTION_LABEL}: {title} priced at the midpoint of "
          f"the title's band"
          for title in _the_titles_priced(engaged))
    ]


def _the_titles_priced(engaged: EngagementAnswer) -> list[str]:
    """What the responders held, each named once, in the order they responded.

    Once, because two people holding one title are priced at one band and the
    basis would otherwise recite it twice; in order, because a reader matching
    the lines against the timeline reads them the same way round.
    """
    return list(dict.fromkeys(
        responder.job_title
        for responder in engaged.engaged
        if responder.job_title is not None
    ))
