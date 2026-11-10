"""The figures the executive synopsis's overview may name, by name, each
written as the postmortem page writes it - and each said as prose says it.

Read off the page's own impact cards rather than worked out again, so the synopsis
and the page it links to cannot state one figure two ways. Only figures the
record holds are named: a figure nobody measured has no name, so the overview
can neither be asked for it nor write one in.

The model is asked with the tiles' wording, and its overview has each figure
written in as a person would say it: "for 7m 12s" reads as a machine wrote it,
and seventeen minutes of responders' time beside a seven-minute outage reads as
a mistake unless it says what it counts.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Final

from argus_core import said_as_a_span
from argus_core.models import Alert, ImpactExtent, PostmortemDocument, said_as_money

from postmortem_rendering.impact import the_impact

# The stretches whose tile says "at least": still going, or with metrics
# missing, when the incident closed.
_FLOORS: Final = frozenset({ImpactExtent.AT_LEAST, ImpactExtent.METRICS_MISSING})

# What the responders' minutes count, as the postmortem measures them: each
# acknowledgement to the end of the on-call incident it acknowledged.
_WHAT_THE_MINUTES_COUNT: Final = "from each responder taking the page until the page was closed"


def the_synopsis_figures(postmortem: PostmortemDocument, alert: Alert) -> dict[str, str]:
    """How long it lasted, how badly requests failed and what customers lost -
    none of them of a disproven alarm, which had no stretch to measure - and,
    where anybody was paged, how many people responded, for how long, and at
    what cost."""
    figures: dict[str, str] = {}

    impact = postmortem.impact
    if impact is None or impact.extent is not ImpactExtent.DISPROVEN:
        cards = the_impact(postmortem, alert).cards
        if impact is not None:
            figures["duration"] = cards[0].value
            # The peak's card follows the duration's, except where the rate did
            # not rise and one card says so instead.
            rose = impact.error_rates.rose if impact.error_rates is not None else None
            if impact.peak_error_rate is not None and rose is not False:
                figures["peak_error_rate"] = cards[1].value
        if postmortem.customer_loss_estimate is not None:
            figures["customer_loss"] = cards[-1].value

    # Nobody responding is no response to name: "0" and "none" became "0
    # people responded, and their time came to none", false where a person
    # ended it unpaged. The ask says why nobody responded instead - nobody
    # paged, or a page nobody acknowledged.
    if not postmortem.responders:
        return figures

    figures["responders"] = str(postmortem.responders)
    if postmortem.engineer_minutes is not None:
        minutes = postmortem.engineer_minutes
        figures["engineer_minutes"] = f"{minutes} min" if minutes else "none"
    if postmortem.responder_cost_estimate is not None:
        figures["responder_cost"] = said_as_money(postmortem.responder_cost_estimate,
                                                  postmortem.responder_cost_currency)

    return figures


def the_synopsis_figures_said(postmortem: PostmortemDocument, alert: Alert) -> dict[str, str]:
    """The same figures by the same names, as prose says them: the duration in
    words, a floor still a floor, and the minutes with what they count. The
    rest read in prose as on their tiles."""
    said = the_synopsis_figures(postmortem, alert)

    impact = postmortem.impact
    a_floor = impact is not None and impact.extent in _FLOORS
    if "duration" in said and impact is not None:
        span = said_as_a_span(impact.duration)
        said["duration"] = f"at least {span}" if a_floor else span

    # No loss is the amount in prose: the tile's "none so far" in an amount's
    # slot read "the cost to the shop's takings at none so far".
    if "customer_loss" in said and postmortem.customer_loss_estimate == 0:
        amount = said_as_money(Decimal(0), postmortem.estimate_currency)
        said["customer_loss"] = f"{amount} so far" if a_floor else amount

    minutes = postmortem.engineer_minutes
    if minutes and "engineer_minutes" in said:
        said["engineer_minutes"] = (f"{minutes} minute{'s' if minutes != 1 else ''} "
                                    f"({_WHAT_THE_MINUTES_COUNT})")

    return said
