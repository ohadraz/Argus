from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from argus_core.anomaly import (
    AnomalyThresholds,
    earliest_bucket_is_anomalous,
    find_onset,
    find_recovery,
    has_a_reading_since,
    has_recovered_since,
)
from argus_core.models.metrics import MetricBucket
from argus_core.timestamps import parse_iso, to_iso_minute
from argus_testkit import Assertion, Scenario

from argus_core_test.framework.windows import (
    a_quiet_window_of,
    with_the_cpu_saturated,
    with_the_error_rate_raised,
)

# Where this suite draws the algorithm's lines - the same numbers the
# environment carries by default, stated here because every expectation
# below is arithmetic on them. A test reading them from the configuration
# the code reads would agree with itself whatever either said.
SOME_THRESHOLDS = AnomalyThresholds(
    deviations_from_baseline=3.0,
    persistence_minutes=2,
    recovery_fraction_of_the_rise=0.8
)

CALM_MINUTES = 6
CALM_P50_MS = 80
CALM_P95_MS = 200
CALM_P99_MS = 350
CALM_MEMORY_BYTES = 440 * 1024**2
CALM_ERROR_RATE = 0.01
MEMORY_LIMIT_BYTES = 2 * 1024**3


@pytest.mark.unit
def test_find_onset_reports_the_first_minute_that_departs_from_a_steady_rate() -> None:
    some_steady_rate = 0.01                            # -> 1% error rate - normal
    some_degradation_rate = some_steady_rate * 9       # -> 9% error rate - escalation
    dont_care_worse_rate = some_steady_rate * 18       # -> 18%, shape only - worse...
    some_calm_subwindow = [some_steady_rate] * CALM_MINUTES
    some_window = a_window_of(
        some_calm_subwindow + [some_degradation_rate, dont_care_worse_rate]
    )

    first_departing_bucket = some_window[len(some_calm_subwindow)]

    Scenario() \
        .given(
            some_window
        ) \
        .when(
            lambda: find_onset(some_window, SOME_THRESHOLDS)
        ) \
        .then(
            _the_onset_is(first_departing_bucket.bucket_id)
        )


@pytest.mark.unit
def test_find_onset_reports_nothing_when_the_whole_window_is_steady() -> None:
    some_steady_rate = 0.01
    some_window = a_window_of([some_steady_rate] * (CALM_MINUTES + 2))

    Scenario() \
        .given(
            some_window
        ) \
        .when(
            lambda: find_onset(some_window, SOME_THRESHOLDS)
        ) \
        .then(
            _no_onset_was_found()
        )


@pytest.mark.unit
def test_find_onset_reports_nothing_for_an_empty_window() -> None:
    empty_window: list[MetricBucket] = []

    Scenario() \
        .given(
            empty_window
        ) \
        .when(
            lambda: find_onset(empty_window, SOME_THRESHOLDS)
        ) \
        .then(
            _no_onset_was_found()
        )


@pytest.mark.unit
def test_find_onset_catches_the_same_shape_at_a_low_and_at_a_high_steady_rate() -> None:
    # The point of measuring in the baseline's own spread: a service that idles
    # at 0.5% errors and one that idles at 8% are both judged against
    # themselves, so one configured setting works for both.
    some_low_steady_rate = 0.005
    some_high_steady_rate = 0.08
    some_low_rate_window = a_window_departing_from(some_low_steady_rate)
    some_high_rate_window = a_window_departing_from(some_high_steady_rate)

    first_departing_low_rate_bucket = some_low_rate_window[CALM_MINUTES]
    first_departing_high_rate_bucket = some_high_rate_window[CALM_MINUTES]

    Scenario() \
        .given(
            some_low_rate_window
        ) \
        .when(
            lambda: find_onset(some_low_rate_window, SOME_THRESHOLDS)
        ) \
        .then(
            _the_onset_is(first_departing_low_rate_bucket.bucket_id)
        )
    Scenario() \
        .given(
            some_high_rate_window
        ) \
        .when(
            lambda: find_onset(some_high_rate_window, SOME_THRESHOLDS)
        ) \
        .then(
            _the_onset_is(first_departing_high_rate_bucket.bucket_id)
        )


@pytest.mark.unit
def test_find_onset_catches_a_latency_departure_at_a_steady_error_rate() -> None:
    # The two fixture scenarios move different metrics, so a bucket whose p95
    # leaves its baseline is the incident even when the error rate never moves.
    dont_care_steady_rate = 0.01
    some_degradation_latency_ms = CALM_P95_MS * 5
    dont_care_worse_latency_ms = CALM_P95_MS * 8
    some_calm_subwindow = [CALM_P95_MS] * CALM_MINUTES
    some_window = a_window_of(
        [dont_care_steady_rate] * (len(some_calm_subwindow) + 2),
        p95_ms_values=some_calm_subwindow
        + [some_degradation_latency_ms, dont_care_worse_latency_ms],
    )

    first_departing_bucket = some_window[len(some_calm_subwindow)]

    Scenario() \
        .given(
            some_window
        ) \
        .when(
            lambda: find_onset(some_window, SOME_THRESHOLDS)
        ) \
        .then(
            _the_onset_is(first_departing_bucket.bucket_id)
        )


@pytest.mark.unit
def test_the_earliest_bucket_is_anomalous_when_the_window_opens_at_its_worst_minute() -> None:
    # No calm stretch is visible: the window opens mid-incident and decays, so
    # the onset is off the left edge and the next iteration must reach back.
    some_declining_rates_from_a_peak = [0.30, 0.28, 0.25, 0.21, 0.20, 0.19]
    some_window_opening_mid_incident = a_window_of(some_declining_rates_from_a_peak)

    Scenario() \
        .given(
            some_window_opening_mid_incident
        ) \
        .when(
            lambda: earliest_bucket_is_anomalous(some_window_opening_mid_incident, SOME_THRESHOLDS)
        ) \
        .then(
            _the_answer_is(True)
        )


@pytest.mark.unit
def test_the_earliest_bucket_is_not_anomalous_when_the_window_opens_calm() -> None:
    some_steady_rate = 0.01
    some_degradation_rate = some_steady_rate * 9
    some_calm_subwindow = [some_steady_rate] * CALM_MINUTES
    some_window = a_window_of(some_calm_subwindow + [some_degradation_rate])

    Scenario() \
        .given(
            some_window
        ) \
        .when(
            lambda: earliest_bucket_is_anomalous(some_window, SOME_THRESHOLDS)
        ) \
        .then(
            _the_answer_is(False)
        )


@pytest.mark.unit
def test_find_onset_ignores_a_minute_that_departs_alone() -> None:
    # An incident is a state the service is in, so it is still there the minute
    # after. A measurement that departs by itself has already recovered by then
    # - anchoring the whole investigation on it points every window at a minute
    # nothing happened in.
    some_steady_rate = 0.01
    dont_care_spike_rate = some_steady_rate * 30
    some_window = a_window_of(
        [some_steady_rate] * CALM_MINUTES
        + [dont_care_spike_rate]
        + [some_steady_rate] * 4
    )

    Scenario() \
        .given(
            some_window
        ) \
        .when(
            lambda: find_onset(some_window, SOME_THRESHOLDS)
        ) \
        .then(
            _no_onset_was_found()
        )


@pytest.mark.unit
def test_find_onset_reports_a_departure_that_is_still_going_when_the_window_ends() -> None:
    # An incident a minute old has not failed to persist - it has not yet been
    # given the chance. The window ending is not evidence of recovery.
    some_steady_rate = 0.01
    some_degradation_rate = some_steady_rate * 30
    some_window = a_window_of([some_steady_rate] * CALM_MINUTES + [some_degradation_rate])

    last_bucket = some_window[-1]

    Scenario() \
        .given(
            some_window
        ) \
        .when(
            lambda: find_onset(some_window, SOME_THRESHOLDS)
        ) \
        .then(
            _the_onset_is(last_bucket.bucket_id)
        )


