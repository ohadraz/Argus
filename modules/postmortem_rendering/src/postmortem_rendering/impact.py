"""How bad it was: one card per figure, the figure first, and what the alert
found where the damage is not a rate - the series its rule pages on among the
figures, where that got worse.

A figure that could not be measured is said not to have been, never shown as a
zero: a reader must not have to guess whether nothing was lost or nothing was
known.
"""

from __future__ import annotations

from typing import Final

from argus_core import level_said_in
from argus_core.models import (
    AlarmClaim,
    Alert,
    Impact,
    ImpactExtent,
    PostmortemDocument,
    said_as_money,
)
from pydantic import BaseModel, ConfigDict

from postmortem_rendering.formatting import as_span
from postmortem_rendering.lines import Line, Role, Run

# Said under a duration the metrics carry no minute of: what was missing is
# the metrics, not sight of the service - its logs and its takings may well
# cover the stretch, and the cause and the loss say what they saw.
_UNOBSERVED: Final = ("The metrics stop at the onset, so the duration is how long they had "
                      "been missing by the close - not a stretch the service is known to "
                      "have spent broken.")

# What a card's "this to that" compares, said once so the two cards that
# compare levels say it alike.
_BEFORE_AND_WHILE_BROKEN: Final = "before onset and while broken on average"


class Card(BaseModel):
    """One figure and what it is, the figure first.

    `note` is what supports the figure without being it - a worst minute, a
    rule's line - said quieter under the label, so the label stays a name for
    the figure rather than more figures. `None` where there is nothing to add.

    `loss_is` says whether a loss is measured or a lower bound, for a
    destination that marks which; `None` on every other card, and on a loss
    nobody estimated.
    """

    model_config = ConfigDict(frozen=True)

    value: str
    label: str
    note: str | None = None
    loss_is: str | None = None


class ImpactSection(BaseModel):
    """The cards, what the alert found, and what a duration the metrics carry
    nothing of measures - each of the last two `None` where there is nothing
    to say.

    `finding_label` is the label a citation of what the alert said goes by,
    where the finding is said here: this is then the one place the alert's
    words are, and a citation of them leads here."""

    model_config = ConfigDict(frozen=True)

    cards: tuple[Card, ...]
    finding: str | None
    unobserved: str | None
    finding_label: str | None = None
    # What the service's own logs show where the metrics stopped, beside the
    # note on what the duration measures; `None` where they never stopped.
    logs_in_the_gap: Line | None = None


def the_impact(postmortem: PostmortemDocument, alert: Alert) -> ImpactSection:
    """How long, how badly, how many and how much - and what the alert itself
    found, which is the one measurement there is where the damage is not a
    rate.

    Only from an alert reporting a finding of its own. A rule watching a series
    says what it pages on, not what it found, and under "found" its condition
    reads as a measurement of this incident: what it found is the series' own
    card, and its words are Detection's row of what the alert said.

    "At least" where the incident never ended: the figures were counted up to
    where the metrics stopped, with the incident still going there.
    """
    impact = postmortem.impact
    a_lower_bound = impact is not None and impact.extent is not ImpactExtent.MEASURED
    found = the_alert_s_own_finding(alert)
    said = postmortem.detection.said if postmortem.detection else None

    return ImpactSection(
        cards=(_the_duration(impact),
               *_the_errors(impact),
               *_the_rules_series(impact),
               _the_loss(postmortem, a_lower_bound)),
        finding=f"What the alert found: {found}" if found else None,
        unobserved=_UNOBSERVED if impact and impact.extent is ImpactExtent.UNOBSERVED else None,
        finding_label=said.label if found and said else None,
        logs_in_the_gap=_the_logs_in_the_gap(impact))


def the_alert_s_own_finding(alert: Alert) -> str | None:
    """What the alert found, where it reports a finding of its own - said
    under Impact, and so nowhere else - or `None` where it watched a series and
    said its condition, or said nothing."""
    return (alert.summary
            if alert.summary and alert.claim is AlarmClaim.ITS_OWN_FINDING else None)


def _the_duration(impact: Impact | None) -> Card:
    """How long, said by where it ends. Back to normal only where it got back:
    a failure still going when the metrics ran out, and metrics still missing
    when the incident closed, are each a floor - labelled as ending back
    to normal, they name an end the incident never had."""
    if impact is None:
        return Card(value="not measured", label=_UNTIL_BACK_TO_NORMAL)

    span = as_span(impact.duration)
    match impact.extent:
        case ImpactExtent.MEASURED:
            return Card(value=span, label=_UNTIL_BACK_TO_NORMAL)
        case ImpactExtent.AT_LEAST:
            return Card(value=f"at least {span}", label="since onset, still not back to normal")
        case ImpactExtent.UNOBSERVED:
            return Card(value=f"at least {span}", label="since onset, metrics missing")


