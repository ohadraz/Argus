"""How bad it was: one card per figure, the figure first, and what the alert
found where the damage is not a rate - the series its rule pages on among the
figures, where that got worse.

A figure that could not be measured is said not to have been, never shown as a
zero: a reader must not have to guess whether nothing was lost or nothing was
known.
"""

from __future__ import annotations

from typing import Final

from argus_core import said_as_a_level
from argus_core.models import Alert, Impact, ImpactExtent, PostmortemDocument
from pydantic import BaseModel, ConfigDict

from postmortem_rendering.formatting import as_money, as_span

_UNOBSERVED: Final = ("Unobserved after a point - the metrics stopped, so the duration is how "
                      "long nobody could see.")


class Card(BaseModel):
    """One figure and what it is, the figure first.

    `loss_is` says whether a loss is measured or a lower bound, for a
    destination that marks which; `None` on every other card, and on a loss
    nobody estimated.
    """

    model_config = ConfigDict(frozen=True)

    value: str
    label: str
    loss_is: str | None = None


class ImpactSection(BaseModel):
    """The cards, what the alert found, and what a duration nobody could see
    measures - each of the last two `None` where there is nothing to say."""

    model_config = ConfigDict(frozen=True)

    cards: tuple[Card, ...]
    finding: str | None
    unobserved: str | None


def the_impact(postmortem: PostmortemDocument, alert: Alert) -> ImpactSection:
    """How long, how badly, how many and how much - and what the alert itself
    found, which is the one measurement there is where the damage is not a
    rate.

    "At least" where the incident never ended: the figures were counted up to
    where the metrics stopped, with the incident still going there.
    """
    impact = postmortem.impact
    a_lower_bound = impact is not None and impact.extent is not ImpactExtent.MEASURED

    if impact is None:
        duration = "not measured"
    elif impact.extent is ImpactExtent.AT_LEAST:
        duration = f"at least {as_span(impact.duration)}"
    else:
        duration = as_span(impact.duration)

    return ImpactSection(
        cards=(Card(value=duration, label="onset to recovery"),
               *_the_errors(impact),
               *_the_rules_series(impact, alert),
               _the_loss(postmortem, a_lower_bound)),
        finding=f"What the alert found: {alert.summary}" if alert.summary else None,
        unobserved=_UNOBSERVED if impact and impact.extent is ImpactExtent.UNOBSERVED else None)


def _the_errors(impact: Impact | None) -> tuple[Card, ...]:
    """The failed requests at their worst and in all - or, where they did not
    rise, one card saying so.

    Failed requests that did not rise are no harm, and a count of them under
    Impact reads as one: the requests that failed at the rate they always do.
    Left off instead, the rate reads as one nobody measured. A document
    written before the levels were carried shows the two cards it always did.
    """
    levels = impact.error_rates if impact else None

    if levels is not None and not levels.rose:
        return (Card(value=f"{levels.while_broken:.1%}",
                     label=f"error rate while broken - {levels.before:.1%} before, no rise"),)

    peak = impact.peak_error_rate if impact else None
    failed = impact.requests_failed if impact else None

    return (Card(value=f"{peak * 100:.1f}%" if peak is not None else "not measured",
                 label="peak error rate"),
            Card(value=f"{failed:,}" if failed is not None else "not counted",
                 label="requests failed"))


def _the_rules_series(impact: Impact | None, alert: Alert) -> tuple[Card, ...]:
    """The series the paging rule evaluates, where it got worse - none where it
    held, since nothing is not a harm.

    Named by the alert, since only the rule knows what the series measures;
    in plain numbers, since only the rule knows its unit; and each written as
    the prose writes a level, so the card and the sentence beside it are one
    figure. On average while broken, as the error rate is, with the worst
    minute beside it: one minute alone overstates the stretch.
    """
    harm = impact.rule_series_harm if impact else None

    if harm is None:
        return ()

    moved = "fell" if harm.worse_when == "below" else "rose"

    return (Card(value=said_as_a_level(harm.while_broken),
                 label=f"what {alert.alert_name} watches while broken, on average - "
                       f"{moved} from {said_as_a_level(harm.before)}, "
                       f"worst minute {said_as_a_level(harm.at_its_worst)}"),)


def _the_loss(postmortem: PostmortemDocument, a_lower_bound: bool) -> Card:
    """What customers' failures cost, to the cent, in its currency.

    No loss is said as none rather than as an amount: "at least 0.00" is true
    and reads as a figure nobody filled in. "So far" keeps what the "at least"
    says of an incident still going when the takings were counted.
    """
    label = "customer loss (estimated)"
    loss = postmortem.customer_loss_estimate

    if loss is None:
        return Card(value="not estimated", label=label)

    loss_is = "a lower bound" if a_lower_bound else "measured"

    if loss == 0:
        return Card(value="none so far" if a_lower_bound else "none", label=label, loss_is=loss_is)

    amount = f"{as_money(loss)} {(postmortem.estimate_currency or '').upper()}".rstrip()

    return Card(value=f"at least {amount}" if a_lower_bound else amount,
                label=label,
                loss_is=loss_is)
