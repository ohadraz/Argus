from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from argus_core.anomaly import (
    AnomalyThresholds,
    earliest_bucket_is_anomalous,
    find_onset,
    has_recovered_since,
)
from argus_core.models.metrics import MetricBucket
from argus_core.timestamps import parse_iso, to_iso_minute
from argus_testkit import Assertion, Scenario

# Where this suite draws the algorithm's lines - the same numbers the
# environment carries by default, stated here because every expectation
# below is arithmetic on them. A test reading them from the configuration
# the code reads would agree with itself whatever either said.
SOME_THRESHOLDS = AnomalyThresholds(
    deviations_from_baseline=3.0,
    persistence_minutes=2,
    recovery_fraction_of_the_rise=0.8
)


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
    # ordinary minute reads as the incident starting.
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
def test_a_single_noisy_minute_after_the_action_is_not_a_relapse() -> None:
    # The same rule `find_onset` already applies, asked of the other end: a lone
    # departed minute is sampling noise that had already recovered by the next
    # one. Without it here, a service that came back is called broken by one
    # jittery minute - and since the window only grows, that minute never leaves
    # it, so no amount of waiting clears the verdict and a correct mitigation is
    # refuted.
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
        + [a_rate_most_of_the_way_back]
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


def _the_minute_after(bucket_id: str) -> str:
    return to_iso_minute(parse_iso(bucket_id) + timedelta(minutes=1))


CALM_MINUTES = 6
CALM_P50_MS = 80
CALM_P95_MS = 200
CALM_MEMORY_BYTES = 440 * 1024**2
CALM_ERROR_RATE = 0.01
MEMORY_LIMIT_BYTES = 2 * 1024**3


def a_window_departing_from(steady_rate: float) -> list[MetricBucket]:
    """The same shape of departure - a calm stretch, then a ninefold rise -
    around whatever rate the service idles at."""
    return a_window_of(
        [steady_rate] * CALM_MINUTES + [steady_rate * 9, steady_rate * 18]
    )


def a_window_of(error_rates: list[float],
                p95_ms_values: list[int] | None = None,
                memory_bytes: list[int] | None = None) -> list[MetricBucket]:
    latencies = p95_ms_values or [CALM_P95_MS] * len(error_rates)
    memory = memory_bytes or [CALM_MEMORY_BYTES] * len(error_rates)
    window_start = datetime(2026, 8, 20, 11, 0, tzinfo=UTC)
    dont_care_volume = 1000
    dont_care_started_at = window_start.timestamp()

    return [
        MetricBucket(
            bucket_id=to_iso_minute(window_start + timedelta(minutes=offset)),
            error_rate=error_rate,
            p50_ms=CALM_P50_MS,
            p95_ms=p95_ms,
            request_volume=dont_care_volume,
            memory_used_bytes=memory_used,
            memory_limit_bytes=MEMORY_LIMIT_BYTES,
            process_start_time_seconds=dont_care_started_at,
        )
        for offset, (error_rate, p95_ms, memory_used) in enumerate(
            zip(error_rates, latencies, memory, strict=True)
        )
    ]


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
