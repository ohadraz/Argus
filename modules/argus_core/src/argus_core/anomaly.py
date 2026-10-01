from __future__ import annotations

from collections.abc import Callable, Sequence
from itertools import groupby
from math import inf
from statistics import median
from typing import NamedTuple

from argus_core.models.metrics import MetricBucket

# Five of a bucket's series are judged here - the error rate, the median, the
# 95th, the 99th and the memory in use - and the rest are retrieved without being
# judged. That is a decision rather than an omission, and utilisation is the case
# that makes it worth writing down: CPU tracks traffic, so a departure test over
# it dates an onset at the minute the load arrived, which is minutes before
# anything was wrong and sometimes a busy stretch where nothing ever was. A heap
# that departs its baseline departs it for a reason no traffic pattern explains,
# which is why that gauge is judged and this one is not.
#
# What a saturated service does to its customers is latency, and the five below
# already see that. So `cpu_used_cores`, `cpu_limit_cores`, `request_volume` and
# `cache_hit_ratio` are read by whoever is diagnosing and are no part of the
# judgement that there is an incident at all - see `_departure_threshold`, which
# refuses to derive a floor from the reported volume for a related reason.

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

# How many of a series' own steps a reading may move before the move is
# evidence rather than quantisation. Two, because one is the smallest change
# the series can express at all: a rate over two hundred requests reports 1.0%
# and 1.5% and nothing between, so a single step apart is what two identical
# minutes look like when one of them caught one more failure.
_WITHIN_THE_NOISE_OF_ITS_OWN_STEPS = 2.0

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
    module, because it is a statement about how much the stretch has seen. So
    does `spread`, and for the same reason: the two stretches are different
    shapes of evidence and a spread read the same way from both is wrong about
    one of them.

    The value-ordered half is a sample of ordinary minutes with the incident
    removed, so what a bar has to clear is how far those minutes range - and
    reading a quantile *inside* the lowest half never looks at an ordinary
    minute at all. The opening is a stretch of consecutive time that may be
    rising, so its range is the slope rather than the noise, and a bar built
    from it would grow with the very climb it is there to date.
    """

    minutes: Callable[[Sequence[float]], list[float]]
    minimum_spread_as_fraction_of_baseline: float
    spread: Callable[[Sequence[float], float], float]


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
    service had any chance to answer. Nor is a stretch in which no minute has
    fallen clear at all, which is the same situation one reading later: the
    service has not answered yet. That is what keeps the paragraph above from
    reading the single minute since an action as the lone noisy one it is
    entitled to disregard.

    The whole window is passed down rather than the minutes since `moment`,
    because how long a recovery has to hold for is read off the incident - see
    `_clear_minutes_a_recovery_has_to_show` - and the minutes since an action
    are the one stretch that cannot say.

    `moment` is passed down as well, and for the opposite reason: the level the
    incident is judged against comes from the minutes before the action, while
    the verdict is evaluated over every minute since it. Two spans with two
    jobs, which is already how the quiet stretch and the judged minutes relate.
    See `_the_incidents_own_level` for what the window Mitigation reads does to
    a level computed over the whole of it.
    """
    from_index = _first_index_at_or_after(buckets, moment)

    if from_index is None:
        return False

    still_the_incident = _minutes_still_at_the_incidents_level(
        buckets, thresholds, the_action=from_index
    )

    return _stays_clear_of_the_incident(still_the_incident, from_index, thresholds)


def has_a_reading_since(buckets: Sequence[MetricBucket], moment: str) -> bool:
    """Whether any minute at or after `moment` was read at all.

    The other half of the question above, and the half it cannot answer. A `False`
    from `has_recovered_since` covers two states that mean opposite things: the
    service was watched and has not come back, or nobody watched it. Collapsed,
    a service nobody can see reads as a service still failing - and a caller
    acting on that refutes an explanation nothing measured, undoes the change that
    fixed it, and strikes the cause off the list.

    So this is asked first wherever the difference matters, and what it reports is
    about the window rather than about the service: not whether the minutes are
    well, but whether they exist. Inclusive of `moment` itself, matching the
    recovery question asked of the same window, because a reading taken at the
    minute asked about is a reading of it.

    No thresholds, and the absence is the point: nothing here judges a level, so
    there is nothing for a bar to be drawn against. A window either covers those
    minutes or it does not, and that is true whatever anybody's idea of quiet is.
    """
    return _first_index_at_or_after(buckets, moment) is not None


