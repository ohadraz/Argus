"""What the document admits to having assumed rather than measured.

Every figure in a postmortem is a measurement, but a measurement is only as
honest as the steps between the source and the page: a rate applied, a band a
title was priced at, a working year the bands were divided by. Each of those is
stated here in the reader's own terms, so a number can be argued with rather
than trusted.

An absence gets a line too. A figure that is missing and a figure that is zero
look the same on a page unless the document says which one it is, and each
absence has its own sentence - "nobody responded" and "the on-call system could
not be reached" are different findings that would otherwise leave the same
blank.

Nothing here reads a source. Everything was read while the incident was being
measured, so a disclosure describes the same read that produced the figure it
sits beside.
"""

from __future__ import annotations

from typing import Any

from agent_postmortem.document import (
    ENGAGEMENT_UNAVAILABLE_ASSUMPTION,
    EXCHANGE_RATE_ASSUMPTION_LABEL,
    EXCLUDED_CURRENCY_ASSUMPTION_LABEL,
    ONSET_UNKNOWN_ASSUMPTION,
    PAY_BAND_ASSUMPTION_LABEL,
    PAY_BANDS_UNAVAILABLE_ASSUMPTION,
    REVENUE_UNAVAILABLE_ASSUMPTION,
    UNPRICED_TITLE_ASSUMPTION_LABEL,
    WORKING_YEAR_ASSUMPTION_LABEL,
)
from agent_postmortem.measuring import Measurements
from agent_postmortem.prompting import ASSUMPTIONS_FIELD
from agent_postmortem.responder_cost import unpriced_titles
from agent_postmortem.sources import EngagementAnswer


def assumptions_of(answer: dict[str, Any],
                   measured: Measurements,
                   working_hours_a_year: float) -> list[str]:
    """Everything the document assumed, in the order a reader meets it.

    The conversions come first - they are the only step between the money the
    provider reported and the figure published - then the pricing, then
    whatever the model says it assumed in its prose, then the absences, each
    saying which question went unanswered.
    """
    assumptions: list[str] = []

    if measured.onset_at is None:
        assumptions.append(ONSET_UNKNOWN_ASSUMPTION)

    assumptions.extend(_rates_applied(measured))
    assumptions.extend(
        f"{EXCLUDED_CURRENCY_ASSUMPTION_LABEL}: takings in {currency} are not in "
        f"the figure, because no rate was published for it"
        for currency in measured.currencies_left_out
    )

    assumptions.extend(_the_pricing_behind(measured, working_hours_a_year))

    assumptions.extend(str(stated) for stated in answer.get(ASSUMPTIONS_FIELD, []))

    if measured.baseline_revenue is None:
        assumptions.append(REVENUE_UNAVAILABLE_ASSUMPTION)
    if measured.engaged is None:
        assumptions.append(ENGAGEMENT_UNAVAILABLE_ASSUMPTION)
    if measured.engaged is not None and measured.bands is None:
        assumptions.append(PAY_BANDS_UNAVAILABLE_ASSUMPTION)

    return assumptions


def _the_pricing_behind(measured: Measurements,
                        working_hours_a_year: float) -> list[str]:
    """How the response cost was arrived at, or why there is none.

    A published figure discloses both things that are not measurements: the
    working year the annual bands were divided by, and the band each title was
    priced at - a midpoint being a range collapsed to a point.

    A figure that could not be published names the titles that stopped it, so
    the gap reads as a band nobody configured rather than as a fault in Argus.
    A source that could not be read at all is a different sentence, said by the
    caller, since there are no titles to blame for it.
    """
    engaged, bands = measured.engaged, measured.bands
    if bands is None or engaged is None:
        return []

    if measured.cost is None:
        return [
            f"{UNPRICED_TITLE_ASSUMPTION_LABEL}: no responder cost, because no "
            f"pay band covers [{title}]"
            for title in unpriced_titles(engaged.engaged, bands)
        ]

    return [
        f"{WORKING_YEAR_ASSUMPTION_LABEL}: annual pay bands divided by "
        f"{working_hours_a_year:g} hours",
        *(f"{PAY_BAND_ASSUMPTION_LABEL}: {title} priced at the midpoint of "
          f"{bands[title].minimum} to {bands[title].maximum} "
          f"{bands[title].currency} a year"
          for title in _the_titles_priced(engaged))
    ]


def _the_titles_priced(engaged: EngagementAnswer) -> list[str]:
    """What the responders held, each named once, in the order they responded.

    Once, because two people holding one title are priced at one band and the
    document would otherwise recite it twice; in order, because a reader
    matching the lines against the timeline reads them the same way round.
    """
    return list(dict.fromkeys(
        responder.job_title
        for responder in engaged.engaged
        if responder.job_title is not None
    ))


def _rates_applied(measured: Measurements) -> list[str]:
    """Every conversion that went into the figure, one line each.

    Only the currencies actually taken, so a document about a service trading
    in dollars does not recite thirty rates it never used. A window needing no
    conversion says nothing, which is correct: there is no assumption to
    disclose.
    """
    taken, rates = measured.baseline_takings, measured.rates
    if taken is None or rates is None:
        return []

    return [
        f"{EXCHANGE_RATE_ASSUMPTION_LABEL}: {currency} converted at "
        f"{rates.per_unit[currency]} per {rates.base}, published "
        f"{rates.on.isoformat()}"
        for currency in taken
        if currency != rates.base and currency in rates.per_unit
    ]
