"""What the incident cost the business, and the arithmetic behind it.

    shortfall = what the shop took over the incident's own hours whole weeks
                earlier - what actually came in
    loss      = the shortfall, where it is larger than the shop varies on its own

Every term is money the payment provider reported, over windows as long as the
incident (spec §21.3): the incident itself, the same hours whole weeks earlier,
and the same hours as far back again, whose difference from the second is how
much the shop varies over those hours anyway. A provider cannot say how many people were
affected - a guest checkout is attached to no customer at all - and does not
have to, because it can say what the shop took. The one thing it cannot report
is the sale that never happened, which is exactly the shortfall.

Every window here is bounded by the signal and never by the workflow. The
caller supplies both ends, and both are read off the metrics: an incident's
length is its onset to its recovery, not to the moment the walk closed it -
those differ by the whole of the verification wait, the code-fix attempt and
the write-up, and a window running to the close is mostly healthy minutes.

Nothing here is a judgement, and no term is a proxy for another: every figure
is money over a window, measured by the party that took it.

Every source is asked once and what it answered is kept, because the sentences
a document discloses are written from the same reads that produced the
figures. A disclosure that went back to the rate table for the rate it is about
could name a rate the figure was not converted at.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from incident_cost.sources import MoneySources, RateTable

_A_WEEK = timedelta(weeks=1)


@dataclass(frozen=True)
class LossEstimate:
    """What an incident cost the business, and every read it was worked out
    from.

    The reads travel with the figure because nothing downstream may go back to
    a source: a document is written after the incident, sources move, and a
    second read is a second answer.
    """

    loss: Decimal | None
    # What the loss is stated in, and `None` wherever there is no loss to
    # state. A currency beside an absent figure is a label for nothing.
    currency: str | None
    # What the shop took over the incident's own hours whole weeks earlier -
    # what the incident is compared with.
    baseline_revenue: Decimal | None
    # How far those hours and the same hours as far back again differ, in the
    # reporting currency: how much the shop varies on its own over them.
    # A shortfall no larger is no loss. `None` where either went unread.
    variation: Decimal | None
    # How far the incident's takings fell short of that stretch's, whether or
    # not it was beyond the variation - negative where the shop took more.
    # `None` where either went unread.
    shortfall: Decimal | None
    # What the incident's hours took whole weeks earlier, per currency, before
    # any of it was converted. The conversions are disclosed one line each, and
    # a line naming a currency needs the currencies rather than the total.
    baseline_takings: Mapping[str, Decimal] | None
    rates: RateTable | None
    currencies_left_out: list[str]


def estimate_loss(onset_at: datetime | None,
                  measured_until: datetime,
                  money: MoneySources) -> LossEstimate:
    """Read the takings and the rates once, and count what they said.

    Like with like: the incident from `onset_at` to `measured_until` against its
    own clock hours whole weeks earlier, so a shop's day and week cancel out -
    and those against the same hours as far back again, for how much the shop
    varies on its own.

    Nothing is read without an onset, since no loss is counted from the alert:
    the alert is late by however long its rule took to trip, so a figure dated
    from it would be both invented and short - and takings read for nothing
    were disclosed as converted at a rate no figure was converted at.
    """
    if onset_at is None:
        return LossEstimate(loss=None,
                            currency=None,
                            baseline_revenue=None,
                            variation=None,
                            shortfall=None,
                            baseline_takings=None,
                            rates=None,
                            currencies_left_out=[])

    rates = money.rates()
    back = weeks_back_for(measured_until - onset_at)
    taken_earlier = money.revenue(onset_at - 2 * back, measured_until - 2 * back)
    taken_before = money.revenue(onset_at - back, measured_until - back)
    taken_during = money.revenue(onset_at, measured_until)
    earlier_revenue, _ = _as_one_figure(
        taken_earlier, rates, money.reporting_currency)
    baseline_revenue, left_out = _as_one_figure(
        taken_before, rates, money.reporting_currency)
    revenue_during, _ = _as_one_figure(
        taken_during, rates, money.reporting_currency)
    variation = (abs(baseline_revenue - earlier_revenue)
                 if baseline_revenue is not None and earlier_revenue is not None else None)
    shortfall = (baseline_revenue - revenue_during
                 if baseline_revenue is not None and revenue_during is not None else None)
    loss = _loss(shortfall, variation)

    return LossEstimate(
        loss=loss,
        currency=money.reporting_currency if loss is not None else None,
        baseline_revenue=baseline_revenue,
        variation=variation,
        shortfall=shortfall,
        baseline_takings=taken_before,
        rates=rates,
        currencies_left_out=left_out
    )


def in_the_reporting_currency(taken: Mapping[str, Decimal],
                              rates: RateTable) -> tuple[Decimal, list[str]]:
    """One figure out of several, and whatever could not be converted.

    The rates say how many units of a currency one unit of the base buys, so
    money taken abroad is divided by its rate rather than multiplied - the
    direction that turns eighty euros into a hundred dollars rather than
    sixty-four.

    A currency the table has no rate for is returned as excluded rather than
    dropped silently or counted at par. Both of those publish a figure that
    looks measured and is not; naming it lets the document say what is missing
    from the total it reports.
    """
    total = Decimal(0)
    excluded: list[str] = []

    for currency, amount in taken.items():
        if currency == rates.base:
            total += amount
        elif currency in rates.per_unit:
            total += amount / rates.per_unit[currency]
        else:
            excluded.append(currency)

    return total, excluded


def weeks_back_for(span: timedelta) -> timedelta:
    """How far back the takings an incident of `span` is compared with lie.

    Whole weeks, so the comparison falls on the same hours of the same weekday
    and a shop's daily and weekly rhythm cancels out: an incident one morning
    against the night before it is a loss the morning rush invented. As few
    weeks as clear the incident, so the stretch compared never overlaps it.
    """
    return _A_WEEK * max(1, math.ceil(span / _A_WEEK))


def beyond_the_variation(shortfall: Decimal, variation: Decimal) -> Decimal:
    """The shortfall, where it is larger than the shop varies on its own, and
    nothing where it is not.

    `variation` is how far two calm stretches the incident's length apart
    differ from each other. A shortfall inside that is the shop being the shop,
    and reported as a loss it is noise given a currency. Zero rather than
    nothing: the takings were read, and showed no loss anyone can tell from
    an ordinary day. In full where it is larger - the variation decides whether
    anything was lost, and the shortfall says how much.

    Never negative. A shop that took more while it was broken lost nothing
    measurable - a busier afternoon, or a promotion that began with the outage -
    and a negative loss is not a smaller loss, it is a category error.

    Deliberately not rounded to a currency's smallest unit: presentation is
    the reader's, and the reader is a page.
    """
    return shortfall if shortfall > variation else Decimal(0)


def _as_one_figure(taken: Mapping[str, Decimal] | None,
                   rates: RateTable | None,
                   reporting_currency: str) -> tuple[Decimal | None, list[str]]:
    """What the service took, stated in the one currency the document reports
    in, and whatever could not be stated there at all.

    A quiet window took nothing, and nothing is a measurement: an empty mapping
    is zero rather than an unanswered question. Only an unread provider leaves
    no figure, because only it leaves no takings to state.

    A table nobody could read is a table with no rates in it, which the
    arithmetic already knows how to answer: whatever needed no conversion is in
    the figure, and every currency that did is named as missing from it. The
    currency this is reported in comes from the configuration either way - it is
    what the table was asked to quote against - so it is not a guess, and losing
    the money that needed no rate at all would be the worse answer.
    """
    if taken is None:
        return None, []

    if rates is None:
        return _only_the_money_needing_no_rate(taken, reporting_currency)

    return in_the_reporting_currency(taken, rates)


def _only_the_money_needing_no_rate(
        taken: Mapping[str, Decimal],
        reporting_currency: str) -> tuple[Decimal, list[str]]:
    """The takings already in the reporting currency, and every other currency.

    The same shape `in_the_reporting_currency` returns for a currency the table
    does not cover, because it is the same finding: money that was taken, and
    no rate to state it with.
    """
    return (
        taken.get(reporting_currency, Decimal(0)),
        [currency for currency in taken if currency != reporting_currency]
    )


def _loss(shortfall: Decimal | None, variation: Decimal | None) -> Decimal | None:
    """The estimate, or nothing when any window went unread.

    Nothing, never zero: an unreadable revenue source and a service that lost
    no money are different findings, and only one of them is a measurement.
    Every window is needed - a loss is the difference between two of them, and
    whether that difference is a loss at all is what the third says.
    """
    if shortfall is None or variation is None:
        return None

    return beyond_the_variation(shortfall, variation)