def _first_index_at_or_after(buckets: Sequence[MetricBucket],
                             moment: str) -> int | None:
    """Where in the window `moment` falls, or `None` if the window ends first.

    Shared by the two questions above so that they cannot come to disagree about
    which minutes count as *since* - the whole value of asking them together is
    that one narrows the other's answer, which it cannot do if each does its own
    arithmetic.
    """
    return next(
        (index for index, bucket in enumerate(buckets) if bucket.bucket_id >= moment),
        None
    )


def find_recovery(buckets: Sequence[MetricBucket],
                  thresholds: AnomalyThresholds) -> str | None:
    """The `bucket_id` of the minute the incident ended, or `None` when the
    window ends with the service still in it (spec §16).

    The other end of `find_onset`, and the moment every measurement of an
    incident has to be bounded by. A window bounded instead by when the walk
    closed the incident is bounded by a fact about Argus: the walk stays open
    through the verification wait, the code-fix attempt and the write-up, so
    the minutes after the mitigation landed are healthy ones, and an average
    taken across them describes a service that was mostly fine. That is how a
    rise in errors came to be reported as *negative*.

    Recovery is read off the metrics rather than off Argus's own timeline - not
    from the moment an action was applied, and not from the moment a verdict was
    reached. Those say when Argus acted and when it concluded, and a service does
    not recover because somebody acted on it; taking them for this would put the
    same defect back at the other boundary. A verdict that carries a recovery
    minute is no exception, because that minute was itself read off the metrics -
    what it is not is the instant the verdict was reached.

    The rule Mitigation's verdict is judged by, stated once here and called from
    both: a minute counts as the incident while it is still up at the incident's
    own level - `_minutes_still_at_the_incidents_level`, the hysteresis bar that
    sits above the departure bar - and the incident is over at the first minute
    that falls below it and stays below it for longer than this incident has ever
    paused. A single minute dipping and climbing back is not the end of an
    incident, for the reason a single minute departing is not the start of one.

    Sharing the rule is worth doing, and it is not what stops the two callers
    disagreeing. Every input the rule has is a function of the minutes handed to
    it, so one rule over a window being polled and over a window bounded by an
    incident's close is two answers. What makes them agree is that the question
    is asked once: Mitigation calls this on the window it holds, records the
    minute, and the write-up reads what was recorded rather than asking again.

    `None` where no minute was ever at the incident's level, because a window
    with no incident in it has no recovery to report and dating one at its
    opening would end an incident before it began. `None` too where the window
    runs out with the service still broken - which is an answer, not a missing
    one: every figure measured over such a window is a lower bound, and the
    caller has to say so rather than quietly bounding it at the last minute
    read.

    Each candidate is judged against the level the incident held *before* that
    minute, which is why the vector is recomputed per candidate rather than read
    once. Mitigation bounds the same history at the action it took; here there is
    no action, and the boundary is the minute being judged - one rule evaluated
    on what each caller holds, rather than the whole window at one end and a
    bounded stretch at the other. A level read off the whole window instead lets
    the minutes *after* a recovery decide how far the service had to fall to have
    recovered, and a service that sheds most of a rise and holds there then reads
    as never having recovered at all. See `_the_incidents_own_level`.

    That bounds how long a recovery has to hold for as well, since
    `_clear_minutes_a_recovery_has_to_show` reads the incident's longest lull off
    the same vector. Deliberate, and the same argument: a lull is a fact about
    the minutes before this one, and a candidate credited with a pause the
    service had not taken yet would be judged against its own future.
    """
    began = _where_the_incident_persisted_from(buckets, thresholds)

    if began is None:
        return None

    for index in range(began + 1, len(buckets)):
        still_the_incident = _minutes_still_at_the_incidents_level(
            buckets, thresholds, the_action=index
        )

        if still_the_incident[index]:
            continue

        if _stays_clear_of_the_incident(still_the_incident, index, thresholds):
            return buckets[index].bucket_id

    return None


