from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from agent_investigator.anomaly import earliest_bucket_is_anomalous, find_onset
from argus_core.models.metrics import MetricBucket
from argus_core.timestamps import to_iso_minute


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

    assert find_onset(some_window) == first_departing_bucket.bucket_id


@pytest.mark.unit
def test_find_onset_reports_nothing_when_the_whole_window_is_steady() -> None:
    some_steady_rate = 0.01
    some_window = a_window_of([some_steady_rate] * (CALM_MINUTES + 2))

    assert find_onset(some_window) is None


@pytest.mark.unit
def test_find_onset_reports_nothing_for_an_empty_window() -> None:
    empty_window: list[MetricBucket] = []

    assert find_onset(empty_window) is None


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

    assert find_onset(some_low_rate_window) == first_departing_low_rate_bucket.bucket_id
    assert find_onset(some_high_rate_window) == first_departing_high_rate_bucket.bucket_id


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

    assert find_onset(some_window) == first_departing_bucket.bucket_id


@pytest.mark.unit
def test_the_earliest_bucket_is_anomalous_when_the_window_opens_at_its_worst_minute() -> None:
    # No calm stretch is visible: the window opens mid-incident and decays, so
    # the onset is off the left edge and the next iteration must reach back.
    some_declining_rates_from_a_peak = [0.30, 0.28, 0.25, 0.21, 0.20, 0.19]
    some_window_opening_mid_incident = a_window_of(some_declining_rates_from_a_peak)

    assert earliest_bucket_is_anomalous(some_window_opening_mid_incident) is True


@pytest.mark.unit
def test_the_earliest_bucket_is_not_anomalous_when_the_window_opens_calm() -> None:
    some_steady_rate = 0.01
    some_degradation_rate = some_steady_rate * 9
    some_calm_subwindow = [some_steady_rate] * CALM_MINUTES
    some_window = a_window_of(some_calm_subwindow + [some_degradation_rate])

    assert earliest_bucket_is_anomalous(some_window) is False


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

    assert find_onset(some_window) is None


@pytest.mark.unit
def test_find_onset_reports_a_departure_that_is_still_going_when_the_window_ends() -> None:
    # An incident a minute old has not failed to persist - it has not yet been
    # given the chance. The window ending is not evidence of recovery.
    some_steady_rate = 0.01
    some_degradation_rate = some_steady_rate * 30
    some_window = a_window_of([some_steady_rate] * CALM_MINUTES + [some_degradation_rate])

    last_bucket = some_window[-1]

    assert find_onset(some_window) == last_bucket.bucket_id


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

    assert find_onset(some_window) == first_incident_bucket.bucket_id


CALM_MINUTES = 6
CALM_P50_MS = 80
CALM_P95_MS = 200


def a_window_departing_from(steady_rate: float) -> list[MetricBucket]:
    """The same shape of departure - a calm stretch, then a ninefold rise -
    around whatever rate the service idles at."""
    return a_window_of(
        [steady_rate] * CALM_MINUTES + [steady_rate * 9, steady_rate * 18]
    )


def a_window_of(error_rates: list[float],
                p95_ms_values: list[int] | None = None) -> list[MetricBucket]:
    latencies = p95_ms_values or [CALM_P95_MS] * len(error_rates)
    window_start = datetime(2026, 8, 20, 11, 0, tzinfo=UTC)
    dont_care_volume = 1000

    return [
        MetricBucket(
            bucket_id=to_iso_minute(window_start + timedelta(minutes=offset)),
            error_rate=error_rate,
            p50_ms=CALM_P50_MS,
            p95_ms=p95_ms,
            request_volume=dont_care_volume,
        )
        for offset, (error_rate, p95_ms) in enumerate(
            zip(error_rates, latencies, strict=True)
        )
    ]
