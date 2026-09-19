from __future__ import annotations

from collections.abc import Callable, Sequence
from statistics import median
from typing import NamedTuple

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

# How much of a window its opening is taken to be. A tenth, bounded below at
# three minutes, and both bounds are load-bearing. Longer, and the opening
# reaches into a departure that really is visible - a window whose calm first
# fifth is followed by a step gets read as having no start at all. Shorter, and
# a climb older than the window clears the threshold too far in to be
# recognised as one. Below three minutes there are too few readings to say
# anything about a spread at all, which is what bites on the short windows a
# demo actually serves.
_OPENING_AS_FRACTION_OF_WINDOW = 0.1
_SHORTEST_OPENING = 3

# The smallest wobble the opening's baseline is credited with. Far above the
# figure the quiet half is held to, because the two stretches are measured with
# very different confidence: half a window has seen the metric's range, and
# three or four minutes have not. A sampled error rate quantised into
# half-percent steps can read 0.5% for the window's first minutes and 1.0% for
# the next ten without anything having happened, and a short stretch has no way
# to know that - so the floor stands in for the noise those minutes were too
# few to observe. Measured: below about 0.35 that drift reads as an onset;
# above about 0.5 a real climb is dated late.
_MINIMUM_OPENING_SPREAD_AS_FRACTION_OF_BASELINE = 0.4

# How far past the opening an onset has to land before it is believed as a
# start rather than reported as a lower bound. An onset nearer than this was
# measured against minutes that are themselves part of the climb: the baseline
# rose with the fault, and the first minute that cleared it says where the
# window happens to open, not where anything began. Twice, because a ramp
# measured against an opening of `n` minutes clears its own threshold at about
# `1.7n` - so anything inside `2n` is the shape of a window that opened
# mid-climb, and anything beyond it is a start the window can actually show.
_OPENINGS_BEFORE_A_START_IS_VISIBLE = 2


class _CalmStretch(NamedTuple):
    """Which minutes of a window are taken to be calm, and how little spread
    they may be credited with.

    Two of these exist and a departure under either is a departure. Ordered by
    value, the window's lowest half is the calm stretch - which is what keeps an
    older, already-resolved departure in the same window from being read as the
    current one. Ordered by time, the window's opening is the calm stretch -
    which is what makes a gradual climb visible at all, since the value-ordered
    calm half of a ramp *is* the early ramp and the spread derived from it is
    the slope rather than the noise.

    The floor travels with the stretch rather than being one number for the
    module, because it is a statement about how much the stretch has seen.
    """

    minutes: Callable[[Sequence[float]], list[float]]
    minimum_spread_as_fraction_of_baseline: float


class AnomalyThresholds(NamedTuple):
    """Where the algorithm draws its three lines.

    A domain value, not a slice of `Settings`: this module decides what counts
    as an incident starting and what counts as recovery, and a rule of that
    kind has no business knowing how Argus is configured. The caller already
    holds the numbers - the same arrangement `status_after(state, max_rounds)`
    has, and for the same reason.

    Required at every call, with no default. A default here would mean any
    caller left unwired silently gets these numbers instead of the deployment's,
    and the environment variable would stop taking effect without a single test
    going red - the test environment runs on these values anyway.
    """

    deviations_from_baseline: float
    persistence_minutes: int
    recovery_fraction_of_the_rise: float