_UNTIL_BACK_TO_NORMAL: Final = "onset until back to normal"


def _the_errors(impact: Impact | None) -> tuple[Card, ...]:
    """The failed requests at their worst and in all - or, where they did not
    rise, one card saying so.

    Failed requests that did not rise are no harm, and a count of them under
    Impact reads as one: the requests that failed at the rate they always do.
    Left off instead, the rate reads as one nobody measured. A document
    written before the levels were carried shows the two cards it always did.
    Said as the series' card says its levels: the one before, then the one
    while broken.
    """
    levels = impact.error_rates if impact else None

    if levels is not None and not levels.rose:
        return (Card(value=f"{levels.before:.1%} to {levels.while_broken:.1%}",
                     label=f"error rate, {_BEFORE_AND_WHILE_BROKEN}",
                     note="no rise"),)

    peak = impact.peak_error_rate if impact else None
    failed = impact.requests_failed if impact else None

    return (Card(value=f"{peak * 100:.1f}%" if peak is not None else "not measured by the metrics",
                 label="peak error rate"),
            Card(value=f"{failed:,}" if failed is not None else "not counted by the metrics",
                 label="requests failed"))


def _the_logs_in_the_gap(impact: Impact | None) -> Line | None:
    """What the service's own logs show of the stretch its metrics missed,
    said beside the cards that say what the metrics did not measure - which
    rows reach in and how far, said once, and where the reading of them
    ended, since where the lines stop is as often where the reading did.
    `None` where the metrics never stopped.

    Each row by its label, leading to it: the rows are where a reader checks
    what the logs said there. And said where they show nothing: a note silent
    on the logs reads the same as one whose logs nobody looked at.
    """
    logs = impact.logs_in_the_gap if impact else None

    if logs is None:
        return None

    if not logs.read:
        return Line(runs=(Run(text="No logs were read."),))

    reached: tuple[Run, ...] = (Run(text="No log line read reaches into the stretch the metrics "
                                         "missed."),)
    if logs.labels and logs.reach_until is not None:
        cited = [run for label in logs.labels
                 for run in (Run(text=", "), Run(text=label, role=Role.CITATION, address=label))]
        reached = (Run(text="The service's own logs reach into the stretch the metrics missed "
                            "until "),
                   Run.a_moment(logs.reach_until),
                   Run(text=": "),
                   *cited[1:],
                   Run(text="."))

    if logs.read_until is None:
        return Line(runs=reached)

    who_read = "They were" if logs.labels else "The logs were"
    when = ", when the alert was raised" if logs.read_until_the_alert else ""

    return Line(runs=(*reached,
                      Run(text=f" {who_read} read up to "),
                      Run.a_moment(logs.read_until),
                      Run(text=f"{when}.")))


def _the_rules_series(impact: Impact | None) -> tuple[Card, ...]:
    """The series the paging rule evaluates, where it got worse - none where it
    held, since nothing is not a harm.

    The figure is the level before and the level while broken, in that order:
    a level alone is no harm until it is set against the one before, and the
    order says which way it went, whichever way is worse. Said as what the
    alert watches, since only the rule knows what the series measures - the
    alert's name is the document's title, and in a card too narrow for it the
    PDF breaks it mid-word. In the unit the rule's panel or its metric's name
    says, and in plain numbers where neither says one; each written as the
    prose writes a level, so the card and the sentence beside it are one
    figure. On average while broken, as the error
    rate is, with the worst minute in the note: one minute alone overstates
    the stretch.

    And the line the rule pages past, in the same unit, where it was read: the
    alert's words may say "80%" of a series written as 0.459, and the line lets
    a reader bridge the two without the page guessing a unit.
    """
    harm = impact.rule_series_harm if impact else None

    if harm is None:
        return ()

    def said(level: float) -> str:
        return level_said_in(level, harm.unit)

    line = f"; the rule's line is {said(harm.line)}" if harm.line is not None else ""

    return (Card(value=f"{said(harm.before)} to {said(harm.while_broken)}",
                 label=f"what the alert watches, {_BEFORE_AND_WHILE_BROKEN}",
                 note=f"worst minute {said(harm.at_its_worst)}{line}"),)


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

    amount = said_as_money(loss, postmortem.estimate_currency)

    return Card(value=f"at least {amount}" if a_lower_bound else amount,
                label=label,
                loss_is=loss_is)