def _where_the_incident_persisted_from(buckets: Sequence[MetricBucket],
                                       thresholds: AnomalyThresholds) -> int | None:
    """Where in the window the first departure run long enough to be a state
    begins, or `None` where the window holds no such run.

    Asked of the departure bar rather than of the incident's level, because
    `find_recovery` derives that level per candidate and where the incident began
    cannot be read off a vector that is about to be recomputed against it.

    The quiet half's bar alone, where `find_onset` asks that stretch and the
    window's opening and takes the earlier answer. So this does not see the one
    departure the opening exists to catch - a climb filling the whole window,
    which has no quiet stretch to be measured against - and it does not need to:
    a window that is still climbing when it ends has no clear stretch after its
    departure, so the candidate scan has nothing to report whichever stretch
    found the start. Reading the ceiling answered the same way, since
    `_departure_threshold` is given the quiet half there too.

    The run rather than the first departed minute. `still_the_incident` used to
    carry the persistence test for free, because a series with no persisted run
    is excluded into `inf` and contributes no minute at all, so "did anything
    reach the incident's level" answered "did anything persist" as a side effect.
    Reading the bare bar instead leaves that behind, and a lone departed minute
    then begins an incident, takes a level from its own single sample, and hands
    the calm after it a recovery. Measured on two shapes - a series departing
    every other minute, and one minute departing alone - both of which reported
    a recovery where nothing had persisted.
    """
    departures = _departures(buckets, thresholds, _THE_QUIETEST_MINUTES)

    return next(
        (
            index
            for index, departed in enumerate(departures)
            if departed
            and (index == 0 or not departures[index - 1])
            and _run_length_from(departures, index) >= thresholds.persistence_minutes
        ),
        None
    )


def _stays_clear_of_the_incident(still_the_incident: Sequence[bool],
                                 from_index: int,
                                 thresholds: AnomalyThresholds) -> bool:
    """Whether the window's minutes from `from_index` on are the incident being
    over rather than pausing.

    The one sentence both questions about recovery are asked through -
    Mitigation's "has it recovered since I acted" and "which minute did it come
    back at". Stated once and called twice because two spellings of one judgement
    drift apart, which is reason enough; it is not what keeps the answers
    consistent. Every input here is a function of the minutes handed in, so the
    same sentence over two spans is two answers - and what settles that is the
    minute being measured once and recorded, not this being one function.

    The whole window comes in and the stretch is cut from it here, because the two
    halves of this read different things. What a run of clear minutes has to prove
    is a fact about *this incident* - how long it has been known to pause - and
    only the minutes before the action can say. What the stretch has to show is
    then read off the minutes since it.

    How long is not a number this module owns, and that is the correction. It
    asked for `anomaly_persistence_minutes` clear minutes, on the reasoning that
    an incident takes that many departed minutes to begin so leaving one is
    staying out for as long. The symmetry is decorative: the onset's number is
    there to stop a single noisy minute in a calm window anchoring an
    investigation, and recovery has the hysteresis bar for that job already. What
    the number was actually standing in for is whether the signal oscillates - and
    applied flat it is wrong in both directions. A service that dropped from a
    third of its requests failing to half a percent and stayed there is recovered
    on the first minute, and waiting a second spends a minute of the verification
    window on a question already answered. A service clear four minutes in every
    six is recovered on none of them, and two minutes confirms a mitigation in the
    middle of a lull.

    So the number is measured instead - `_clear_minutes_a_recovery_has_to_show`.

    The departed side keeps the allowance it has, and must. A lone departed minute
    is not a relapse, for the reason a lone departed minute is not an onset - and
    the argument is stronger here, because the window Mitigation reads only grows:
    its last minute is always the freshest sample and always the end of whatever
    run it is in, so one noisy minute would deny a verdict for as long as anybody
    waited.
    """
    stretch = still_the_incident[from_index:]

    return (
        _stays_clear_for_long_enough_to_be_a_recovery(
            stretch,
            _clear_minutes_a_recovery_has_to_show(still_the_incident, thresholds)
        )
        and not _departs_for_long_enough_to_be_the_incident(stretch, thresholds)
    )