@pytest.mark.unit
def test_find_onset_is_not_fooled_by_a_baseline_whose_quiet_minutes_read_alike() -> None:
    # A sampled error rate is quantised - a few hundred requests a minute
    # resolve it to half-percent steps - so most quiet minutes report the
    # identical figure and the average deviation between them is zero. A
    # threshold built on that average collapses onto the baseline, and every
    # ordinary minute reads as the incident starting. What this pins is that the
    # onset is the real incident and not the quantisation; that the quiet
    # minutes raise no onset of their own is a claim `find_onset`'s latest-run
    # rule hides here, and it has a test of its own below.
    some_quantised_low_rate = 0.005
    some_quantised_high_rate = 0.01
    some_incident_rate = 0.30
    some_window = a_window_of(
        [some_quantised_low_rate] * 7
        + [some_quantised_high_rate] * 10
        + [some_incident_rate] * 3
    )

    first_incident_bucket = some_window[17]

    Scenario() \
        .given(
            some_window
        ) \
        .when(
            lambda: find_onset(some_window, SOME_THRESHOLDS)
        ) \
        .then(
            _the_onset_is(first_incident_bucket.bucket_id)
        )


@pytest.mark.unit
def test_a_quiet_window_with_no_incident_behind_it_still_has_no_onset() -> None:
    # The half the test above cannot check. Its quiet stretch is followed by a
    # real 30% incident, and `find_onset` takes the *latest* qualifying run - so
    # a false onset among those quiet minutes is found, discarded and never seen.
    # Staged here with nothing behind it, where the only answer available is the
    # one about the quiet minutes themselves, and against a rate that is sampled
    # rather than written down: no two minutes of this window report the same
    # figure, which is what a service with nothing wrong with it looks like.
    some_quiet_window = a_quiet_window_of(90, seed=1)

    Scenario() \
        .given(
            some_quiet_window
        ) \
        .when(
            lambda: find_onset(some_quiet_window, SOME_THRESHOLDS)
        ) \
        .then(
            _no_onset_was_found()
        )


@pytest.mark.unit
def test_find_onset_dates_a_climb_from_where_it_began_rather_than_where_it_got_bad() -> None:
    # The case the window's lowest half by value cannot see: on a ramp, that
    # half *is* the early climb, so the baseline rises with the fault and the
    # spread derived from it is the slope. Measured against it alone, the first
    # departing minute here is #33 - twenty-three minutes after the climb
    # started, and most of the way to the peak. The window's own opening is
    # still calm, and that is what dates it.
    a_calm_stretch = [CALM_P95_MS] * 10
    a_continuous_climb = [CALM_P95_MS + 60 * (minute + 1) for minute in range(30)]
    some_window = a_window_of(
        [CALM_ERROR_RATE] * 40, a_calm_stretch + a_continuous_climb
    )

    a_minute_at_the_start_of_the_climb = some_window[14]

    Scenario() \
        .given(
            some_window
        ) \
        .when(
            lambda: find_onset(some_window, SOME_THRESHOLDS)
        ) \
        .then(
            _the_onset_is(a_minute_at_the_start_of_the_climb.bucket_id)
        )


@pytest.mark.unit
def test_a_window_filled_entirely_by_a_climb_has_no_visible_start() -> None:
    # A leak older than the window. Every minute is slightly worse than the one
    # before, no minute is a departure from its neighbours, and the baseline
    # taken from the window's opening is itself part of the climb. The honest
    # answer is the earliest minute there is, reported as the lower bound it is
    # - which is what makes the next round widen rather than believe this one.
    a_climb_with_no_calm_before_it = [CALM_P95_MS + 60 * minute for minute in range(60)]
    some_window = a_window_of(
        [CALM_ERROR_RATE] * 60, a_climb_with_no_calm_before_it
    )

    Scenario() \
        .given(
            some_window
        ) \
        .when(
            lambda: earliest_bucket_is_anomalous(some_window, SOME_THRESHOLDS)
        ) \
        .then(
            _the_answer_is(True)
        )


@pytest.mark.unit
def test_find_onset_catches_a_memory_departure_at_a_steady_error_rate_and_latency() -> None:
    # A leak's earliest and clearest signal is memory, and it runs ahead of the
    # latency and the errors it eventually causes. A detector reading only those
    # would date every leak at the minute it became a user-visible failure.
    a_calm_working_set = [CALM_MEMORY_BYTES] * 10
    a_working_set_three_times_the_baseline = [1536 * 1024**2] * 4
    some_window = a_window_of(
        [CALM_ERROR_RATE] * 14,
        memory_bytes=a_calm_working_set + a_working_set_three_times_the_baseline
    )

    first_bucket_using_too_much = some_window[10]

    Scenario() \
        .given(
            some_window
        ) \
        .when(
            lambda: find_onset(some_window, SOME_THRESHOLDS)
        ) \
        .then(
            _the_onset_is(first_bucket_using_too_much.bucket_id)
        )


@pytest.mark.unit
def test_find_onset_catches_a_median_departure_at_a_steady_tail() -> None:
    # A fault that removes a fast path - a cache gone, a warm pool lost -
    # leaves the tail describing what it already described, the slow requests,
    # while multiplying what a typical request costs. An incident of that shape
    # is invisible in the tail and plain in the median, so a detector reading
    # only the tail would not find it at all.
    a_calm_median = [CALM_P50_MS] * 10
    a_median_four_times_the_baseline = [CALM_P50_MS * 4] * 4
    some_window = a_window_of(
        [CALM_ERROR_RATE] * 14,
        p50_ms_values=a_calm_median + a_median_four_times_the_baseline
    )

    first_slow_minute = some_window[10]

    Scenario() \
        .given(
            some_window
        ) \
        .when(
            lambda: find_onset(some_window, SOME_THRESHOLDS)
        ) \
        .then(
            _the_onset_is(first_slow_minute.bucket_id)
        )


@pytest.mark.unit
def test_a_quiet_window_is_not_a_flat_one_and_still_has_no_onset() -> None:
    # Every other calm fixture here is a *constant*, which is the one case the
    # spread's floor was built for. A real service is quiet, not flat: this is
    # twelve minutes of an error rate sampled over two hundred requests at a 1%
    # baseline, so it moves in half-percent steps and nothing has happened.
    #
    # The bar it has to clear is derived from the window's lowest half by value,
    # whose own upper quantile is still below the middle of the series - so on a
    # quantised rate the measured spread was exactly zero, the bar sat a few
    # thousandths above the baseline, and ordinary minutes cleared it five times
    # over. These figures dated an onset at the second minute.
    some_quiet_minutes = [
        0.01, 0.015, 0.025, 0.01, 0.015, 0.005,
        0.01, 0.02, 0.01, 0.01, 0.01, 0.01
    ]
    a_window_in_which_nothing_happened = a_window_of(some_quiet_minutes)

    Scenario() \
        .given(a_window_in_which_nothing_happened) \
        .when(lambda: find_onset(a_window_in_which_nothing_happened, SOME_THRESHOLDS)) \
        .then(_no_onset_was_found())


