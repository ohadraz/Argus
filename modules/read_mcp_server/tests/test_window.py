from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

import pytest
from argus_core.config import get_settings
from read_mcp_server.window import ResolvedWindow, resolve_log_window, resolve_metrics_window

TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
MINUTES_IN_A_DAY = 24 * 60

settings = get_settings()


@pytest.mark.unit
def test_no_alert_time_and_no_window_resolves_to_no_window() -> None:
    result = resolve_log_window()

    assert result == ResolvedWindow(start=None, end=None, clamped=False)


@pytest.mark.unit
def test_a_log_window_spans_the_configured_lookback_and_lookahead() -> None:
    some_alert_time = _an_alert_time()

    result = resolve_log_window(alert_time=_an_iso_minute(some_alert_time))

    assert result == ResolvedWindow(
        start=some_alert_time - timedelta(minutes=settings.log_initial_lookback_minutes),
        end=some_alert_time + timedelta(minutes=settings.log_initial_lookahead_minutes),
        clamped=False,
    )


@pytest.mark.unit
def test_a_log_window_whose_lookahead_runs_past_now_ends_at_now() -> None:
    too_recent_alert = _a_minute_ago(settings.log_initial_lookahead_minutes - 1)
    lookahead_in_the_future = too_recent_alert + timedelta(
        minutes=settings.log_initial_lookahead_minutes)

    result = resolve_log_window(
        alert_time=_an_iso_minute(too_recent_alert)
    )

    # `now` advances while the test runs, so the assertion is on the bound
    # rather than on an instant: the end stopped short of the full lookahead,
    # and did not overshoot into the future.
    assert result.end is not None
    assert result.end < lookahead_in_the_future
    assert result.end <= datetime.now(UTC)
    # Stopping at "now" is NOT the span clamp, so nothing to warn the caller about
    assert not result.clamped


@pytest.mark.unit
def test_an_explicit_log_window_exactly_on_the_ceiling_is_used_as_given() -> None:
    some_window_start = _an_alert_time()
    window_end_exactly_on_the_ceiling = some_window_start + timedelta(
        minutes=settings.log_max_window_minutes
    )

    result = resolve_log_window(
        window_start=_an_iso_minute(some_window_start),
        window_end=_an_iso_minute(window_end_exactly_on_the_ceiling),
    )

    assert result == ResolvedWindow(
        start=some_window_start,
        end=window_end_exactly_on_the_ceiling,
        clamped=False,
    )


@pytest.mark.unit
def test_an_explicit_window_overrides_the_alert_time() -> None:
    some_alert_time = _an_alert_time()
    some_unrelated_window_start = some_alert_time - timedelta(days=1)
    some_unrelated_window_end = some_unrelated_window_start + timedelta(minutes=1)

    result = resolve_log_window(
        alert_time=_an_iso_minute(some_alert_time),
        window_start=_an_iso_minute(some_unrelated_window_start),
        window_end=_an_iso_minute(some_unrelated_window_end),
    )

    assert result == ResolvedWindow(
        start=some_unrelated_window_start,
        end=some_unrelated_window_end,
        clamped=False,
    )


@pytest.mark.unit
def test_an_over_span_log_window_is_clamped_forward_from_its_start() -> None:
    some_window_start = _an_alert_time()
    window_end_past_the_ceiling = some_window_start + timedelta(
        minutes=settings.log_max_window_minutes + 1
    )

    result = resolve_log_window(
        window_start=_an_iso_minute(some_window_start),
        window_end=_an_iso_minute(window_end_past_the_ceiling),
    )

    # Anchored at the start: the earliest minutes are the ones that explain
    # onset, so an over-wide request loses its tail, never its head.
    assert result == ResolvedWindow(
        start=some_window_start,
        end=some_window_start + timedelta(minutes=settings.log_max_window_minutes),
        clamped=True,
    )


@pytest.mark.unit
def test_a_log_window_with_only_a_start_is_clamped_forward_from_it() -> None:
    some_window_start = _an_alert_time()

    result = resolve_log_window(window_start=_an_iso_minute(some_window_start))

    assert result == ResolvedWindow(
        start=some_window_start,
        end=some_window_start + timedelta(minutes=settings.log_max_window_minutes),
        clamped=True,
    )


@pytest.mark.unit
def test_a_log_window_with_only_an_end_is_clamped_back_from_it() -> None:
    some_window_end = _an_alert_time()

    result = resolve_log_window(window_end=_an_iso_minute(some_window_end))

    assert result == ResolvedWindow(
        start=some_window_end - timedelta(minutes=settings.log_max_window_minutes),
        end=some_window_end,
        clamped=True,
    )


@pytest.mark.unit
def test_a_metrics_window_spans_the_metrics_window_on_both_sides_of_the_alert() -> None:
    some_alert_time = _an_alert_time()
    metrics_window = timedelta(minutes=settings.metrics_window_minutes)

    result = resolve_metrics_window(alert_time=_an_iso_minute(some_alert_time))

    assert result == ResolvedWindow(
        start=some_alert_time - metrics_window,
        end=some_alert_time + metrics_window,
        clamped=False,
    )


@pytest.mark.unit
def test_a_metrics_window_wider_than_the_log_ceiling_is_not_clamped() -> None:
    some_window_start = _an_alert_time()
    window_end_past_only_the_log_ceiling = some_window_start + timedelta(
        minutes=settings.log_max_window_minutes + 1
    )

    result = resolve_metrics_window(
        window_start=_an_iso_minute(some_window_start),
        window_end=_an_iso_minute(window_end_past_only_the_log_ceiling),
    )

    # Metrics have their own, wider ceiling - a span the log phase would refuse
    # is ordinary here, which is the whole reason the two resolvers are separate.
    assert result == ResolvedWindow(
        start=some_window_start,
        end=window_end_past_only_the_log_ceiling,
        clamped=False,
    )


@pytest.mark.unit
def test_an_over_span_metrics_window_is_clamped_to_the_metrics_span() -> None:
    some_window_start = _an_alert_time()
    window_end_past_the_metrics_span = some_window_start + timedelta(
        minutes=settings.metrics_window_minutes + 1
    )

    result = resolve_metrics_window(
        window_start=_an_iso_minute(some_window_start),
        window_end=_an_iso_minute(window_end_past_the_metrics_span),
    )

    assert result == ResolvedWindow(
        start=some_window_start,
        end=some_window_start + timedelta(minutes=settings.metrics_window_minutes),
        clamped=True,
    )


def _a_minute_ago(minutes: int) -> datetime:
    return datetime.now(UTC).replace(second=0, microsecond=0) - timedelta(minutes=minutes)


def _an_alert_time() -> datetime:
    """A random minute-aligned instant, far enough back that no window reaches now.

    Anywhere between a day and a month ago - wider than the widest configured
    span, so a test that does not mean to exercise the "now" bound never
    stumbles into it.
    """
    return _a_minute_ago(random.randint(MINUTES_IN_A_DAY, 30 * MINUTES_IN_A_DAY))


def _an_iso_minute(minute: datetime) -> str:
    return minute.strftime(TIMESTAMP_FORMAT)