def _clear_minutes_a_recovery_has_to_show(still_the_incident: Sequence[bool],
                                          thresholds: AnomalyThresholds) -> int:
    """How many clear minutes in a row this incident has to be held off for
    before it counts as over.

    One more than the longest lull the incident has already come back from. That
    is the whole rule, and it is a measurement rather than a setting: a lull of
    the length this incident is known to take is the one length that proves
    nothing, because the service has already been exactly that well and returned
    once. One minute past it is the shortest stretch the window holds no
    counterexample to.

    So a step - departed, acted on, back - asks for one minute, which is every
    minute of evidence there is. A capacity that will not settle asks for one more
    than its own cycle, whatever that cycle happens to be. No number is picked,
    which is what makes this hold for a shape nobody staged: a rule fitted to two
    bad minutes for one good confirms a useless action on a service that is clear
    four minutes in six, and a rule fitted to that one is wrong about the next
    ratio.

    Reading it off the window is what makes it available at all. The minutes since
    an action cannot say how long this incident pauses for - if they could, the
    question would already be answered.
    """
    return 1 + _the_longest_lull_the_incident_came_back_from(
        still_the_incident, thresholds
    )


def _the_longest_lull_the_incident_came_back_from(
    still_the_incident: Sequence[bool],
    thresholds: AnomalyThresholds
) -> int:
    """The longest stretch of clear minutes inside this incident that the
    incident then returned from, or zero where it never returned.

    Inside the incident, so the calm the window opens with is not a lull: those
    minutes are followed by the onset, which reaches persistence by definition, so
    counting them would have every window demand one more clear minute than the
    calm it opened with - which is most of the window, and never available.

    Returned, and returned properly - the departed run after the lull has to reach
    `anomaly_persistence_minutes`, the same bar `_departs_for_long_enough_to_be_the_incident`
    holds a relapse to. Without that the lone noisy minute this module deliberately
    disregards would count as the incident coming back, and a recovery followed by
    one jittery sample would demand a longer run than the recovery it just
    invalidated - which is the allowance destroying itself.

    Zero where no lull was ever returned from, which is the ordinary case and the
    important one: nothing in such a window says the service bounces, so nothing
    in it justifies waiting to find out.
    """
    runs = _the_runs_from_the_first_departure(still_the_incident)

    return max(
        (
            lull
            for (clear, lull), (_, back) in zip(runs, runs[1:], strict=False)
            if not clear and back >= thresholds.persistence_minutes
        ),
        default=0
    )


def _the_runs_from_the_first_departure(
    still_the_incident: Sequence[bool]
) -> list[tuple[bool, int]]:
    """The window's alternating runs of elevated and clear minutes, with the calm
    it opens with dropped.

    Runs rather than indices because what is being read is a shape - a lull and
    the return after it are adjacent runs, and `zip(runs, runs[1:])` is that
    sentence. Alternating by construction, so the run after a clear one is the
    departed one without having to check.
    """
    runs = [
        (elevated, len(list(group)))
        for elevated, group in groupby(still_the_incident)
    ]

    return runs[1:] if runs and not runs[0][0] else runs


def _stays_clear_for_long_enough_to_be_a_recovery(
    still_the_incident: Sequence[bool],
    clear_minutes_required: int
) -> bool:
    """Whether any run of clear minutes reaches `clear_minutes_required`.

    Takes the number rather than the thresholds, because it is not one of them -
    it is measured from the incident by `_clear_minutes_a_recovery_has_to_show`,
    and a function that read it off `AnomalyThresholds` here would be the fixed
    number this stopped being.

    Any run in the stretch rather than the run it ends on. The stretch is
    everything measured since an action, and a service that came back and then
    caught one noisy sample has recovered - what denies recovery is the *departed*
    side reaching persistence, which is the other half of the expression this sits
    in. Requiring the stretch to end clear would hand that decision to whichever
    minute happened to be freshest.

    A stretch with no clear minute at all fails this for the same reason a calm
    window has no onset: there is nothing here to have lasted.
    """
    return any(
        _run_length_from([not elevated for elevated in still_the_incident], index)
        >= clear_minutes_required
        for index in range(len(still_the_incident))
    )