@pytest.mark.unit
def test_a_signal_whose_worst_minute_lands_on_its_own_bar_is_not_an_incident() -> None:
    # The sibling below excludes a signal that never departed. This is that
    # signal one attounit of arithmetic away from not being excluded, and the
    # gap decides a mitigation.
    #
    # The error rate idles at half a percent and jitters in half-percent steps,
    # so its bar is the baseline plus three times two steps - 0.005 + 3 * 0.01 -
    # which in binary floating point is 0.034999999999999996. Its worst minute
    # reports seven failures in two hundred requests, which is 0.035. The series
    # therefore "departs" by 7e-18, escapes the exclusion written for signals
    # with no incident in them, and is handed a recovery ceiling its own worst
    # minute clears by the same nothing.
    #
    # That minute is the only one after the action, because the fixture freezes
    # its window one settling minute past a revert - so the tolerance for a lone
    # departed minute cannot apply, and polling cannot help a frozen window.
    # Measured: it refuted a flag revert that had worked, and the walk then
    # escalated an incident it had already ended.
    an_error_rate_that_only_jitters = [
        0.005, 0.005, 0.005, 0.01, 0.005, 0.01, 0.005, 0.01,
        0.01, 0.015, 0.015, 0.015, 0.01, 0.005, 0.01, 7 / 200, 0.01
    ]
    a_tail_that_departed_and_came_back = (
        [CALM_P99_MS] * 8 + [CALM_P99_MS * 10] * 4 + [CALM_P99_MS] * 5
    )
    some_window = a_window_of(
        an_error_rate_that_only_jitters,
        p99_ms_values=a_tail_that_departed_and_came_back
    )

    the_first_minute_since_the_revert = some_window[-2].bucket_id

    Scenario() \
        .given(some_window) \
        .when(lambda: has_recovered_since(
                some_window, the_first_minute_since_the_revert, SOME_THRESHOLDS
        )) \
        .then(_the_answer_is(True))


@pytest.mark.unit
def test_a_signal_that_never_departed_does_not_hold_recovery_open() -> None:
    # The median departs and comes back; the error rate only jitters inside its
    # own calm range the whole time. Recovery has to be judged on the signal
    # that was the incident, because the one that never moved has no incident
    # level to have fallen back from - and judging on it anyway refused a
    # configuration rollback that had genuinely ended an incident, in the one
    # scenario whose error rate never moves at all.
    an_error_rate_that_only_jitters = [
        0.005, 0.005, 0.005, 0.015, 0.01, 0.015, 0.015, 0.025,
        0.01, 0.025, 0.005, 0.025, 0.01, 0.02, 0.02, 0.025
    ]
    a_median_that_departed_and_came_back = [
        26, 25, 27, 26, 25, 26, 24, 27, 190, 189, 191, 188, 26, 25, 27, 26
    ]
    some_window = a_window_of(
        an_error_rate_that_only_jitters,
        p50_ms_values=a_median_that_departed_and_came_back
    )

    the_minute_the_median_came_back = some_window[12].bucket_id

    Scenario() \
        .given(some_window) \
        .when(lambda: has_recovered_since(
            some_window, the_minute_the_median_came_back, SOME_THRESHOLDS
        )) \
        .then(_the_answer_is(True))


@pytest.mark.unit
def test_one_noisy_minute_does_not_hold_recovery_open_for_the_whole_window() -> None:
    # The third of these siblings, and the case the other two let through. The
    # error rate jitters in half-percent steps the whole way and never departs;
    # one minute early in the window catches eight failures in two hundred
    # requests where the shop ordinarily catches one to four. That single sample
    # lifts the series' maximum past the margin the exclusion allows, so a signal
    # with no incident in it is admitted as one that departed - and recovery is
    # then judged against a ceiling the ordinary jitter sits above.
    #
    # The window is long because a six-hour one is: the shop serves 360 minutes,
    # so it holds 360 chances to contain a minute like this, and the refusal
    # stands for as long as that minute takes to slide out of the window. Every
    # rollback in those six hours is refused. Measured against the fixture at 21%
    # of clock positions, on the scenario whose error rate never moves at all.
    a_jitter = [0.005, 0.01, 0.005, 0.015, 0.01, 0.005, 0.02, 0.01, 0.015, 0.005]
    a_minute_that_caught_eight_failures = 8 / 200
    an_error_rate_that_only_jitters = (
        a_jitter * 2
        + [a_minute_that_caught_eight_failures]
        + a_jitter[1:]
        + a_jitter
        + [0.01] * 10
    )
    a_latency_that_departed_and_came_back = (
        [CALM_P95_MS] * 40 + [CALM_P95_MS * 10] * 4 + [CALM_P95_MS] * 6
    )
    some_window = a_window_of(
        an_error_rate_that_only_jitters,
        p95_ms_values=a_latency_that_departed_and_came_back
    )

    the_minute_the_latency_came_back = some_window[44].bucket_id

    Scenario() \
        .given(some_window) \
        .when(lambda: has_recovered_since(
            some_window, the_minute_the_latency_came_back, SOME_THRESHOLDS
        )) \
        .then(_the_answer_is(True))


@pytest.mark.unit
def test_a_spike_above_the_incidents_plateau_does_not_confirm_recovery() -> None:
    # The mirror of the three siblings above, at the other half of the same
    # function. There a maximum decided *whether* a series had departed; here it
    # decides how far it has to have fallen back, and the ceiling is read a fifth
    # of the way down from the worst minute - so one minute far above an
    # otherwise flat plateau lifts that bar clear of the plateau itself, and a
    # service still sitting at the incident's own level reads as recovered.
    #
    # Measured on this window: the departure bar is 258.70 and the worst minute
    # 9800, so the ceiling lands at 2166.96 and the only minute above it is the
    # spike - which is before the action. Every plateau minute after the action
    # is therefore clear, and the verdict is a false CONFIRMED. That is the worse
    # direction of the two: it closes the incident and stops, where the sibling
    # defect refused a mitigation that had worked and could be waited out. Read
    # off the departed minutes instead, the ceiling is 407.66 and the plateau
    # sits above it.
    #
    # §16 says both ends of the rule come from the window - "the incident from
    # the minutes that departed". Plural, and a median of them for the reason the
    # baseline is a median: one extreme minute moves a mean and moves a median
    # not at all. Strictly this makes recovery harder to claim on a spiky
    # incident and identical on a plateau.
    a_calm_stretch = [
        198, 201, 204, 199, 202, 196, 203, 200, 197, 202, 199, 201, 203, 198
    ]
    a_plateau = [1000, 1010, 995, 1005]
    a_minute_far_above_it = [9800]
    the_plateau_it_stayed_at = [1002, 998, 1006]
    a_p95_that_spiked_above_its_plateau = (
        a_calm_stretch + a_plateau + a_minute_far_above_it + the_plateau_it_stayed_at
    )
    some_window = a_window_of(
        [CALM_ERROR_RATE] * len(a_p95_that_spiked_above_its_plateau),
        p95_ms_values=a_p95_that_spiked_above_its_plateau
    )

    the_first_minute_since_the_action = some_window[19].bucket_id

    Scenario() \
        .given(some_window) \
        .when(lambda: has_recovered_since(
            some_window, the_first_minute_since_the_action, SOME_THRESHOLDS
        )) \
        .then(_the_answer_is(False))