def find_onset(buckets: Sequence[MetricBucket],
               thresholds: AnomalyThresholds) -> str | None:
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

    The question is asked of both calm stretches and the earlier answer is
    taken. The two ask different things of the same numbers - one what is
    unusual for this service, the other when this window stopped looking like
    its own beginning - and a fault that ramps is invisible to the first: its
    lowest half by value *is* the early climb, so the baseline rises with the
    fault and the spread derived from it is the slope. Neither answer is
    discarded, because a window holding an older resolved departure needs the
    value-ordered one to keep from dating the current incident from it.
    """
    against_the_quiet_half = _the_onset_against(
        buckets, thresholds, _THE_QUIETEST_MINUTES
    )
    against_the_opening = _the_start_the_opening_can_claim(
        _the_onset_against(buckets, thresholds, _THE_WINDOWS_OPENING), len(buckets)
    )
    found = [
        index
        for index in (against_the_quiet_half, against_the_opening)
        if index is not None
    ]

    return buckets[min(found)].bucket_id if found else None


def _the_onset_against(buckets: Sequence[MetricBucket],
                       thresholds: AnomalyThresholds,
                       calm: _CalmStretch) -> int | None:
    """Which minute one calm stretch dates the incident from, or `None` if it
    sees no departure that persisted."""
    departures = _departures(buckets, thresholds, calm)
    required = thresholds.persistence_minutes

    for index in reversed(range(len(departures))):
        if not departures[index] or (index > 0 and departures[index - 1]):
            continue

        length = _run_length_from(departures, index)

        if length >= required or index + length == len(departures):
            return index

    return None


def _the_start_the_opening_can_claim(index: int | None,
                                     window_length: int) -> int | None:
    """The opening's answer, or the window's first minute when that answer
    lands too near the opening to have been measured against calm.

    A baseline drawn from minutes that are themselves climbing rises with the
    fault, so the first minute to clear it says where the window happens to
    open and not where anything began. The honest answer is then the earliest
    minute there is, reported as the lower bound it is - which is exactly what
    makes the next round widen the window rather than believe this one.
    """
    if index is None:
        return None

    visible_from = _OPENINGS_BEFORE_A_START_IS_VISIBLE * _opening_length(window_length)

    return index if index >= visible_from else 0


def earliest_bucket_is_anomalous(buckets: Sequence[MetricBucket],
                                 thresholds: AnomalyThresholds) -> bool:
    """Whether the window opens already inside the incident - the structural
    trigger for widening the next iteration (spec §9).

    True means no calm stretch is visible: the baseline is off the left edge,
    so the onset predates everything retrieved and the next iteration has to
    reach further back. An empty window has no earliest bucket and so cannot
    show one.
    """
    if not buckets:
        return False

    return find_onset(buckets, thresholds) == buckets[0].bucket_id


def has_recovered_since(buckets: Sequence[MetricBucket],
                        moment: str,
                        thresholds: AnomalyThresholds) -> bool:
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
    still_the_incident = _minutes_still_at_the_incidents_level(buckets, thresholds)
    since_moment = [
        elevated
        for bucket, elevated in zip(buckets, still_the_incident, strict=True)
        if bucket.bucket_id >= moment
    ]

    if not since_moment:
        return False

    return not _departs_for_long_enough_to_be_the_incident(since_moment, thresholds)


def _minutes_still_at_the_incidents_level(
    buckets: Sequence[MetricBucket],
    thresholds: AnomalyThresholds
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
    error_rate_ceiling = _subsided_threshold(error_rates, thresholds)
    latency_ceiling = _subsided_threshold(latencies, thresholds)

    return [
        bucket.error_rate > error_rate_ceiling or bucket.p95_ms > latency_ceiling
        for bucket in buckets
    ]


def _subsided_threshold(values: Sequence[float],
                        thresholds: AnomalyThresholds) -> float:
    """What a minute has to have fallen below to count as no longer the
    incident.

    Above the departure threshold by construction: a minute that never departed
    has certainly subsided, so the floor here is the bar `find_onset` uses. On
    a window with no incident in it the two are the same, and nothing is
    reported as still elevated.
    """
    departed = _departure_threshold(values, thresholds, _THE_QUIETEST_MINUTES)
    at_its_worst = max(values, default=departed)
    subsided = thresholds.recovery_fraction_of_the_rise

    return max(departed, at_its_worst - subsided * (at_its_worst - departed))


def _departs_for_long_enough_to_be_the_incident(departures: Sequence[bool],
                                                thresholds: AnomalyThresholds) -> bool:
    """Whether any run of departed minutes is long enough to be a state rather
    than noise.

    The same threshold `find_onset` anchors on, so the two agents agree about
    what "still broken" means: a run that reaches
    `anomaly_persistence_minutes`, or one still going when the window ends -
    which has not failed to persist, it has yet to be given the chance.
    """
    required = thresholds.persistence_minutes

    for index, departed in enumerate(departures):
        if not departed or (index > 0 and departures[index - 1]):
            continue

        length = _run_length_from(departures, index)

        if length >= required or index + length == len(departures):
            return True

    return False


def _departures(buckets: Sequence[MetricBucket],
                thresholds: AnomalyThresholds,
                calm: _CalmStretch) -> list[bool]:
    """Whether each minute, in window order, has left the baseline on error
    rate, p95 latency or memory.

    All three are checked because different failures move different metrics - a
    bad flag spikes errors, a slow dependency does not, and a leak moves neither
    until it has been climbing for hours. Memory is a leak's earliest and
    clearest signal, and it runs ahead of the latency and the errors it
    eventually causes: a detector reading only those would date every leak at
    the minute it became a user-visible failure.
    """
    if not buckets:
        return []

    error_rate_ceiling = _departure_threshold(
        [bucket.error_rate for bucket in buckets], thresholds, calm
    )
    latency_ceiling = _departure_threshold(
        [float(bucket.p95_ms) for bucket in buckets], thresholds, calm
    )
    memory_ceiling = _departure_threshold(
        [float(bucket.memory_used_bytes) for bucket in buckets], thresholds, calm
    )

    return [
        bucket.error_rate > error_rate_ceiling
        or bucket.p95_ms > latency_ceiling
        or bucket.memory_used_bytes > memory_ceiling
        for bucket in buckets
    ]


def _run_length_from(departures: Sequence[bool], start: int) -> int:
    """How many consecutive minutes stay departed from `start` onwards."""
    length = 0

    while start + length < len(departures) and departures[start + length]:
        length += 1

    return length


def _departure_threshold(values: Sequence[float],
                         thresholds: AnomalyThresholds,
                         calm: _CalmStretch) -> float:
    """The value a minute has to exceed to count as the incident, derived
    from the stretch of the window `calm` takes to be quiet.

    The baseline is taken from part of the window rather than from all of it:
    the incident's own minutes are in there too, and they are exactly the ones
    that would drag a whole-window average up and hide the onset. A median
    rather than a mean for the same reason - one 30% minute moves a mean, and
    moves a median not at all.

    The spread is how far the quiet stretch's own worst minutes sit above that
    baseline, rather than how far its average minute does. The two agree on a
    continuous metric and disagree completely on a sampled one, where most
    quiet minutes report the identical quantised figure: the average deviation
    is then zero, the threshold collapses onto the baseline, and every
    ordinary minute reads as the incident starting.
    """
    deviations = thresholds.deviations_from_baseline

    quiet = calm.minutes(values)
    baseline = median(quiet)
    wobble = _quantile(quiet, _QUIET_SPREAD_QUANTILE) - baseline
    spread = max(
        wobble, baseline * calm.minimum_spread_as_fraction_of_baseline
    )

    return baseline + deviations * spread


def _the_quietest_minutes(values: Sequence[float]) -> list[float]:
    """The window's lowest half by value, in order."""
    return sorted(values)[: max(1, len(values) // 2)]


def _the_windows_opening(values: Sequence[float]) -> list[float]:
    """The window's earliest minutes, sorted so a spread can be read off them.
    """
    return sorted(values[: _opening_length(len(values))])


def _opening_length(window_length: int) -> int:
    """How many of a window's earliest minutes are taken to be its opening."""
    return max(
        _SHORTEST_OPENING, round(window_length * _OPENING_AS_FRACTION_OF_WINDOW)
    )


# What is unusual for this service, and what this window looked like when it
# began. Neither is discarded in favour of the other: the first is what tells an
# older resolved departure from the current one, the second is the only one that
# can see a climb.
_THE_QUIETEST_MINUTES = _CalmStretch(
    minutes=_the_quietest_minutes,
    minimum_spread_as_fraction_of_baseline=_MINIMUM_SPREAD_AS_FRACTION_OF_BASELINE
)
_THE_WINDOWS_OPENING = _CalmStretch(
    minutes=_the_windows_opening,
    minimum_spread_as_fraction_of_baseline=(
        _MINIMUM_OPENING_SPREAD_AS_FRACTION_OF_BASELINE
    )
)


def _quantile(sorted_values: Sequence[float], quantile: float) -> float:
    """The value at `quantile` of an already-sorted sequence, by nearest rank.

    Nearest rank rather than an interpolating quantile because the values are
    a handful of quantised measurements: interpolating between two of them
    invents a rate the service never reported.
    """
    return sorted_values[round(quantile * (len(sorted_values) - 1))]
