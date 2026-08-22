from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from typing import NamedTuple

import pytest
from argus_core.config import get_settings
from argus_core.models.metrics import MetricBucket
from read_mcp_server.retrieval import get_log_lines, get_metrics_summary

TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
MINUTES_IN_A_DAY = 24 * 60

settings = get_settings()


@pytest.mark.unit
def test_get_log_lines_returns_whatever_fetch_returns() -> None:
    some_logs = ["INFO line one", "ERROR line two"]

    result = get_log_lines(fetch=lambda: some_logs)

    assert result == some_logs

@pytest.mark.unit
def test_get_log_lines_windows_around_the_alert_time() -> None:
    some_alert_time = _an_alert_time()
    some_timeline = _a_log_timeline_around(some_alert_time)
    some_lines = _some_log_lines_at(some_timeline)

    result = get_log_lines(alert_time=_an_iso_minute(some_alert_time), fetch=lambda: some_lines)

    assert result == [
        _a_log_line_at(some_timeline.inside_lookback),
        _a_log_line_at(some_timeline.inside_lookahead),
    ]

@pytest.mark.unit
def test_get_log_lines_explicit_window_overrides_the_alert_time() -> None:
    some_alert_time = _an_alert_time()
    some_timeline = _a_log_timeline_around(some_alert_time)
    some_lines = _some_log_lines_at(some_timeline)
    a_window_start_around_the_too_late_minute = some_timeline.too_late - timedelta(minutes=1)
    a_window_end_around_the_too_late_minute = some_timeline.too_late + timedelta(minutes=1)

    result = get_log_lines(
        alert_time=_an_iso_minute(some_alert_time),
        window_start=_an_iso_minute(a_window_start_around_the_too_late_minute),
        window_end=_an_iso_minute(a_window_end_around_the_too_late_minute),
        fetch=lambda: some_lines,
    )

    assert result == [_a_log_line_at(some_timeline.too_late)]

@pytest.mark.unit
def test_get_log_lines_clamps_an_over_span_window_and_reports_it() -> None:
    some_alert_time = _an_alert_time()
    some_timeline = _a_log_timeline_around(some_alert_time)
    some_lines = _some_log_lines_at(some_timeline)
    an_over_span_window_end = some_timeline.too_early + timedelta(
        minutes=settings.log_max_window_minutes + 1
    )

    result = get_log_lines(
        window_start=_an_iso_minute(some_timeline.too_early),
        window_end=_an_iso_minute(an_over_span_window_end),
        fetch=lambda: some_lines,
    )

    assert result[0].startswith("WARN argus-read-mcp: requested window exceeded")
    # Clamped from the start, and the timeline is built to fit inside the
    # ceiling, so no line is lost to the clamp itself.
    assert result[1:] == some_lines

@pytest.mark.unit
def test_get_log_lines_scopes_to_the_named_buckets() -> None:
    some_alert_time = _an_alert_time()
    some_timeline = _a_log_timeline_around(some_alert_time)
    some_lines = _some_log_lines_at(some_timeline)

    result = get_log_lines(
        alert_time=_an_iso_minute(some_alert_time),
        bucket_ids=[_an_iso_minute(some_timeline.inside_lookahead)],
        fetch=lambda: some_lines,
    )

    assert result == [_a_log_line_at(some_timeline.inside_lookahead)]

@pytest.mark.unit
def test_get_log_lines_drops_lines_with_no_timestamp_when_windowed() -> None:
    some_alert_time = _an_alert_time()
    some_timeline = _a_log_timeline_around(some_alert_time)
    some_untimestamped_line = "ERROR target-service: legacy line with no timestamp"
    some_lines = [*_some_log_lines_at(some_timeline), some_untimestamped_line]

    result = get_log_lines(alert_time=_an_iso_minute(some_alert_time), fetch=lambda: some_lines)

    assert result == [
        _a_log_line_at(some_timeline.inside_lookback),
        _a_log_line_at(some_timeline.inside_lookahead),
    ]


@pytest.mark.unit
def test_get_metrics_summary_returns_every_bucket_without_a_window() -> None:
    some_alert_time = _an_alert_time()
    some_buckets = [
        _a_bucket(some_alert_time - timedelta(minutes=settings.metrics_window_minutes)),
        _a_bucket(some_alert_time),
    ]

    result = get_metrics_summary(fetch=lambda: some_buckets)

    assert result == some_buckets