@pytest.mark.unit
def test_a_verdict_does_not_turn_on_how_long_the_poll_waited() -> None:
    # Green when it was written, and deliberately so: this pins a property the
    # change that read the level off the departed minutes could easily have
    # broken, and it went red under the first design that did. Red-first is for
    # behaviour that does not exist yet; a guard's job starts when somebody
    # reaches for the wrong design.
    #
    # The service sheds most of its rise and holds still. Nothing about it
    # changes from the action onwards, so every poll has to answer the same way -
    # and the window Mitigation reads only grows, so "the same way" is the whole
    # claim. Read off the whole window the answer was measured as True at one,
    # two and three minutes held, False at five and eight, and True again at
    # thirteen and twenty-one: first the held minutes join the departed set and
    # pull the level down to their own, then they outnumber the incident in the
    # window's quiet half and lift the departure bar above the plateau. Neither
    # is a fact about the service, and a verdict that is not a fact about the
    # service is decided by whatever the timeout allowed.
    #
    # Asked at seven lengths rather than one, and asserted together, because what
    # is being claimed is that they agree - separately, each is satisfied by a
    # function that always answers True.
    a_calm_stretch = [
        198, 201, 204, 199, 202, 196, 203, 200, 197, 202, 199, 201, 203, 198
    ]
    a_plateau = [1000, 1010, 995, 1005]
    the_level_it_fell_to = [
        350, 360, 345, 355, 342, 358, 347, 353, 351, 349,
        344, 356, 348, 352, 346, 354, 343, 357, 350, 345, 355
    ]
    the_action_lands_at = len(a_calm_stretch) + len(a_plateau)

    def polled_after(minutes: int) -> bool:
        some_window = a_window_of(
            [CALM_ERROR_RATE] * (the_action_lands_at + minutes),
            p95_ms_values=a_calm_stretch + a_plateau + the_level_it_fell_to[:minutes]
        )

        return has_recovered_since(
            some_window, some_window[the_action_lands_at].bucket_id, SOME_THRESHOLDS
        )

    Scenario() \
        .given(the_action_lands_at) \
        .when(lambda: {
            minutes: polled_after(minutes) for minutes in (1, 2, 3, 5, 8, 13, 21)
        }) \
        .then(_every_poll_agreed_it_had_recovered())


@pytest.mark.unit
def test_a_series_that_only_broke_after_the_action_is_judged_against_itself() -> None:
    # The level is read from the minutes before the action, and this is the
    # window where there are none: the service is well until the moment it is
    # acted on, and every departed minute it has is after. Not a corner - the
    # window Mitigation reads grows from the action, so at the first poll the
    # history is always the shortest it will ever be, and a flapping capacity
    # asked from every minute in turn puts the action at the incident's first
    # departed minute directly.
    #
    # So the level falls back to every departed minute in the window, which is
    # the answer rather than a degenerate one: something here did depart, and the
    # judgement should be against it. The two alternatives are both worse than a
    # wrong number. Excluding the series into `inf` would judge a signal that is
    # departed *now* against no level at all and confirm the mitigation that
    # broke it. Taking the median of nothing raises, which is what this did
    # before the fallback existed.
    a_calm_stretch = [
        198, 201, 204, 199, 202, 196, 203, 200, 197, 202, 199, 201, 203, 198
    ]
    a_plateau_that_began_at_the_action = [1000, 1010, 995, 1005, 1000, 1008]
    a_p95_that_only_broke_afterwards = (
        a_calm_stretch + a_plateau_that_began_at_the_action
    )
    some_window = a_window_of(
        [CALM_ERROR_RATE] * len(a_p95_that_only_broke_afterwards),
        p95_ms_values=a_p95_that_only_broke_afterwards
    )

    the_action = some_window[len(a_calm_stretch)].bucket_id

    Scenario() \
        .given(some_window) \
        .when(lambda: has_recovered_since(some_window, the_action, SOME_THRESHOLDS)) \
        .then(_the_answer_is(False))


@pytest.mark.unit
def test_find_onset_catches_a_tail_departure_at_a_steady_median_and_p95() -> None:
    # A fault reaching a few requests in a hundred is below the 95th percentile
    # by arithmetic, fails nothing and allocates nothing - so every other signal
    # is flat across its onset by construction. A detector reading only those
    # four would find no onset at all, rather than a late one.
    a_calm_tail = [CALM_P99_MS] * 10
    a_tail_five_times_the_baseline = [CALM_P99_MS * 5] * 4
    some_window = a_window_of(
        [CALM_ERROR_RATE] * 14,
        p99_ms_values=a_calm_tail + a_tail_five_times_the_baseline
    )

    first_slow_minute = some_window[10]

    Scenario() \
        .given(
            some_window
        ) \
        .when(
            lambda: find_onset(some_window, SOME_THRESHOLDS)
        ) \
        .then(
            _the_onset_is(first_slow_minute.bucket_id)
        )


@pytest.mark.unit
def test_recovery_is_judged_on_the_tail_too() -> None:
    # An incident found in the tail alone can only be confirmed over by the
    # tail coming back down. Asking a p95 that never moved whether it has
    # returned to its baseline confirms a mitigation the instant it is taken.
    a_calm_tail = [CALM_P99_MS] * CALM_MINUTES
    a_tail_five_times_the_baseline = [CALM_P99_MS * 5] * 3
    a_tail_back_where_it_was = [CALM_P99_MS] * 4
    some_window = a_window_of(
        [CALM_ERROR_RATE] * (CALM_MINUTES + 7),
        p99_ms_values=(
            a_calm_tail + a_tail_five_times_the_baseline + a_tail_back_where_it_was
        )
    )

    first_calm_minute_after_it = some_window[CALM_MINUTES + 3]

    Scenario() \
        .given(some_window) \
        .when(lambda: find_recovery(some_window, SOME_THRESHOLDS)) \
        .then(_the_recovery_is(first_calm_minute_after_it.bucket_id))


@pytest.mark.unit
def test_a_window_that_returned_to_baseline_has_recovered() -> None:
    # The mitigation side of the same judgement: not "when did this start" but
    # "is it still going", asked of the minutes after an action was taken.
    some_steady_rate = 0.01
    some_degradation_rate = some_steady_rate * 30
    some_window = a_window_of(
        [some_steady_rate] * CALM_MINUTES
        + [some_degradation_rate, some_degradation_rate]
        + [some_steady_rate] * 3
    )

    the_minute_after_the_action = some_window[CALM_MINUTES + 2].bucket_id

    Scenario() \
        .given(
            some_window
        ) \
        .when(
            lambda: has_recovered_since(some_window, the_minute_after_the_action, SOME_THRESHOLDS)
        ) \
        .then(
            _the_answer_is(True)
        )


@pytest.mark.unit
def test_a_window_still_departing_has_not_recovered() -> None:
    some_steady_rate = 0.01
    some_degradation_rate = some_steady_rate * 30
    some_window = a_window_of(
        [some_steady_rate] * CALM_MINUTES + [some_degradation_rate] * 4
    )

    the_minute_after_the_action = some_window[CALM_MINUTES + 1].bucket_id

    Scenario() \
        .given(
            some_window
        ) \
        .when(
            lambda: has_recovered_since(some_window, the_minute_after_the_action, SOME_THRESHOLDS)
        ) \
        .then(
            _the_answer_is(False)
        )


@pytest.mark.unit
def test_recovery_is_not_claimed_before_a_minute_has_been_measured() -> None:
    # No minute has been measured since the action, so there is no evidence of
    # recovery - which is not the same as evidence of recovery. Claiming it here
    # would confirm every mitigation the instant it was taken.
    some_steady_rate = 0.01
    some_degradation_rate = some_steady_rate * 30
    some_window = a_window_of(
        [some_steady_rate] * CALM_MINUTES + [some_degradation_rate] * 2
    )

    a_minute_after_the_window_ends = _the_minute_after(some_window[-1].bucket_id)

    Scenario() \
        .given(
            some_window
        ) \
        .when(
            lambda: has_recovered_since(
                some_window, a_minute_after_the_window_ends, SOME_THRESHOLDS
            )
        ) \
        .then(
            _the_answer_is(False)
        )


@pytest.mark.unit
def test_one_noisy_minute_after_a_recovery_does_not_take_it_back() -> None:
    # The allowance the module already makes, and which must survive: a lone
    # departed minute is not a relapse, for the reason a lone departed minute is
    # not an onset. The window Mitigation reads only grows, so a minute that
    # denied the verdict would deny it for as long as anybody waited.
    some_steady_rate = 0.01
    some_degradation_rate = some_steady_rate * 30
    some_window = a_window_of(
        [some_steady_rate] * CALM_MINUTES
        + [some_degradation_rate, some_degradation_rate]
        + [some_steady_rate, some_steady_rate,
           some_degradation_rate,
           some_steady_rate]
    )

    the_first_minute_after_the_action = some_window[CALM_MINUTES + 2].bucket_id

    Scenario() \
        .given(some_window) \
        .when(
            lambda: has_recovered_since(
                some_window, the_first_minute_after_the_action, SOME_THRESHOLDS
            )
        ) \
        .then(_the_answer_is(True))


