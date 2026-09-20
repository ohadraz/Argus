"""What the incident cost the business, and the arithmetic behind it.

    loss = what the calm hour predicted - what actually came in

Both terms are money the payment provider reported, over two windows: the hour
before the onset, and the stretch the service was broken for (spec §21.3). A
provider cannot say how many people were affected - a guest checkout is
attached to no customer at all - and does not have to, because it can say what
the shop took. The one thing it cannot report is the sale that never happened,
which is exactly the difference between the two windows.

Every window here is bounded by the signal and never by the workflow. The
caller supplies both ends, and both are read off the metrics: an incident's
length is its onset to its recovery, not to the moment the walk closed it -
those differ by the whole of the verification wait, the code-fix attempt and
the write-up, and a window running to the close is mostly healthy minutes.

Nothing here is a judgement, and no term is a proxy for another: every figure
is money over a window, measured by the party that took it.

The error rate is measured too, but only to tell the model what happened. No
figure rests on it.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta
from decimal import Decimal

from argus_core import parse_iso
from argus_core.models import MetricBucket
from pydantic import BaseModel

from agent_postmortem.sources import RateTable

# How far before the incident to ask what the service normally takes. An hour
# is long enough that a quiet minute does not become the baseline, and short
# enough to still be the same day's trade.
BASELINE_WINDOW_HOURS = 1.0

# The same window as a span, for the callers that subtract it from an instant
# rather than divide by it. Derived rather than written twice, so the two can
# never say different things about how long "before" is.
BASELINE_WINDOW = timedelta(hours=BASELINE_WINDOW_HOURS)


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

    The baseline is every minute before `began`, which is the calm hour the
    caller read. The other two levels come from the broken stretch - their
    mean, and the worst of them.

    `None` when either side is missing, because a measurement against nothing
    is not a small one - it is an unanswered question.
    """
    before = [bucket.error_rate for bucket in buckets
              if parse_iso(bucket.bucket_id) < began]
    while_broken = [bucket.error_rate for bucket in buckets
                    if began <= parse_iso(bucket.bucket_id)
                    and (until is None or parse_iso(bucket.bucket_id) < until)]

    if not before or not while_broken:
        return None

    return ErrorRates(
        baseline=_mean(before),
        while_broken=_mean(while_broken),
        at_its_worst=max(while_broken)
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


def loss_between(taken_before: Decimal,
                 over_hours: float,
                 taken_during: Decimal,
                 for_hours: float) -> Decimal:
    """What the calm hour predicted, less what actually came in.

    Both terms are money the payment provider reported; the only arithmetic is
    scaling the first to the length of the second, because a baseline hour and
    a ten-minute incident are not comparable until they are.

    Never negative. A shop that took more while it was broken than its calm
    hour predicted lost nothing measurable - a busier afternoon, or a
    promotion that began with the outage - and a negative loss is not a
    smaller loss, it is a category error. Zero is the honest floor, and it is
    a measurement rather than an absence.

    Deliberately not rounded to a currency's smallest unit. Rounding would
    imply the figure is accurate to that unit, and a figure resting on a
    baseline hour standing in for the incident's own is not accurate to the
    cent. Presentation is the reader's, and the reader is a page.
    """
    predicted = taken_before / Decimal(str(over_hours)) * Decimal(str(for_hours))

    return max(predicted - taken_during, Decimal(0))


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)
