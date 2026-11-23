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

from core.models import Alert, ImpactExtent, PostmortemDocument, PricedResponse, SynopsisFigure
from narration import said_as_a_span, said_as_money

from postmortem_rendering.impact import the_impact

# The stretches whose duration tile says "at least" where nothing ended them:
# still going, or with metrics missing, when the incident closed.
_FLOORS: Final = frozenset({ImpactExtent.AT_LEAST, ImpactExtent.METRICS_MISSING})

# What the responders' minutes count, as the postmortem measures them: each
# acknowledgement to the end of the on-call incident it acknowledged.
_WHAT_THE_MINUTES_COUNT: Final = "from each responder taking the page until the page was closed"


def the_synopsis_figures(postmortem: PostmortemDocument,
                         alert: Alert,
                         cost: PricedResponse) -> dict[str, str]:
    """How long it lasted, how badly requests failed and what customers lost -
    none of them of a disproven alarm, which had no stretch to measure - and,
    where anybody responded, how many people, for how long, and at what cost:
    `cost`, the response as the synopsis priced it, named only where every
    title in it was priced."""
    figures: dict[str, str] = {}

    impact = postmortem.impact
    if impact is None or impact.extent is not ImpactExtent.DISPROVEN:
        section = the_impact(postmortem, alert)
        if impact is not None:
            figures[SynopsisFigure.DURATION] = section.duration_card.value
            # The page shows no peak where no rise was measured, and one card
            # says so instead - nor one nobody read.
            if impact.peak_error_rate is not None and section.peak_card is not None:
                figures[SynopsisFigure.PEAK_ERROR_RATE] = section.peak_card.value
        if postmortem.customer_loss_estimate is not None and section.loss_card is not None:
            figures[SynopsisFigure.CUSTOMER_LOSS] = section.loss_card.value

    # Nobody responding is no response to name: "0" and "none" became "0
    # people responded, and their time came to none", false where a person
    # ended it unpaged. The ask says why nobody responded instead - nobody
    # paged, or a page nobody acknowledged.
    if not postmortem.responders:
        return figures

    figures[SynopsisFigure.RESPONDERS] = str(postmortem.responders)
    if postmortem.engineer_minutes is not None:
        minutes = postmortem.engineer_minutes
        figures[SynopsisFigure.ENGINEER_MINUTES] = f"{minutes} min" if minutes else "none"
    if cost.responder_cost_estimate is not None:
        figures[SynopsisFigure.RESPONDER_COST] = said_as_money(cost.responder_cost_estimate,
                                                               cost.responder_cost_currency)

    return figures


def the_synopsis_figures_said(postmortem: PostmortemDocument,
                              alert: Alert,
                              cost: PricedResponse) -> dict[str, str]:
    """The same figures by the same names, as prose says them: the duration in
    words, a floor still a floor, and the minutes with what they count. The
    rest read in prose as on their tiles."""
    said = the_synopsis_figures(postmortem, alert, cost)

    # Two floors, as the tiles have: the duration's where the stretch was cut
    # short with nothing ending it, the loss's wherever nothing ended it - which
    # includes metrics that resumed without showing the service back, a stretch
    # measured whole whose takings were still counting.
    impact = postmortem.impact
    ended = postmortem.the_impact_ended()
    the_duration_a_floor = impact is not None and impact.extent in _FLOORS and not ended
    the_loss_a_floor = impact is not None and not ended
    if SynopsisFigure.DURATION in said and impact is not None:
        span = said_as_a_span(impact.duration)
        said[SynopsisFigure.DURATION] = f"at least {span}" if the_duration_a_floor else span

    # No loss is the amount in prose: the tile's "none so far" in an amount's
    # slot read "the cost to the shop's takings at none so far".
    if SynopsisFigure.CUSTOMER_LOSS in said and postmortem.customer_loss_estimate == 0:
        amount = said_as_money(Decimal(0), postmortem.estimate_currency)
        said[SynopsisFigure.CUSTOMER_LOSS] = f"{amount} so far" if the_loss_a_floor else amount

    minutes = postmortem.engineer_minutes
    if minutes and SynopsisFigure.ENGINEER_MINUTES in said:
        said[SynopsisFigure.ENGINEER_MINUTES] = (f"{minutes} minute{'s' if minutes != 1 else ''} "
                                                 f"({_WHAT_THE_MINUTES_COUNT})")

    return said