@pytest.mark.unit
def test_a_service_clear_one_minute_in_three_has_recovered_from_none_of_them() -> None:
    # A capacity that will not settle, which is the shape that found all of this:
    # two minutes at the incident's level, one below it, repeating. Every minute
    # of it is a moment somebody could have acted at, and none of them is a
    # recovery - the service is not better, it is between cycles. Asked from
    # every minute rather than from one, because which minute an action lands on
    # is not something a walk chooses.
    some_steady_rate = 0.01
    some_degradation_rate = some_steady_rate * 30
    a_flapping_stretch = [
        some_degradation_rate, some_degradation_rate, some_steady_rate
    ] * 4
    some_window = a_window_of(
        [some_steady_rate] * CALM_MINUTES + a_flapping_stretch
    )

    Scenario() \
        .given(some_window) \
        .when(lambda: {
            bucket.bucket_id: has_recovered_since(
                some_window, bucket.bucket_id, SOME_THRESHOLDS
            )
            for bucket in some_window[CALM_MINUTES:]
        }) \
        .then(_no_minute_read_as_a_recovery())


@pytest.mark.unit
def test_a_step_incident_is_recovered_from_on_one_clear_minute() -> None:
    # How long a recovery has to hold for is read off the incident rather than
    # set by a number. Nothing in this window says the service bounces: it
    # departed, it came back, and it never once returned. One minute below the
    # incident's own level is then the whole of the available evidence, and
    # waiting a second one buys nothing - it spends a minute of the verification
    # window on a question already answered.
    some_steady_rate = 0.01
    some_degradation_rate = some_steady_rate * 30
    some_window = a_window_of(
        [some_steady_rate] * CALM_MINUTES
        + [some_degradation_rate, some_degradation_rate]
        + [some_steady_rate]
    )

    the_one_minute_measured_since = some_window[-1].bucket_id

    Scenario() \
        .given(some_window) \
        .when(
            lambda: has_recovered_since(
                some_window, the_one_minute_measured_since, SOME_THRESHOLDS
            )
        ) \
        .then(_the_answer_is(True))


@pytest.mark.unit
def test_a_cycle_of_four_clear_minutes_is_not_recovered_from_in_four() -> None:
    # The case that defeats any fixed number, and so the reason the number is
    # measured. This service is clear for four minutes of every six, so a rule
    # asking for `persistence_minutes` - or for any figure read off a cycle of two
    # bad minutes to one good - confirms a mitigation in the middle of a lull the
    # incident has already come back from twice.
    #
    # Four clear minutes is exactly what this incident recovered from before, so
    # four is the one length that proves nothing. Asked from the start of the last
    # lull, which is the most favourable minute the window has.
    some_steady_rate = 0.01
    some_degradation_rate = some_steady_rate * 30
    a_cycle = [some_degradation_rate] * 2 + [some_steady_rate] * 4
    some_window = a_window_of([some_steady_rate] * CALM_MINUTES + a_cycle * 3)

    the_start_of_the_last_lull = some_window[-4].bucket_id

    Scenario() \
        .given(some_window) \
        .when(
            lambda: has_recovered_since(
                some_window, the_start_of_the_last_lull, SOME_THRESHOLDS
            )
        ) \
        .then(_the_answer_is(False))


@pytest.mark.unit
def test_a_single_noisy_minute_after_the_action_is_not_a_relapse() -> None:
    # The same rule `find_onset` already applies, asked of the other end: a lone
    # departed minute is sampling noise that had already recovered by the next
    # one. What this stages is the jitter with clean minutes after it, which is
    # the run-length rule alone; a lone minute landing *last* is the arrangement
    # a growing mitigation window actually hits, and it has a test of its own
    # below.
    some_steady_rate = 0.01
    some_degradation_rate = some_steady_rate * 30
    some_jittery_p95 = int(CALM_P95_MS * 1.4)
    some_window = a_window_of(
        [some_steady_rate] * CALM_MINUTES
        + [some_degradation_rate, some_degradation_rate]
        + [some_steady_rate] * 4,
        [CALM_P95_MS] * (CALM_MINUTES + 2)
        + [CALM_P95_MS, some_jittery_p95, CALM_P95_MS, CALM_P95_MS]
    )

    the_minute_after_the_action = some_window[CALM_MINUTES + 2].bucket_id

    Scenario() \
        .given(
            some_window
        ) \
        .when(
            lambda: has_recovered_since(some_window, the_minute_after_the_action, SOME_THRESHOLDS)
        ) \
        .then(
            _the_answer_is(True)
        )


@pytest.mark.unit
def test_a_departure_that_holds_after_the_action_is_still_a_relapse() -> None:
    # The other side of the same rule, and what stops it being a licence to
    # ignore evidence: a service that departs and stays departed has not
    # recovered, however briefly it looked as though it had.
    some_steady_rate = 0.01
    some_degradation_rate = some_steady_rate * 30
    some_window = a_window_of(
        [some_steady_rate] * CALM_MINUTES
        + [some_degradation_rate, some_degradation_rate]
        + [some_steady_rate, some_degradation_rate, some_degradation_rate]
    )

    the_minute_after_the_action = some_window[CALM_MINUTES + 2].bucket_id

    Scenario() \
        .given(
            some_window
        ) \
        .when(
            lambda: has_recovered_since(some_window, the_minute_after_the_action, SOME_THRESHOLDS)
        ) \
        .then(
            _the_answer_is(False)
        )


@pytest.mark.unit
def test_a_noisy_minute_landing_last_is_not_a_relapse_either() -> None:
    # The arrangement the test above states and cannot reach. Its jittery minute
    # has two clean ones after it, and a run of departed minutes that ends inside
    # the window is judged on its length alone. A run still going when the window
    # ends is not - it counts however short it is, which is right for an onset,
    # where an incident a minute old has yet to be given the chance to persist,
    # and inverted here: the window Mitigation reads is the window it has just
    # polled, so its last minute is always the freshest sample and one noisy
    # sample denies the verdict.
    some_incident_rate = 0.30
    a_quiet_window = a_quiet_window_of(12, seed=3)
    an_incident = with_the_error_rate_raised(
        a_quiet_window, to=some_incident_rate, over=range(4, 7)
    )
    some_window = with_the_error_rate_raised(
        an_incident, to=some_incident_rate, over=range(11, 12)
    )

    the_minute_after_the_action = some_window[7].bucket_id

    Scenario() \
        .given(
            some_window
        ) \
        .when(
            lambda: has_recovered_since(some_window, the_minute_after_the_action, SOME_THRESHOLDS)
        ) \
        .then(
            _the_answer_is(True)
        )


@pytest.mark.unit
def test_a_minute_that_has_fallen_back_from_the_incident_is_recovery() -> None:
    # The case that refutes correct mitigations in the real stack: a service
    # that failed a third of its requests and now fails two in a hundred has
    # recovered by any reading. Judging it against the baseline's own noise
    # instead - which is where an onset is judged from - demands a return to
    # indistinguishable-from-quiet, and a service still shedding the last of an
    # incident never gets there inside the time it is given.
    some_steady_rate = 0.005
    some_incident_rate = some_steady_rate * 64
    a_rate_most_of_the_way_back = some_steady_rate * 4
    some_window = a_window_of(
        [some_steady_rate] * CALM_MINUTES
        + [some_incident_rate, some_incident_rate]
        + [a_rate_most_of_the_way_back, a_rate_most_of_the_way_back]
    )

    the_minute_after_the_action = some_window[CALM_MINUTES + 2].bucket_id

    Scenario() \
        .given(
            some_window
        ) \
        .when(
            lambda: has_recovered_since(some_window, the_minute_after_the_action, SOME_THRESHOLDS)
        ) \
        .then(
            _the_answer_is(True)
        )