def _minutes_still_at_the_incidents_level(
    buckets: Sequence[MetricBucket],
    thresholds: AnomalyThresholds,
    the_action: int | None = None
) -> list[bool]:
    """Whether each minute is still up at the incident's level, rather than
    merely above the quiet stretch.

    A fraction of the rise rather than a figure, for the reason the departure
    rule is in units of the baseline's own spread: a service that fails a third
    of its requests and one that doubles its latency have recovered by the same
    proportion and by wildly different amounts.

    Every signal an onset is found in, and for the same reason each was added
    there. A mitigation judged on the symptoms alone would confirm a restart
    the instant latency eased, with the heap already climbing again behind it -
    and would judge a leak recovered on the strength of the metric that reacts
    to it last. The tail is the sharpest case: an incident found in the tail
    alone left every other series where it was, so asking those whether they
    have returned to their baselines confirms a mitigation the instant it is
    taken.

    `the_action` is where the window stops being the incident's history, or
    `None` for a caller that has no action to divide it at. Only the level is
    read from that stretch; which minutes are judged is the caller's own
    question and every minute of the window is answered here.
    """
    if not buckets:
        return []

    each_series = [
        _minutes_above(values, _subsided_threshold(values, thresholds, the_action))
        for values in _the_five_series(buckets)
    ]

    return [any(minute) for minute in zip(*each_series, strict=True)]


def _subsided_threshold(values: Sequence[float],
                        thresholds: AnomalyThresholds,
                        the_action: int | None = None) -> float:
    """What a minute has to have fallen below to count as no longer the
    incident, or `inf` where this series never was the incident.

    A signal that never departed in this window has no incident level, and
    asking whether it has fallen back from one is asking a question with no
    answer. The old spelling answered it anyway, by flooring at the bar
    `find_onset` uses - on the reasoning that a minute which never departed has
    certainly subsided. That step is only safe while the departure bar sits
    above ordinary noise, and for a sampled error rate it does not: the bar is
    derived from the window's lowest half by value, whose own upper quantile is
    still below the middle of the series, so on a rate quantised into
    half-percent steps the measured spread is one step or exactly zero. The bar
    then lands a few thousandths above a baseline that ordinary minutes clear
    five times over, and every calm minute reads as still being the incident.

    What that cost was a real mitigation: the deployment rollback ends an
    incident whose error rate never moved at all - the cache fallback is
    designed behaviour - so recovery was being judged on a signal that had no
    incident in it, and a shop back at its baseline on every other measure was
    refused.

    So a series that never reached the incident level is excluded rather than
    floored. `inf` says that plainly: no minute can exceed it, so this signal
    contributes nothing to whether the incident is still going on - which is
    what the reasoning above always meant.

    Whether it reached that level is the onset's question, and it is asked the
    onset's way: a run of departed minutes long enough to be a state. §16 says
    this is the one question the section asks twice - once to date an onset, once
    to exclude a series from recovery - so the two answers have to agree, and
    anything else here is a second spelling of a rule stated elsewhere.

    It was spelled a second way, and the difference is what a maximum is. Asking
    whether the series' worst minute cleared the bar by more than the series can
    resolve made the exclusion turn on one sample, and a maximum is the one
    statistic a single sample moves arbitrarily far. A shop drawing one to four
    failures in two hundred requests draws eight occasionally; that minute lifted
    the maximum past the margin, admitted a series with no incident in it, and
    left recovery judged against a ceiling a fifth of the way up from the bar to
    that outlier - which ordinary jitter sits above. Every rollback was then
    refused for as long as the minute took to leave the window: six hours, on 21%
    of clock positions against the fixture, and on any incident that leaves one
    of the five judged signals flat.

    The margin is not missed. It already lives in the departure bar, where
    `_WITHIN_THE_NOISE_OF_ITS_OWN_STEPS` floors the spread at two of whatever the
    quiet stretch resolves, so a minute inside its own noise does not depart in
    the first place and never reaches the run this asks about.

    Deliberately not `find_onset`'s allowance for a run still going when the
    window ends. That allowance credits a final run of any length, so one noisy
    last minute would admit an otherwise-flat series - this same defect at the
    tail instead of the middle. What the strict bar trades for that is named
    rather than hidden: a relapse that is one minute old when the confirming poll
    lands is not credited here. The departed side's own allowance in
    `_stays_clear_of_the_incident` already lets that minute pass, and the
    reassurance offered there - that a real relapse is a run of two by the next
    poll - covers a verdict being denied and not one being granted, because
    `CONFIRMED` leaves the loop and there is no next poll. That is a known limit
    of the recovery end, not of this exclusion.

    A run is compared by length rather than by value, so where a sum of floats
    happens to round decides nothing here. A minute a thousandth of a step above
    the bar departs, and one departed minute is not an incident whatever its
    arithmetic came to.

    The ceiling below was read off the worst minute too, and that was the same
    statistic this exclusion stopped trusting, at the other half of one function.
    There a maximum decided whether a signal had departed at all; here it decided
    how far it had to have fallen back, so a spike raised the ceiling instead of
    lowering it and confirmed early where the other defect refused. The two are
    not equally bad: a refusal can be waited out, and a false `CONFIRMED` closes
    the incident and stops. Measured on a plateau at five times its baseline with
    one minute far above it, the ceiling landed above the plateau itself and a
    service that had not moved read as recovered.

    So the level comes from the departed minutes, as §16 says it does - "the
    incident from the minutes that departed", plural - and it is their median for
    the reason the baseline is a median rather than a mean. One extreme minute
    moves a mean and moves a median not at all. Which way that cuts is worth
    stating: recovery becomes harder to claim on a spiky incident and identical
    on a flat one.
    """
    departed = _departure_threshold(values, thresholds, _THE_QUIETEST_MINUTES)
    above = _minutes_above(values, departed)

    if not _departs_for_long_enough_to_be_the_incident(above, thresholds):
        return inf

    subsided = thresholds.recovery_fraction_of_the_rise
    level = _the_incidents_own_level(values, above, the_action)

    return max(departed, level - subsided * (level - departed))


