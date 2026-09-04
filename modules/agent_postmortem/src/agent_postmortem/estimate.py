"""What the incident cost the business, and the arithmetic behind it.

    loss = what the calm hour predicted - what actually came in

Both terms are money the payment provider reported, over two windows: the hour
before the onset, and the incident itself (spec §21.3). A provider cannot say
how many people were affected - a guest checkout is attached to no customer at
all - and does not have to, because it can say what the shop took. The one
thing it cannot report is the sale that never happened, which is exactly the
difference between the two windows.

Nothing here is a judgement, and no term is a proxy for another: every figure
is money over a window, measured by the party that took it.

The error rate is measured too, but only to tell the model what happened. No
figure rests on it.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal

from argus_core.models.metrics import MetricBucket
from argus_core.timestamps import parse_iso

from agent_postmortem.sources import RateTable

# How far before the incident to ask what the service normally takes. An hour
# is long enough that a quiet minute does not become the baseline, and short
# enough to still be the same day's trade.
BASELINE_WINDOW_HOURS = 1.0


def duration_in_hours(started_at: datetime, ended_at: datetime) -> float:
    return (ended_at - started_at).total_seconds() / 3600


def error_rate_delta(buckets: list[MetricBucket],
                     started_at: datetime,
                     ended_at: datetime) -> float | None:
    """How much of the traffic failed that would not have failed anyway.

    The rise above the service's own calm rate, not the raw rate: a service
    that always errors on two requests in a hundred did not start doing so
    because of this incident, and charging those to it overstates every
    estimate by the same amount.

    `None` when either side is missing, because a delta against nothing is not
    a small delta - it is an unanswered question.
    """
    before = [bucket.error_rate for bucket in buckets
              if parse_iso(bucket.bucket_id) < started_at]
    during = [bucket.error_rate for bucket in buckets
              if started_at <= parse_iso(bucket.bucket_id) <= ended_at]

    if not before or not during:
        return None

    return _mean(during) - _mean(before)


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