@pytest.mark.unit
def test_a_minute_still_near_the_incidents_own_level_is_not_recovery() -> None:
    # The other side of it, and what stops the rule being "anything below the
    # peak". A service that has come down by half is still having the incident,
    # and calling that recovered would confirm a mitigation on the strength of
    # an outage easing.
    some_steady_rate = 0.005
    some_incident_rate = some_steady_rate * 64
    a_rate_barely_off_the_incident = some_incident_rate / 2
    some_window = a_window_of(
        [some_steady_rate] * CALM_MINUTES
        + [some_incident_rate, some_incident_rate]
        + [a_rate_barely_off_the_incident]
    )

    the_minute_after_the_action = some_window[CALM_MINUTES + 2].bucket_id

    Scenario() \
        .given(
            some_window
        ) \
        .when(
            lambda: has_recovered_since(some_window, the_minute_after_the_action, SOME_THRESHOLDS)
        ) \
        .then(
            _the_answer_is(False)
        )


@pytest.mark.unit
def test_find_onset_ignores_an_earlier_departure_the_service_recovered_from() -> None:
    # The window is six hours wide and a quiet minute still wobbles, so a brief
    # departure hours before the alert is ordinary rather than the incident.
    # Anchoring on the first one dates the incident from a minute the service
    # was fine by, and every window derived from that onset - the logs, the
    # changes, the money - then covers mostly healthy time.
    some_steady_rate = 0.01
    dont_care_earlier_rate = some_steady_rate * 30
    some_degradation_rate = some_steady_rate * 30
    some_window = a_window_of(
        [some_steady_rate] * CALM_MINUTES
        + [dont_care_earlier_rate] * 2
        + [some_steady_rate] * CALM_MINUTES
        + [some_degradation_rate] * 3
    )

    first_bucket_of_the_departure_still_going = some_window[2 * CALM_MINUTES + 2]

    Scenario() \
        .given(
            some_window
        ) \
        .when(
            lambda: find_onset(some_window, SOME_THRESHOLDS)
        ) \
        .then(
            _the_onset_is(first_bucket_of_the_departure_still_going.bucket_id)
        )


@pytest.mark.unit
def test_find_recovery_reports_the_minute_the_incident_fell_away_and_stayed_away() -> None:
    # The moment every measured window has to end at. Recovery is a fact about
    # the service; when the walk closed the incident is a fact about Argus, and
    # a figure bounded by the second describes neither.
    some_steady_rate = 0.01
    some_window = a_window_of(
        [some_steady_rate] * CALM_MINUTES
        + [some_steady_rate * 9, some_steady_rate * 18, some_steady_rate * 18]
        + [some_steady_rate] * 4
    )

    first_calm_minute_after_it = some_window[CALM_MINUTES + 3]

    Scenario() \
        .given(some_window) \
        .when(lambda: find_recovery(some_window, SOME_THRESHOLDS)) \
        .then(_the_recovery_is(first_calm_minute_after_it.bucket_id))


@pytest.mark.unit
def test_a_signal_departing_every_other_minute_has_no_recovery_to_report() -> None:
    # Where the incident began is asked of the departure bar, and the bar alone
    # does not say whether anything persisted. The vector of minutes at the
    # incident's level used to answer both at once - a series with no persisted
    # run is excluded from the judgement entirely, so "was anything ever at the
    # incident's level" answered "did anything last" as a side effect - and
    # reading the bar directly leaves that behind unless it is asked for.
    #
    # A series alternating departed and clear is the shape that catches it. No
    # run reaches two minutes, so there is no incident here to recover from; take
    # the first departed minute as the start and the clear minute after it looks
    # like a recovery, with a level drawn from the single sample that preceded it.
    # Measured without the persistence requirement: a recovery reported at 11:15,
    # on a service that goes on departing for nine more minutes.
    #
    # The existing cycle case cannot catch this because its runs are exactly as
    # long as persistence asks for, so it is satisfied either way - which is why
    # these runs are one minute and not two.
    a_calm_stretch = [
        198, 201, 204, 199, 202, 196, 203, 200, 197, 202, 199, 201, 203, 198
    ]
    a_departure_that_never_lasts = [
        1000, 205, 1010, 203, 995, 206, 1005, 204, 1000, 205
    ]
    a_p95_that_never_stays_departed = a_calm_stretch + a_departure_that_never_lasts
    some_window = a_window_of(
        [CALM_ERROR_RATE] * len(a_p95_that_never_stays_departed),
        p95_ms_values=a_p95_that_never_stays_departed
    )

    Scenario() \
        .given(some_window) \
        .when(lambda: find_recovery(some_window, SOME_THRESHOLDS)) \
        .then(_it_never_recovered())


@pytest.mark.unit
def test_an_incident_that_half_subsided_is_recovered_from_where_it_fell() -> None:
    # The level comes from the minutes before the moment being judged, and this
    # is the case that says so. A service sheds most of a rise and holds there:
    # 1000ms against a baseline near 200 and a departure bar of 260, falling to
    # 350 and staying. 350 is 88% of the way back down and the rule asks for 80%,
    # so the incident ended where it fell - and it stays ended however long the
    # service sits there, because how far it had to fall is a fact about the
    # minutes before it fell rather than about the ones after.
    #
    # Read off the whole window instead, those held minutes are above the
    # departure bar, so they join the departed set, outnumber the four that were
    # the incident and drag the level to their own. The ceiling follows them down
    # and the service reads as never having recovered - measured as `None` on
    # this window. It is the same moving goalpost the mitigation end is bounded
    # at the action to avoid, arriving at the end that has no action to be
    # bounded at.
    #
    # `find_onset` still dates a departure in these minutes, and that is not a
    # contradiction: §16 makes the bar hysteretic on purpose, because demanding a
    # return to indistinguishable-from-quiet would refuse to recognise a service
    # still shedding the last of an outage.
    a_calm_stretch = [
        198, 201, 204, 199, 202, 196, 203, 200, 197, 202, 199, 201, 203, 198
    ]
    a_plateau = [1000, 1010, 995, 1005]
    the_level_it_fell_to_and_held = [350, 360, 345, 355, 342, 358, 347, 353]
    a_p95_that_shed_most_of_its_rise = (
        a_calm_stretch + a_plateau + the_level_it_fell_to_and_held
    )
    some_window = a_window_of(
        [CALM_ERROR_RATE] * len(a_p95_that_shed_most_of_its_rise),
        p95_ms_values=a_p95_that_shed_most_of_its_rise
    )

    the_minute_it_fell = some_window[18].bucket_id

    Scenario() \
        .given(some_window) \
        .when(lambda: find_recovery(some_window, SOME_THRESHOLDS)) \
        .then(_the_recovery_is(the_minute_it_fell))


@pytest.mark.unit
def test_a_window_still_at_the_incidents_level_when_it_ends_never_recovered() -> None:
    # Not a recovery at the last minute read, which is what dating it from the
    # end of the window would amount to. The service was still broken when the
    # metrics ran out, and every figure measured over this window is a lower
    # bound that has to say so.
    some_steady_rate = 0.01
    some_window = a_window_of(
        [some_steady_rate] * CALM_MINUTES
        + [some_steady_rate * 9, some_steady_rate * 18, some_steady_rate * 18]
    )

    Scenario() \
        .given(some_window) \
        .when(lambda: find_recovery(some_window, SOME_THRESHOLDS)) \
        .then(_it_never_recovered())