def _the_incidents_own_level(values: Sequence[float],
                             above: Sequence[bool],
                             the_action: int | None) -> float:
    """How high this series sat while it was the incident, taken from the
    minutes that departed and before the action divided them.

    The history rather than the whole window, and the reason is not that a
    recovered minute would drag the level down - it would not, because a minute
    back at its baseline is below the departure bar and never enters this set at
    all. It is the *partly* recovered minute that does, and what it costs is not
    a wrong answer in one direction but an answer that depends on when the poll
    happened to land.

    Measured on a service that fell from a plateau at 1000ms to 350ms and held
    there, with the bar at 260. Over the whole window the verdict reads recovered
    one, two and three minutes after the action, not recovered at five and eight,
    and recovered again at thirteen and twenty-one. Nothing about the service
    changes across that. What changes is the window Mitigation is holding: first
    the 350ms minutes join the departed set and pull the level down to their own,
    which drops the ceiling below them and reads them as a relapse; later they
    outnumber the incident in the window's quiet half, which lifts the departure
    bar above the plateau until nothing has departed at all. Read from the
    history, every one of those polls answers recovered, which is the right
    answer and - more to the point - the same answer.

    `the_action` is `None` for a caller with no action to divide the window at,
    and then the history is the whole of it. That is one rule evaluated on what
    each caller holds rather than two rules: the level comes from the incident's
    history, and `find_recovery` is reading a window that is entirely history.

    Where the history holds no departed minute the level falls back to every
    departed minute in the window, and that stretch is reached rather than
    hypothetical: the action can land at or before the incident's first departed
    minute - a series that was well until it was acted on, or a window asked
    about its own opening - and a flapping capacity asked from every minute in
    turn does exactly that. The fallback is the answer rather than a degenerate
    one, because something in this window did depart and the judgement should be
    against it. What it must not do is exclude the series: `inf` here would judge
    a signal that is departed *now* against no level at all, which is the false
    `CONFIRMED` this whole function exists to stop.
    """
    its_history_ends_at = len(values) if the_action is None else the_action
    departed_minutes = [
        (minute, value)
        for minute, (value, departed) in enumerate(zip(values, above, strict=True))
        if departed
    ]
    its_history = [
        value for minute, value in departed_minutes if minute < its_history_ends_at
    ]

    return median(its_history or [value for _, value in departed_minutes])


