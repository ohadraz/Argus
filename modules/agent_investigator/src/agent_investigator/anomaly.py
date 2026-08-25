from __future__ import annotations

from collections.abc import Iterator, Sequence
from statistics import median

from argus_core.config import get_settings
from argus_core.models.metrics import MetricBucket

# The smallest wobble a baseline is credited with, as a fraction of the
# baseline itself. A window of identical minutes has zero measured spread, so
# without this floor every minute after it would sit infinitely many
# deviations away and the first rounding artefact would read as an incident.
# Relative rather than absolute for the same reason the whole rule is
# relative: 10% of a 0.5% error rate and 10% of an 8% one are both "quiet".
_MINIMUM_SPREAD_AS_FRACTION_OF_BASELINE = 0.1


def find_onset(buckets: Sequence[MetricBucket]) -> str | None:
    """The `bucket_id` of the minute the incident started, or `None` when no
    minute in the window departs from the rest (spec §16).

    The window's own calm stretch is the baseline, so a service that idles at
    0.5% errors and one that idles at 8% are both judged against themselves.
    Returns a `bucket_id` because that is the wire-format minute a
    `get_log_lines` window is anchored on - no separate onset scheme to keep
    in sync.
    """
    for bucket in _anomalous_buckets(buckets):
        return bucket.bucket_id

    return None


def earliest_bucket_is_anomalous(buckets: Sequence[MetricBucket]) -> bool:
    """Whether the window opens already inside the incident - the structural
    trigger for widening the next iteration (spec §9).

    True means no calm stretch is visible: the baseline is off the left edge,
    so the onset predates everything retrieved and the next iteration has to
    reach further back. An empty window has no earliest bucket and so cannot
    show one.
    """
    if not buckets:
        return False

    return find_onset(buckets) == buckets[0].bucket_id


def _anomalous_buckets(buckets: Sequence[MetricBucket]) -> Iterator[MetricBucket]:
    """Yields, in window order, every minute whose error rate or p95 latency
    has left the baseline. Both are checked because different failures move
    different metrics - a bad flag spikes errors, a slow dependency does not.
    """
    if not buckets:
        return

    error_rate_ceiling = _departure_threshold([bucket.error_rate for bucket in buckets])
    latency_ceiling = _departure_threshold([float(bucket.p95_ms) for bucket in buckets])

    for bucket in buckets:
        if bucket.error_rate > error_rate_ceiling or bucket.p95_ms > latency_ceiling:
            yield bucket


def _departure_threshold(values: Sequence[float]) -> float:
    """The value a minute has to exceed to count as the incident, derived
    from the window's own quiet half.

    The baseline is taken from the lower half of the window rather than from
    all of it: the incident's own minutes are in there too, and they are
    exactly the ones that would drag a whole-window average up and hide the
    onset. Medians rather than means for the same reason - one 30% minute
    moves a mean, and moves a median not at all.
    """
    deviations = get_settings().anomaly_deviations_from_baseline

    quiet_half = sorted(values)[: max(1, len(values) // 2)]
    baseline = median(quiet_half)
    wobble = median([abs(value - baseline) for value in quiet_half])
    spread = max(wobble, baseline * _MINIMUM_SPREAD_AS_FRACTION_OF_BASELINE)

    return baseline + deviations * spread