@pytest.mark.unit
def test_a_window_with_no_incident_in_it_has_no_recovery_to_report() -> None:
    # Every minute here is below the incident's level, and the first of them
    # is not a recovery - there was nothing to recover from. A rule reading
    # this window as recovered at its opening would date the end of an
    # incident before its beginning.
    some_steady_rate = 0.01
    some_window = a_window_of([some_steady_rate] * (CALM_MINUTES + 3))

    Scenario() \
        .given(some_window) \
        .when(lambda: find_recovery(some_window, SOME_THRESHOLDS)) \
        .then(_it_never_recovered())


@pytest.mark.unit
def test_a_single_minute_falling_back_mid_incident_is_not_the_recovery() -> None:
    # The persistence rule `find_onset` anchors on, applied at the other end.
    # An incident is a state the service stays in, so one minute dipping below
    # the incident's level and climbing straight back is noise - and dating
    # recovery there would end the incident in the middle of it, with the
    # worst minutes counted as aftermath.
    some_steady_rate = 0.01
    a_minute_that_dipped = some_steady_rate * 3
    some_window = a_window_of(
        [some_steady_rate] * CALM_MINUTES
        + [some_steady_rate * 18, some_steady_rate * 18,
           a_minute_that_dipped,
           some_steady_rate * 18, some_steady_rate * 18]
        + [some_steady_rate] * 4
    )

    first_calm_minute_after_it = some_window[CALM_MINUTES + 5]

    Scenario() \
        .given(some_window) \
        .when(lambda: find_recovery(some_window, SOME_THRESHOLDS)) \
        .then(_the_recovery_is(first_calm_minute_after_it.bucket_id))


@pytest.mark.unit
def test_a_running_cycle_has_no_recovery_to_report() -> None:
    # The postmortem's bound, and the reason the measured rule has to reach this
    # end too. Every figure an incident is described by is averaged over the
    # window recovery closes, so a recovery dated inside a lull describes a
    # service that was mostly well - which is how a rise in errors once came to be
    # reported as negative. A cycle that is still running has not recovered at any
    # of its lulls, and the honest answer is that this window does not contain the
    # end of it.
    some_steady_rate = 0.01
    some_degradation_rate = some_steady_rate * 30
    a_cycle = [some_degradation_rate] * 2 + [some_steady_rate] * 4
    some_window = a_window_of([some_steady_rate] * CALM_MINUTES + a_cycle * 3)

    Scenario() \
        .given(some_window) \
        .when(lambda: find_recovery(some_window, SOME_THRESHOLDS)) \
        .then(_it_never_recovered())


@pytest.mark.unit
def test_recovery_is_dated_after_a_cycle_stops_and_not_inside_a_lull() -> None:
    # The other side of it: the same cycle, and then something that actually
    # stopped it. The minute recovery is dated at is the first of the run that
    # outlasted every lull before it - not the first of the two four-minute lulls
    # that look identical up to their fifth minute and do not have one.
    some_steady_rate = 0.01
    some_degradation_rate = some_steady_rate * 30
    a_cycle = [some_degradation_rate] * 2 + [some_steady_rate] * 4
    a_last_departure = [some_degradation_rate] * 2
    it_settled = [some_steady_rate] * 8
    some_window = a_window_of(
        [some_steady_rate] * CALM_MINUTES + a_cycle * 2 + a_last_departure + it_settled
    )

    the_minute_the_cycle_stopped = some_window[-len(it_settled)]

    Scenario() \
        .given(some_window) \
        .when(lambda: find_recovery(some_window, SOME_THRESHOLDS)) \
        .then(_the_recovery_is(the_minute_the_cycle_stopped.bucket_id))


@pytest.mark.unit
def test_a_busy_stretch_with_nothing_else_moved_is_no_onset() -> None:
    # Utilisation tracks traffic, and traffic has a shape. A departure test over
    # this series would date the onset at the minute the load arrived - minutes
    # before anything was wrong, and in a busy stretch where nothing ever was.
    a_quiet_window = a_quiet_window_of(90, seed=1)
    some_busy_window = with_the_cpu_saturated(a_quiet_window, over=range(40, 90))

    Scenario() \
        .given(some_busy_window) \
        .when(lambda: find_onset(some_busy_window, SOME_THRESHOLDS)) \
        .then(_no_onset_was_found())


@pytest.mark.unit
def test_a_saturated_service_is_dated_from_the_series_that_are_judged() -> None:
    # The minute customers were hurt, not the minute the resource ran out. The
    # two differ by however long the service absorbed the load, and only the
    # first is an incident.
    some_incident_rate = 0.30
    a_quiet_window = a_quiet_window_of(90, seed=1)
    a_saturated_window = with_the_cpu_saturated(a_quiet_window, over=range(40, 90))
    some_window = with_the_error_rate_raised(
        a_saturated_window, to=some_incident_rate, over=range(45, 90)
    )

    first_minute_that_failed = some_window[45]

    Scenario() \
        .given(some_window) \
        .when(lambda: find_onset(some_window, SOME_THRESHOLDS)) \
        .then(_the_onset_is(first_minute_that_failed.bucket_id))


@pytest.mark.unit
def test_recovery_is_not_held_open_by_utilisation_that_stayed_high() -> None:
    # A scaled-out service can be well while its cores are still busy, and a
    # recovery rule reading this series would refuse to call that recovered.
    some_incident_rate = 0.30
    a_quiet_window = a_quiet_window_of(90, seed=1)
    a_saturated_window = with_the_cpu_saturated(a_quiet_window, over=range(0, 90))
    some_window = with_the_error_rate_raised(
        a_saturated_window, to=some_incident_rate, over=range(40, 60)
    )

    first_calm_minute_after_it = some_window[60]

    Scenario() \
        .given(some_window) \
        .when(lambda: find_recovery(some_window, SOME_THRESHOLDS)) \
        .then(_the_recovery_is(first_calm_minute_after_it.bucket_id))


@pytest.mark.unit
def test_a_window_whose_minutes_stop_before_the_moment_has_no_reading_since_it() -> None:
    # The state the recovery question cannot express. A window whose minutes stop
    # before the moment asked about says nothing about what happened after it -
    # not that the service is still bad, and not that it is well. Nobody looked.
    some_window = a_window_of([CALM_ERROR_RATE] * CALM_MINUTES)
    a_minute_after_the_window_ends = _the_minute_after(some_window[-1].bucket_id)

    Scenario() \
        .given(
            some_window
        ) \
        .when(
            lambda: has_a_reading_since(some_window, a_minute_after_the_window_ends)
        ) \
        .then(
            _the_answer_is(False)
        )


@pytest.mark.unit
def test_a_window_reaching_the_moment_has_a_reading_since_it() -> None:
    # Inclusive of the minute itself, matching the recovery question asked of the
    # same window: a reading taken *at* the minute asked about is a reading of it.
    some_window = a_window_of([CALM_ERROR_RATE] * CALM_MINUTES)

    Scenario() \
        .given(
            some_window
        ) \
        .when(
            lambda: has_a_reading_since(some_window, some_window[-1].bucket_id)
        ) \
        .then(
            _the_answer_is(True)
        )


@pytest.mark.unit
def test_a_window_with_no_minutes_in_it_has_no_reading_since_anything() -> None:
    # The degenerate case, and the one a monitoring blind spot reaches: nothing
    # was published, so there is no minute to be before or after anything.
    dont_care_minute = to_iso_minute(datetime(2026, 1, 1, tzinfo=UTC))
    no_window: list[MetricBucket] = []

    Scenario() \
        .given(
            no_window
        ) \
        .when(
            lambda: has_a_reading_since(no_window, dont_care_minute)
        ) \
        .then(
            _the_answer_is(False)
        )