def _minutes_above(values: Sequence[float], ceiling: float) -> list[bool]:
    """Which of one series' minutes are above `ceiling`, in window order.

    The one place a reading is compared to a bar, and that is the point of it.
    Both questions this module asks about a signal - did it depart, and has it
    fallen back - are asked of the same comparison, and they were spelled
    separately: `_departures` ored five inline comparisons and kept no record of
    which series departed, so the exclusion had to derive the fact again from a
    maximum. The two spellings then disagreed, and the disagreement was the bug.

    One series rather than five, because who wants the five ored together is the
    caller's question and not this one's. `_departures` ors them; the exclusion
    asks about the single series it is being asked about.
    """
    return [value > ceiling for value in values]


def _departs_for_long_enough_to_be_the_incident(departures: Sequence[bool],
                                                thresholds: AnomalyThresholds) -> bool:
    """Whether any run of departed minutes is long enough to be a state rather
    than noise.

    A run that reaches `anomaly_persistence_minutes`, and only that. `find_onset`
    additionally counts a run still going when the window ends - an incident that
    began a minute ago has not failed to persist, it has yet to be given the
    chance - and that allowance is exactly wrong at this end.

    The window Mitigation reads is the window it has just polled, so its final
    minute is always the freshest sample and always the end of whatever run it
    is in. Crediting that run with persistence it has not shown lets one noisy
    minute deny a verdict every minute before it supports, and waiting does not
    clear it: the window only grows, and each new last minute is a fresh chance
    to land noisy. A real relapse is unaffected - it is still departed at the
    next poll, where it is a run of two and evidence rather than a sample.

    What the two ends share is the bar a minute has to clear. What a run of them
    has to prove is asked differently, because starting an incident and ending
    one are different questions.
    """
    return any(
        _run_length_from(departures, index) >= thresholds.persistence_minutes
        for index, departed in enumerate(departures)
        if departed and (index == 0 or not departures[index - 1])
    )


def _departures(buckets: Sequence[MetricBucket],
                thresholds: AnomalyThresholds,
                calm: _CalmStretch) -> list[bool]:
    """Whether each minute, in window order, has left the baseline on error
    rate, any of the three latency quantiles, or memory.

    All of them are checked because different failures move different metrics -
    a bad flag spikes errors, a slow dependency does not, and a leak moves
    neither until it has been climbing for hours. Memory is a leak's earliest
    and clearest signal, and it runs ahead of the latency and the errors it
    eventually causes: a detector reading only those would date every leak at
    the minute it became a user-visible failure.

    The three quantiles are three signals rather than one for the same reason.
    A fault that removes a fast path lives entirely in the median; a fault
    reaching a few requests in a hundred is below the p95 by arithmetic and
    lives entirely in the tail. Each is an incident the others cannot see.
    """
    if not buckets:
        return []

    each_series = [
        _minutes_above(values, _departure_threshold(values, thresholds, calm))
        for values in _the_five_series(buckets)
    ]

    return [any(minute) for minute in zip(*each_series, strict=True)]


