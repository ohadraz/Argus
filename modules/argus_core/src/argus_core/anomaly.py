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
    """Whether the incident has subsided over the minutes from `moment` onwards
    (spec §7.3).

    Not the departure rule `find_onset` uses, and deliberately not. Starting an
    incident and ending one are different questions asked of the same numbers:
    an onset is the first minute that leaves the quiet stretch, and recovery is
    the incident's own level falling away. Judging recovery on the onset's
    threshold demands a return to indistinguishable-from-quiet, which a service
    still shedding the last of an outage does not reach inside any time it is
    given - and the mitigation that fixed it is then refuted and put back.

    So a minute has recovered once it has fallen most of the way from the
    incident's own level back towards the baseline. Both ends come from the
    window: the baseline from its quiet half, the incident from the minutes
    that departed. A window with no departure in it has no incident to have
    recovered from, and every minute in it counts as recovered - which is the
    right answer for the only caller, since Mitigation asks this of a window it
    reached by way of an onset.

    A lone departed minute is not a relapse, for the same reason `find_onset`
    refuses to call one an onset: an incident is a state the service stays in,
    and a single minute that departs has, by the next one, already come back.
    Reading one as evidence against recovery would be worse here than there,
    because the window Mitigation reads only grows - a minute that never leaves
    it denies the verdict for as long as anyone waits, and a longer timeout
    buys nothing.

    No minute at or after `moment` is **not** recovery. Absence of evidence
    would otherwise confirm a mitigation the instant it was taken, before the
    service had any chance to answer.
    """
    still_the_incident = _minutes_still_at_the_incidents_level(buckets)
    since_moment = [
        elevated
        for bucket, elevated in zip(buckets, still_the_incident, strict=True)
        if bucket.bucket_id >= moment
    ]

    if not since_moment:
        return False

    return not _departs_for_long_enough_to_be_the_incident(since_moment)


def _minutes_still_at_the_incidents_level(
    buckets: Sequence[MetricBucket]
) -> list[bool]:
    """Whether each minute is still up at the incident's level, rather than
    merely above the quiet stretch.

    A fraction of the rise rather than a figure, for the reason the departure
    rule is in units of the baseline's own spread: a service that fails a third
    of its requests and one that doubles its latency have recovered by the same
    proportion and by wildly different amounts.
    """
    error_rates = [bucket.error_rate for bucket in buckets]
    latencies = [float(bucket.p95_ms) for bucket in buckets]
    error_rate_ceiling = _subsided_threshold(error_rates)
    latency_ceiling = _subsided_threshold(latencies)

    return [
        bucket.error_rate > error_rate_ceiling or bucket.p95_ms > latency_ceiling
        for bucket in buckets
    ]


def _subsided_threshold(values: Sequence[float]) -> float:
    """What a minute has to have fallen below to count as no longer the
    incident.

    Above the departure threshold by construction: a minute that never departed
    has certainly subsided, so the floor here is the bar `find_onset` uses. On
    a window with no incident in it the two are the same, and nothing is
    reported as still elevated.
    """
    departed = _departure_threshold(values)
    at_its_worst = max(values, default=departed)
    subsided = get_settings().recovery_fraction_of_the_rise

    return max(departed, at_its_worst - subsided * (at_its_worst - departed))


def _departs_for_long_enough_to_be_the_incident(departures: Sequence[bool]) -> bool:
    """Whether any run of departed minutes is long enough to be a state rather
    than noise.

    The same threshold `find_onset` anchors on, so the two agents agree about
    what "still broken" means: a run that reaches
    `anomaly_persistence_minutes`, or one still going when the window ends -
    which has not failed to persist, it has yet to be given the chance.
    """
    required = get_settings().anomaly_persistence_minutes

    for index, departed in enumerate(departures):
        if not departed or (index > 0 and departures[index - 1]):
            continue

        length = _run_length_from(departures, index)

        if length >= required or index + length == len(departures):
            return True

    return False


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