@pytest.mark.unit
def test_get_metrics_summary_excludes_buckets_outside_the_window() -> None:
    some_alert_time = _an_alert_time()
    a_metrics_window = timedelta(minutes=settings.metrics_window_minutes)
    a_minute_past_the_window = a_metrics_window + timedelta(minutes=1)
    the_bucket_on_the_window_edge = _a_bucket(some_alert_time - a_metrics_window)
    some_buckets = [
        _a_bucket(some_alert_time - a_minute_past_the_window),
        the_bucket_on_the_window_edge,
        _a_bucket(some_alert_time + a_minute_past_the_window),
    ]

    result = get_metrics_summary(
        alert_time=_an_iso_minute(some_alert_time), fetch=lambda: some_buckets
    )

    assert result == [the_bucket_on_the_window_edge]

@pytest.mark.unit
def test_get_metrics_summary_with_no_active_scenario_returns_no_buckets() -> None:
    result = get_metrics_summary(alert_time=_an_iso_minute(_an_alert_time()), fetch=list)

    assert result == []


def _an_alert_time() -> datetime:
    """A random minute-aligned instant, safely in the past."""

    # old enough such that times won't get mixed with current time - anywhere 
    # between a day and a month ago
    minutes_ago_way_back = random.randint(MINUTES_IN_A_DAY, 30 * MINUTES_IN_A_DAY) 
    old_time = datetime.now(UTC) - timedelta(minutes=minutes_ago_way_back)

    return old_time.replace(second=0, microsecond=0)

def _a_timeline_around(alert_time: datetime, 
                       lookback_minutes: int, 
                       lookahead_minutes: int) -> _Timeline:
    """Four minutes straddling both edges of `[T0 - lookback, T0 + lookahead]`.

    Each offset is random within its band, so a test that passes only because
    of one particular arrangement of minutes will eventually say so.
    How far past an edge a minute may sit is derived, not picked: the whole 
    timeline has to fit inside the clamp ceiling, or the clamp test would lose 
    lines to the ceiling rather than to the behavior it checks.
    """
    max_minutes_beyond_an_edge = (
        settings.log_max_window_minutes - lookback_minutes - lookahead_minutes
    ) // 2

    def random_minutes_beyond_an_edge() -> int:
        return random.randint(1, max_minutes_beyond_an_edge)

    return _Timeline(
        too_early=alert_time - timedelta(
            minutes=lookback_minutes + random_minutes_beyond_an_edge()),
        inside_lookback=alert_time - timedelta(
            minutes=random.randint(1, lookback_minutes - 1)),
        inside_lookahead=alert_time + timedelta(
            minutes=random.randint(1, lookahead_minutes - 1)),
        too_late=alert_time + timedelta(
            minutes=lookahead_minutes + random_minutes_beyond_an_edge()),
    )

def _a_log_timeline_around(alert_time: datetime) -> _Timeline:
    return _a_timeline_around(
        alert_time,
        lookback_minutes=settings.log_initial_lookback_minutes,
        lookahead_minutes=settings.log_initial_lookahead_minutes,
    )

def _an_iso_minute(minute: datetime) -> str:
    return minute.strftime(TIMESTAMP_FORMAT)

def _a_log_line_at(minute: datetime) -> str:
    return f"{_an_iso_minute(minute)} INFO target-service: some log line"

def _some_log_lines_at(timeline: _Timeline) -> list[str]:
    return [_a_log_line_at(minute) for minute in timeline]

def _a_bucket(minute: datetime, error_rate: float = 0.01) -> MetricBucket:
    return MetricBucket(
        bucket_id=_an_iso_minute(minute),
        error_rate=error_rate,
        p50_ms=40,
        p95_ms=200,
        request_volume=1000,
    )


class _Timeline(NamedTuple):
    """Four minutes, positioned relative to an alert time and the window around it.

    Named rather than indexed: the difference between `inside_lookback` and
    `too_early` is the behavior under test, and `LINES[1]` said nothing about
    which side of which edge it sat on.
    """

    too_early: datetime
    inside_lookback: datetime
    inside_lookahead: datetime
    too_late: datetime