def _the_five_series(buckets: Sequence[MetricBucket]) -> list[list[float]]:
    """One window read as the five series a departure can appear in.

    Named once, because every question about whether a signal moved is asked of
    these same five and an answer derived from four of them would be a different
    rule wearing this one's name.
    """
    return [
        [bucket.error_rate for bucket in buckets],
        [float(bucket.p50_ms) for bucket in buckets],
        [float(bucket.p95_ms) for bucket in buckets],
        [float(bucket.p99_ms) for bucket in buckets],
        [float(bucket.memory_used_bytes) for bucket in buckets]
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

    How the spread is read belongs to the stretch, because the two stretches are
    different shapes of evidence - see `_CalmStretch`.

    The value-ordered half reads its range, and that is the correction to this
    function's history of being wrong. That stretch is the window's lowest half
    *by value*, so a quantile taken inside it is still below the middle of the
    series: the 90th percentile of the lowest half is about the 45th of the
    whole, and the distance from there to the 25th is not a measure of how far
    ordinary minutes reach. It cannot be, because it never looks at one. On a
    rate sampled over a couple of hundred requests and quantised into
    half-percent steps the two quantiles land on the identical figure, the
    measured spread is exactly zero, and the bar falls back on a floor of a
    tenth of the baseline - a few thousandths above a level calm minutes clear
    five times over.

    The cost was paid at both ends. Calm windows reported an onset in a little
    over half of all runs, and a deployment rollback that had genuinely
    ended an incident was refused, because the error rate - which never moves
    in that scenario at all - read as still elevated on every minute after it.

    Neither stretch reaches above the lowest half of the window, and that is
    deliberate. Taking the window's own upper quantile would measure the fault
    rather than the noise: a flag toggle putting a tenth of the window at thirty
    percent errors would set a bar no incident could ever clear.

    Floored twice over, and the second floor is the one that matters on a short
    window. A stretch of four quantised minutes has a range of one step or none,
    so the range degenerates exactly where the quantile did - and the fraction
    of the baseline that catches it is a tenth of one percent, which is nothing.
    A series only resolves differences the size of its own step, so a departure
    inside a couple of those is a departure the measurement cannot claim to have
    seen. Read from the series rather than from `request_volume`, because the
    reported volume is not always the number of requests a rate was actually
    measured over, and a floor derived from an overstated one is no floor.
    """
    deviations = thresholds.deviations_from_baseline

    quiet = calm.minutes(values)
    baseline = median(quiet)
    spread = max(
        calm.spread(quiet, baseline),
        baseline * calm.minimum_spread_as_fraction_of_baseline,
        _WITHIN_THE_NOISE_OF_ITS_OWN_STEPS * _what_the_series_resolves(quiet)
    )

    return baseline + deviations * spread


def _what_the_series_resolves(quiet: Sequence[float]) -> float:
    """The finest difference these readings actually distinguish.

    The smallest gap between two distinct values. A rate sampled over two
    hundred requests moves in half-percent steps whatever it reports its volume
    as, and this is what says so. Continuous enough series answer with the
    millisecond they are rounded to, which floors nothing.

    Asked of the quiet stretch rather than of the whole window, because a
    smallest gap is only a quantisation step among readings that are all
    ordinary. Across a whole window the two nearest distinct values may be the
    calm level and the incident's, and a floor built from that measures the
    fault and then hides it.

    Zero where every reading is identical, which is right: a series that never
    moved offers no evidence about how far it moves, and the other two floors
    are what stand in for that.
    """
    distinct = sorted(set(quiet))
    gaps = [later - earlier for earlier, later in zip(distinct, distinct[1:], strict=False)]

    return min(gaps) if gaps else 0.0


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


def _how_far_the_quiet_minutes_range(quiet: Sequence[float],
                                     _baseline: float) -> float:
    """The distance from the quietest minute to the least quiet one.

    Two-sided, which a quantile taken inside the lowest half cannot be, and
    safe from the incident, which is not in that half by construction.
    """
    return max(quiet) - min(quiet)


def _how_far_the_opening_climbs(opening: Sequence[float],
                                baseline: float) -> float:
    """How far the opening's worst minutes sit above its median.

    Not its range, because these minutes are consecutive rather than selected:
    an opening that is already rising has a range equal to its own slope, and a
    bar built from that grows with the climb it exists to date - which is how a
    ramp filling the whole window came to report a confident start in the middle
    of itself.
    """
    return _quantile(opening, _QUIET_SPREAD_QUANTILE) - baseline


# What is unusual for this service, and what this window looked like when it
# began. Neither is discarded in favour of the other: the first is what tells an
# older resolved departure from the current one, the second is the only one that
# can see a climb.
_THE_QUIETEST_MINUTES = _CalmStretch(
    minutes=_the_quietest_minutes,
    minimum_spread_as_fraction_of_baseline=_MINIMUM_SPREAD_AS_FRACTION_OF_BASELINE,
    spread=_how_far_the_quiet_minutes_range
)
_THE_WINDOWS_OPENING = _CalmStretch(
    minutes=_the_windows_opening,
    minimum_spread_as_fraction_of_baseline=(
        _MINIMUM_OPENING_SPREAD_AS_FRACTION_OF_BASELINE
    ),
    spread=_how_far_the_opening_climbs
)


def _quantile(sorted_values: Sequence[float], quantile: float) -> float:
    """The value at `quantile` of an already-sorted sequence, by nearest rank.

    Nearest rank rather than an interpolating quantile because the values are
    a handful of quantised measurements: interpolating between two of them
    invents a rate the service never reported.
    """
    return sorted_values[round(quantile * (len(sorted_values) - 1))]
