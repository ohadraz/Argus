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

The error rate is measured too, but only to tell the model what happened. No
figure rests on it. So is the paging rule's own series, where the window carries
one, for the same reason and with the same three levels.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from statistics import quantiles
from typing import Final, NamedTuple

from argus_core import parse_iso
from argus_core.models import MetricBucket, WorseWhen
from pydantic import BaseModel

from agent_postmortem.sources import RateTable

# The hour before the incident the calm level of the error rate and the rule's
# series is measured over - how far back the metrics are read is
# `calm_to_read_for`'s, and is never less than this. An hour is long enough
# that a quiet minute does not become the baseline, and short enough to still be
# the same day's traffic. Not the revenue's: takings are compared over stretches
# as long as the incident, because an hour scaled to a week turns an ordinary
# hour's variation into six figures.
BASELINE_WINDOW = timedelta(hours=1)

_A_WEEK = timedelta(weeks=1)
_A_MINUTE = timedelta(minutes=1)

# The furthest back the calm is read for how far the rate varies on its own.
_LONGEST_CALM: Final = _A_WEEK


def calm_to_read_for(span: timedelta) -> timedelta:
    """How far before an incident the metrics are read, for one that can be no
    longer than `span`: far enough for twenty stretches as long as it to share
    no minute, so how high the rate goes on its own can be read off them.

    Counted in the minutes a stretch that long can touch - its whole minutes
    and one more, since a read answers for both its ends and a stretch never
    seen to end runs to the read's. Never less than the hour the baseline is
    measured over, and never more than a week: incidents of most of a working
    day, inside the fortnight a metrics store keeps by default. Past it the
    calm is too short, and the variation says so.
    """
    stretch = timedelta(minutes=span // _A_MINUTE + 1)

    return min(_LONGEST_CALM, max(BASELINE_WINDOW, _FEWEST_STRETCHES * stretch))


def duration_in_hours(from_when: datetime, until: datetime) -> float:
    """How long two instants are apart, on whichever clock they came from.

    Named for neither clock, because it serves both: the stretch the service
    was broken for, and the time Argus held the incident. Parameters called
    `started_at` and `ended_at` were the administrative reading of the
    question smuggled into the one function that answers it for the other.
    """
    return (until - from_when).total_seconds() / 3600


class ErrorRates(BaseModel):
    """What the service's error rate was, at the three levels worth reporting.

    Three numbers rather than one, because two different questions were being
    asked of the same figure and only one of them could be answered. `rise` is
    attribution - how much of the traffic failed that would not have failed
    anyway - and the levels are severity: a service that idles at 30% and one
    that idles at nothing can rise by the same amount and be in very different
    trouble. Handed a single number labelled as the error rate, a model
    reached past it for the per-minute figures, which was the right instinct
    about a page that could not tell it what it needed.

    `rise` is derived rather than stored, so that the levels and the
    difference between them cannot come to disagree.
    """

    baseline: float
    while_broken: float
    at_its_worst: float
    # How high the rate goes on its own over a stretch as long as the broken
    # one: the 95th percentile, across every such stretch in the calm before
    # it began, of its average and of its worst minute. A service that idles
    # between one and two percent rises above its baseline in half its quiet
    # hours, and a write-up told every such stretch was a rise blames the
    # incident for noise. `None` where the calm holds too few stretches for a
    # 95th percentile to be one.
    usual_ceiling: float | None
    usual_worst: float | None
    # How many requests failed over the broken stretch - each broken minute's
    # requests at that minute's rate. What a reader asks after how long and how
    # bad. `None` where it was not counted.
    failed_requests: int | None = None

    @property
    def rose_beyond_its_variation(self) -> bool | None:
        """Whether the broken stretch's average went higher than stretches as
        long go on their own - `None` where nobody can say how high that is."""
        return None if self.usual_ceiling is None else self.while_broken > self.usual_ceiling

    @property
    def peaked_beyond_its_variation(self) -> bool | None:
        """Whether the broken stretch's worst minute went higher than the worst
        minutes of stretches as long go on their own - `None` where nobody can
        say how high that is."""
        return None if self.usual_worst is None else self.at_its_worst > self.usual_worst

    @property
    def a_rise_was_measured(self) -> bool:
        """Whether failed requests rose above the calm before, and beyond what
        the rate reaches on its own - not where nobody can say how far that is.

        One answer for every reader of it: the brief and the impact cards each
        say "no rise" from this, and two tests of it are two chances to
        disagree."""
        return self.rise > 0 and self.rose_beyond_its_variation is True

    @property
    def rise(self) -> float:
        """How much of the traffic failed that would not have failed anyway.

        Not clamped at zero, and deliberately. While the window ran to the
        moment the walk closed the incident a negative rise meant nothing but
        healthy minutes being averaged in, and suppressing it would have hidden
        that. Bounded by the signal instead, a negative says the calm stretch
        was worse than the broken one - which is a defect report about the
        baseline or the onset, and is worth seeing.
        """
        return self.while_broken - self.baseline


def error_rates_over(buckets: list[MetricBucket],
                     began: datetime,
                     until: datetime | None) -> ErrorRates | None:
    """What the error rate did over the stretch the service was broken.

    `began` and `until` are the onset and the recovery, both read off the
    metrics. Neither is an administrative moment: the walk stays open through
    the verification wait, the code-fix attempt and the write-up, so a window
    ending when the incident was closed is mostly healthy minutes, and the
    mean across them describes a service that was mostly fine.

    `until` is the first minute that is no longer the incident, and is
    excluded - a recovery minute is by definition a minute the service was
    well in, and counting it would put one healthy minute inside the broken
    stretch and leave the mean describing a span the duration does not. It is
    `None` where the metrics ran out with the service still broken, which
    means every minute read counts: there is no first well minute to stop at.

    The baseline is the hour before `began` (`BASELINE_WINDOW`), however far
    back the caller read: hours earlier is another part of the day. Every calm
    minute read is what says how high the rate goes on its own over a stretch
    as long as the broken one - the caller reads `calm_to_read_for` the
    incident's span for that. The other two levels come from the broken
    stretch - their mean, and the worst of them.

    `None` when either side is missing, because a measurement against nothing
    is not a small one - it is an unanswered question. Which side, and why, is
    `why_no_error_rates`.
    """
    sides = _either_side_of(buckets, began, until)
    while_broken = [bucket.error_rate for bucket in sides.broken]

    if not sides.the_hour or not while_broken:
        return None

    calm = [bucket.error_rate for bucket in sides.calm]
    stretches = [calm[start:start + len(while_broken)]
                 for start in range(len(calm) - len(while_broken) + 1)]
    # Counted apart, though read overlapping: stretches sharing minutes are
    # mostly the same minutes, and say no more of how the rate varies than
    # the ones that share none.
    enough = len(calm) // len(while_broken) >= _FEWEST_STRETCHES

    return ErrorRates(
        baseline=_mean([bucket.error_rate for bucket in sides.the_hour]),
        while_broken=_mean(while_broken),
        at_its_worst=max(while_broken),
        usual_ceiling=(_the_95th_percentile([_mean(stretch) for stretch in stretches])
                       if enough else None),
        usual_worst=(_the_95th_percentile([max(stretch) for stretch in stretches])
                     if enough else None),
        failed_requests=round(sum(bucket.request_volume * bucket.error_rate
                                  for bucket in sides.broken))
    )


# How many stretches that share no minute a 95th percentile needs: it is the
# value one stretch in twenty passes, and fewer than twenty have no such value.
_FEWEST_STRETCHES: Final = 20


def _the_95th_percentile(values: list[float]) -> float:
    """The value one in twenty of `values` passes, interpolated between the
    two it falls between."""
    return quantiles(values, n=20, method="inclusive")[-1]


class Unmeasured(StrEnum):
    """Why the error rates could not be measured.

    Three gaps that read alike as an absent figure and are not alike: a read
    that came back empty is an outage of the metrics, while a read holding no
    minute of the hour before a week-old onset is the metrics doing their job
    over a shorter memory than the fault's.
    """

    NOTHING_READ = "nothing-read"
    NO_MINUTE_IN_THE_HOUR_BEFORE_THE_ONSET = "no-minute-in-the-hour-before-the-onset"
    NO_MINUTE_WHILE_BROKEN = "no-minute-while-broken"


def why_no_error_rates(buckets: list[MetricBucket],
                       began: datetime,
                       until: datetime | None) -> Unmeasured | None:
    """Why `error_rates_over` measured nothing, over the same stretch and by
    the same rules - or `None` where it measured something."""
    if not buckets:
        return Unmeasured.NOTHING_READ

    sides = _either_side_of(buckets, began, until)

    if not sides.the_hour:
        return Unmeasured.NO_MINUTE_IN_THE_HOUR_BEFORE_THE_ONSET

    if not sides.broken:
        return Unmeasured.NO_MINUTE_WHILE_BROKEN

    return None


class _Sides(NamedTuple):
    """A read cut where the incident began and ended: the hour before it, every
    calm minute read before it, and the broken minutes up to `until`."""

    the_hour: list[MetricBucket]
    calm: list[MetricBucket]
    broken: list[MetricBucket]


def _either_side_of(buckets: list[MetricBucket],
                    began: datetime,
                    until: datetime | None) -> _Sides:
    """Every minute read, on its side of `began` and `until`."""
    calm = [bucket for bucket in buckets if parse_iso(bucket.bucket_id) < began]

    return _Sides(
        the_hour=[bucket for bucket in calm
                  if parse_iso(bucket.bucket_id) >= began - BASELINE_WINDOW],
        calm=calm,
        broken=[bucket for bucket in buckets
                if began <= parse_iso(bucket.bucket_id)
                and (until is None or parse_iso(bucket.bucket_id) < until)]
    )


class RuleSeriesLevels(BaseModel):
    """What the series the paging rule evaluates did, at the error rate's three
    levels, and which way its rule calls worse.

    The series a fault in what the service answers moves alone: every request
    succeeded, so the error rate says nothing happened, and this is what says
    what did. The direction travels with the levels because "at its worst" means
    the lowest of a share of confident answers and the highest of a latency, and
    a reader handed the number without it cannot tell which it was.

    No rise, unlike the error rate's. That one is attribution in a unit everyone
    shares - a share of traffic - and a difference between two levels of a
    series in whatever unit its rule watches is not.
    """

    baseline: float
    while_broken: float
    at_its_worst: float
    worse_when: WorseWhen
    # The threshold the rule pages past, in the series' own unit - what lets a
    # reader bridge the levels to the alert's words, which may say "80%" of a
    # series read as 0.8, without anything here guessing a unit. `None` where
    # the rule's threshold could not be read.
    line: float | None = None

    @property
    def got_worse(self) -> bool:
        """Whether the series sat on its rule's worse side of where it was before,
        on average while the service was broken.

        No band of usual variation, as the error rate has: the rule fired on this
        series, so it crossed a line its owner drew, and the levels carry no
        spread to draw one from."""
        if self.worse_when == "below":
            return self.while_broken < self.baseline

        return self.while_broken > self.baseline


def rule_series_over(buckets: list[MetricBucket],
                     began: datetime,
                     until: datetime | None) -> RuleSeriesLevels | None:
    """What the paging rule's series did over the stretch the service was broken.

    The same stretch and the same rules as `error_rates_over` - the hour before
    `began` for the baseline, `began` up to `until` for the other two - because
    a series measured over a different span would be a second incident on the
    same page. Only the minutes carrying a reading count, since a minute
    without one has no level of the series in it.

    `None` where no minute carries a reading - a window read for no rule, or for
    one whose series could not be followed - and where either side is empty,
    because a level against nothing is an unanswered question rather than a
    small answer.
    """
    sides = _either_side_of(buckets, began, until)
    before = [bucket.rule_reading for bucket in sides.the_hour
              if bucket.rule_reading is not None]
    while_broken = [bucket.rule_reading for bucket in sides.broken
                    if bucket.rule_reading is not None]

    if not before or not while_broken:
        return None

    worse_when = while_broken[0].worse_when
    values = [reading.value for reading in while_broken]
    line = next((reading.line for reading in while_broken if reading.line is not None), None)

    return RuleSeriesLevels(
        baseline=_mean([reading.value for reading in before]),
        while_broken=_mean(values),
        at_its_worst=min(values) if worse_when == "below" else max(values),
        worse_when=worse_when,
        line=line.at if line is not None else None
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


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)