@pytest.mark.unit
def test_nothing_read_and_nothing_recovered_are_told_apart() -> None:
    # The whole reason the question exists. Both of these answer `False` to
    # "has it recovered", and they are opposite claims about the service: one is a
    # shop still failing where somebody is watching, the other a shop nobody can
    # see. A caller that cannot separate them either refutes a mitigation nobody
    # measured or waits out a service that already answered.
    some_steady_rate = 0.01
    some_degradation_rate = some_steady_rate * 30
    still_failing = a_window_of(
        [some_steady_rate] * CALM_MINUTES + [some_degradation_rate] * 3
    )
    the_action = still_failing[-2].bucket_id

    nobody_watching = a_window_of([some_steady_rate] * CALM_MINUTES)
    the_same_action_unwatched = _the_minute_after(nobody_watching[-1].bucket_id)

    Scenario() \
        .given(
            (still_failing, nobody_watching)
        ) \
        .when(
            lambda: {
                "recovered while watched": has_recovered_since(
                    still_failing, the_action, SOME_THRESHOLDS
                ),
                "read while watched": has_a_reading_since(still_failing, the_action),
                "recovered while unwatched": has_recovered_since(
                    nobody_watching, the_same_action_unwatched, SOME_THRESHOLDS
                ),
                "read while unwatched": has_a_reading_since(
                    nobody_watching, the_same_action_unwatched
                )
            }
        ) \
        .then(
            _the_two_silences_are_not_one()
        )


def _the_two_silences_are_not_one() -> Assertion[dict[str, bool]]:
    """Neither window has recovered, and only one of them was ever read.

    Asserted together rather than as two tests, because what is being claimed is
    a difference: separately, each half is satisfied by a function that always
    answers the same thing.
    """
    def assertion(answers: dict[str, bool]) -> bool:
        if answers["recovered while watched"] or answers["recovered while unwatched"]:
            raise AssertionError(
                f"Both windows were built so that nothing has recovered, and the "
                f"recovery question answered {answers} - so this test is no longer "
                f"comparing the two silences it was written to compare."
            )

        if not answers["read while watched"]:
            raise AssertionError(
                f"A window carrying minutes at and after the action was reported as "
                f"having no reading since it, which would leave a service that is "
                f"plainly still failing indistinguishable from one nobody watched: "
                f"{answers}."
            )

        if answers["read while unwatched"]:
            raise AssertionError(
                f"A window whose minutes stop before the action was reported as "
                f"having a reading since it, so a mitigation nobody measured would "
                f"be refuted on the evidence of a window that never covered it: "
                f"{answers}."
            )

        return True

    return assertion


def _no_minute_read_as_a_recovery() -> Assertion[dict[str, bool]]:
    """No minute of a running cycle is one the incident has recovered from.

    Named minutes in the message rather than a count: which of them read as a
    recovery says whether the rule is wrong about the clear minute, about the
    minute after it, or about the whole stretch, and a count says none of that.
    """
    def assertion(answers: dict[str, bool]) -> bool:
        recovered = sorted(minute for minute, yes in answers.items() if yes)

        if recovered:
            raise AssertionError(
                f"Expected no minute of a service that is clear one minute in "
                f"three to read as a recovery, and {recovered} did."
            )

        return True

    return assertion


def _every_poll_agreed_it_had_recovered() -> Assertion[dict[int, bool]]:
    """That every window length answered that the incident had recovered.

    Named by how long each poll waited rather than counted, because which
    lengths disagreed says where the level went wrong: the short ones mean it is
    being read off too little, the middle ones that the minutes since the action
    are in it, and the long ones that the baseline has re-learned the plateau.
    """
    def every_poll_agreed_it_had_recovered(answers: dict[int, bool]) -> bool:
        disagreed = sorted(held for held, recovered in answers.items() if not recovered)

        if disagreed:
            raise AssertionError(
                f"A service that shed most of its rise and then held still has "
                f"recovered however long anybody waits to ask, and the polls that "
                f"waited {disagreed} minutes answered that it had not: {answers}."
            )

        return True

    return every_poll_agreed_it_had_recovered


def _the_minute_after(bucket_id: str) -> str:
    return to_iso_minute(parse_iso(bucket_id) + timedelta(minutes=1))


def a_window_departing_from(steady_rate: float) -> list[MetricBucket]:
    """The same shape of departure - a calm stretch, then a ninefold rise -
    around whatever rate the service idles at."""
    return a_window_of(
        [steady_rate] * CALM_MINUTES + [steady_rate * 9, steady_rate * 18]
    )


def a_window_of(error_rates: list[float],
                p95_ms_values: list[int] | None = None,
                memory_bytes: list[int] | None = None,
                p50_ms_values: list[int] | None = None,
                p99_ms_values: list[int] | None = None) -> list[MetricBucket]:
    latencies = p95_ms_values or [CALM_P95_MS] * len(error_rates)
    medians = p50_ms_values or [CALM_P50_MS] * len(error_rates)
    tails = p99_ms_values or [CALM_P99_MS] * len(error_rates)
    memory = memory_bytes or [CALM_MEMORY_BYTES] * len(error_rates)
    window_start = datetime(2026, 8, 20, 11, 0, tzinfo=UTC)
    dont_care_volume = 1000
    dont_care_started_at = window_start.timestamp()

    return [
        MetricBucket(
            bucket_id=to_iso_minute(window_start + timedelta(minutes=offset)),
            error_rate=error_rate,
            p50_ms=p50_ms,
            p95_ms=p95_ms,
            p99_ms=p99_ms,
            request_volume=dont_care_volume,
            memory_used_bytes=memory_used,
            memory_limit_bytes=MEMORY_LIMIT_BYTES,
            process_start_time_seconds=dont_care_started_at,
            cpu_used_cores=0.77,
            cpu_limit_cores=3.0,
        )
        for offset, (error_rate, p50_ms, p95_ms, p99_ms, memory_used) in enumerate(
            zip(error_rates, medians, latencies, tails, memory, strict=True)
        )
    ]


def _the_recovery_is(expected: str) -> Assertion[str | None]:
    """That the incident was measured as ending at this minute."""
    def the_recovery_is(recovery: str | None) -> bool:
        if recovery != expected:
            raise AssertionError(
                f"Expected recovery at [{expected}], and it was [{recovery}]."
            )

        return True

    return the_recovery_is


def _it_never_recovered() -> Assertion[str | None]:
    """That no minute in the window reads as the incident ending.

    Separate from `_the_recovery_is`, for the reason `_no_onset_was_found` is
    separate: "it was still broken when the window ran out" is an answer, and
    a measurement bounded by it is a lower bound rather than a figure. A page
    that printed the two the same way is the defect this rule exists to end.
    """
    def it_never_recovered(recovery: str | None) -> bool:
        if recovery is not None:
            raise AssertionError(
                f"Expected the window to end still broken, and recovery was "
                f"reported at [{recovery}]."
            )

        return True

    return it_never_recovered


def _the_onset_is(expected: str) -> Assertion[str | None]:
    """That the incident was measured as beginning at this minute."""
    def the_onset_is(onset: str | None) -> bool:
        if onset != expected:
            raise AssertionError(
                f"Expected the onset at [{expected}], and it was [{onset}]."
            )

        return True

    return the_onset_is


def _no_onset_was_found() -> Assertion[str | None]:
    """That nothing in the window reads as the incident starting.

    Separate from `_the_onset_is`, because "no minute departed" and "it
    departed somewhere else" are different answers, and a reader of a failure
    wants to be told which.
    """
    def no_onset_was_found(onset: str | None) -> bool:
        if onset is not None:
            raise AssertionError(
                f"Expected no onset in this window, and [{onset}] was reported."
            )

        return True

    return no_onset_was_found


def _the_answer_is(expected: bool) -> Assertion[bool]:
    """That the question the window was asked came back this way."""
    def the_answer_is(answered: bool) -> bool:
        if answered is not expected:
            raise AssertionError(
                f"Expected [{expected}], and it answered [{answered}]."
            )

        return True

    return the_answer_is
