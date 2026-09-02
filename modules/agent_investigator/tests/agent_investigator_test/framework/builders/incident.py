"""The incident an investigation is about: the alert, and the minutes around it.

One incident, built the same way everywhere, so that a window named in one
test file means the same thing in the next. The error rates are what make a
minute anomalous or not - the onset is measured from them, and every default
retrieval window is anchored on it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from argus_core.models.alert import Alert
from argus_core.models.metrics import MetricBucket

# Long enough for the anomaly detector to have a baseline to depart from.
CALM_MINUTES = 10

CALM_ERROR_RATE = 0.01
CALM_P50_MS = 80
CALM_P95_MS = 200
DONT_CARE_REQUEST_VOLUME = 1000

WINDOW_START = datetime(2026, 8, 20, 11, 0, tzinfo=UTC)
AN_ALERT_TIME = datetime(2026, 8, 20, 11, 8, tzinfo=UTC)

A_SERVICE = "kuki"


def an_alert(started_at: datetime | None = AN_ALERT_TIME) -> Alert:
    """The alert that opened the incident.

    `started_at` is a parameter because its absence is a real case - an alert
    that never said when it fired - and it decides where a default log window
    ends.
    """
    return Alert(service=A_SERVICE, alert_name="HighErrorRate", started_at=started_at)


def a_window_that_starts_calm() -> list[MetricBucket]:
    """Minutes with a locatable onset: a calm baseline, then a departure."""
    return a_window_of([CALM_ERROR_RATE] * CALM_MINUTES + [0.09, 0.18])


def a_window_that_starts_mid_incident() -> list[MetricBucket]:
    """Already elevated at its earliest minute, so the onset is only a lower
    bound - the incident began before anything Argus can see."""
    return a_window_of([0.30, 0.28, 0.25, 0.21, 0.20, 0.19])


def a_steady_window() -> list[MetricBucket]:
    """No minute departs from the baseline, so there is no onset to find."""
    return a_window_of([CALM_ERROR_RATE] * (CALM_MINUTES + 2))


def a_window_of(error_rates: list[float]) -> list[MetricBucket]:
    return [
        MetricBucket(
            bucket_id=_the_minute_at(offset),
            error_rate=error_rate,
            p50_ms=CALM_P50_MS,
            p95_ms=CALM_P95_MS,
            request_volume=DONT_CARE_REQUEST_VOLUME
        )
        for offset, error_rate in enumerate(error_rates)
    ]


def the_onset_of(buckets: list[MetricBucket]) -> str:
    """The minute a window's first departure lands in.

    Derived from the buckets rather than restated as a constant, so a test
    asserting what the model was told about the onset cannot drift from the
    window it was given.
    """
    calm = [bucket for bucket in buckets if bucket.error_rate <= CALM_ERROR_RATE]

    return buckets[len(calm)].bucket_id


def _the_minute_at(offset: int) -> str:
    return (WINDOW_START + timedelta(minutes=offset)).strftime("%Y-%m-%dT%H:%M:%SZ")
