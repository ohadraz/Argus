"""What the incident cost the business, and the arithmetic behind it.

Spec §21.3 states the estimate as `affected_users x avg_revenue_per_user x
duration x impact_weight`. Neither of the first two terms is obtainable: a
payment provider can say what was taken in a window and cannot say by how many
people, since a guest checkout is attached to no customer at all. So the same
quantity is reached from the side that *is* measurable:

    loss = revenue_per_hour x duration_hours x error_rate_delta x impact_weight

The substitution is exact where the original was guessing, and it drops an
assumption on the way: a revenue rate already reflects how many visitors buy,
where a user count multiplied by an average pretends every affected visitor
would have.

Three of the four terms are measured. The fourth is the model's, and the
document says so.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from argus_core.models.metrics import MetricBucket
from argus_core.timestamps import parse_iso

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


def revenue_per_hour(amount: Decimal, over_hours: float) -> float:
    """A rate, from an amount and the span it was taken over."""
    return float(amount) / over_hours


def loss_estimate(rate_per_hour: float,
                  duration_hours: float,
                  delta: float,
                  impact_weight: float) -> Decimal:
    """The four terms, multiplied in the order the spec states them.

    Deliberately not rounded to a currency's smallest unit. Rounding would
    imply the figure is accurate to that unit, and an estimate resting on a
    judgment about which paths carry revenue is not accurate to the cent.
    Presentation is the reader's, and the reader is a page.
    """
    return Decimal(rate_per_hour * duration_hours * delta * impact_weight)


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)
