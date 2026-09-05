from __future__ import annotations

from collections.abc import Sequence
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

# Where in the quiet stretch the baseline's spread is read off. High enough to
# reach the calm window's own worst minutes, which is what the spread has to
# cover - the alternative, an average deviation, is dragged to zero by a
# metric that only takes a few distinct values. A sampled error rate is
# exactly that: 200 requests a minute quantises it into half-percent steps, so
# most quiet minutes report the identical figure and the average deviation
# between them is zero however much the rate actually moves.
_QUIET_SPREAD_QUANTILE = 0.9


def find_onset(buckets: Sequence[MetricBucket]) -> str | None:
    """The `bucket_id` of the minute the incident started, or `None` when no
    minute in the window departs from the rest (spec §16).

    The window's own calm stretch is the baseline, so a service that idles at
    0.5% errors and one that idles at 8% are both judged against themselves.
    Returns a `bucket_id` because that is the wire-format minute a
    `get_log_lines` window is anchored on - no separate onset scheme to keep
    in sync.

    A single departed minute is not an onset. An incident is a state the
    service stays in - it is still broken the minute after it broke - where a
    measurement that departs alone has, by the next minute, already recovered.
    Anchoring on one of those points the whole investigation at a minute
    nothing happened in, and every widening reaches further away from the
    incident rather than towards it. So the onset is the first minute of a run
    that lasts (`anomaly_persistence_minutes`), and a run still going when the
    window ends counts however short it is - an incident that began a minute
    ago has not failed to persist, it has yet to be given the chance.

    The *latest* such run rather than the first, for the same reason the onset
    is a run at all. The window is hours wide, and a service that departs
    briefly and comes back has had an incident that is over: dating the current
    one from it would put the onset before minutes the service was measurably
    healthy in, and every window derived from that onset - the logs read, the
    changes considered, the money counted - would cover mostly calm time. The
    state the service is in now began the last time it entered it.
    """
    departures = _departures(buckets)
    required = get_settings().anomaly_persistence_minutes

    for index in reversed(range(len(departures))):
        if not departures[index] or (index > 0 and departures[index - 1]):
            continue

        length = _run_length_from(departures, index)

        if length >= required or index + length == len(departures):
            return buckets[index].bucket_id

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


def has_recovered_since(buckets: Sequence[MetricBucket], moment: str) -> bool:
    """Whether every minute from `moment` onwards sits at the window's baseline
    (spec §7.3).

    The same departure rule `find_onset` uses, asked of the end of the window
    rather than its start: not "when did this begin" but "is it still going".
    Mitigation asks it of the minutes after an action, so that a confirmed
    verdict rests on the same judgement of a healthy minute that the
    Investigator made of an unhealthy one - two agents disagreeing about that
    would be two incidents.

    The baseline comes from the whole window, incident minutes included,
    because that is what the later minutes have to be judged against. A window
    of only post-action minutes has no departure to contrast with, and would
    read any steady rate as healthy however elevated it was.

    No minute at or after `moment` is **not** recovery. Absence of evidence
    would otherwise confirm a mitigation the instant it was taken, before the
    service had any chance to answer.
    """
    departures = _departures(buckets)
    since_moment = [
        departed
        for bucket, departed in zip(buckets, departures, strict=True)
        if bucket.bucket_id >= moment
    ]

    if not since_moment:
        return False

    return not any(since_moment)


def _departures(buckets: Sequence[MetricBucket]) -> list[bool]:
    """Whether each minute, in window order, has left the baseline on error
    rate or p95 latency. Both are checked because different failures move
    different metrics - a bad flag spikes errors, a slow dependency does not.
    """
    if not buckets:
        return []

    error_rate_ceiling = _departure_threshold([bucket.error_rate for bucket in buckets])
    latency_ceiling = _departure_threshold([float(bucket.p95_ms) for bucket in buckets])

    return [
        bucket.error_rate > error_rate_ceiling or bucket.p95_ms > latency_ceiling
        for bucket in buckets
    ]


def _run_length_from(departures: Sequence[bool], start: int) -> int:
    """How many consecutive minutes stay departed from `start` onwards."""
    length = 0

    while start + length < len(departures) and departures[start + length]:
        length += 1

    return length


def _departure_threshold(values: Sequence[float]) -> float:
    """The value a minute has to exceed to count as the incident, derived
    from the window's own quiet half.

    The baseline is taken from the lower half of the window rather than from
    all of it: the incident's own minutes are in there too, and they are
    exactly the ones that would drag a whole-window average up and hide the
    onset. A median rather than a mean for the same reason - one 30% minute
    moves a mean, and moves a median not at all.

    The spread is how far the quiet stretch's own worst minutes sit above that
    baseline, rather than how far its average minute does. The two agree on a
    continuous metric and disagree completely on a sampled one, where most
    quiet minutes report the identical quantised figure: the average deviation
    is then zero, the threshold collapses onto the baseline, and every
    ordinary minute reads as the incident starting.
    """
    deviations = get_settings().anomaly_deviations_from_baseline

    quiet_half = sorted(values)[: max(1, len(values) // 2)]
    baseline = median(quiet_half)
    wobble = _quantile(quiet_half, _QUIET_SPREAD_QUANTILE) - baseline
    spread = max(wobble, baseline * _MINIMUM_SPREAD_AS_FRACTION_OF_BASELINE)

    return baseline + deviations * spread


def _quantile(sorted_values: Sequence[float], quantile: float) -> float:
    """The value at `quantile` of an already-sorted sequence, by nearest rank.

    Nearest rank rather than an interpolating quantile because the values are
    a handful of quantised measurements: interpolating between two of them
    invents a rate the service never reported.
    """
    return sorted_values[round(quantile * (len(sorted_values) - 1))]
