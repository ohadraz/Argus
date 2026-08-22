from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import NamedTuple

import pytest
from argus_core.config import get_settings
from argus_core.models.metrics import MetricBucket
from argus_core.timestamps import parse_iso
from argus_testkit.assertions import Assertion, all_of
from argus_testkit.scenario import Scenario
from conftest import FakeTargetServiceHandler
from framework.builders import (
    a_cause_line_at,
    a_failure_line_at,
    a_metric_at,
    an_iso_minute,
)
from read_mcp_client import get_log_lines, get_metrics_summary


@pytest.mark.integration
def test_get_log_lines_reaches_the_real_read_mcp_server(
    running_read_mcp: type[FakeTargetServiceHandler]
) -> None:
    some_logs = ["INFO some line", "ERROR another line"]
    the_target_service_has_logs = partial(_the_target_service_has, running_read_mcp)

    Scenario() \
        .given(
            the_target_service_has_logs(some_logs)
        ) \
        .when(
            get_log_lines
        ) \
        .then(
            _the_returned_lines_are(some_logs)
        )


@pytest.mark.integration
def test_both_retrieval_phases_drive_each_other_through_the_client(
    running_read_mcp: type[FakeTargetServiceHandler]
) -> None:
    some_time_the_cause_happened = datetime(2026, 8, 20, 11, 45, 0, tzinfo=UTC)
    some_time_the_error_appeared = some_time_the_cause_happened + timedelta(minutes=1)
    some_alert_time = _an_alert_time_within_window_after(some_time_the_error_appeared)
    some_error_rate_threshold = 0.1
    some_anomalous_error_rate = 0.41
    the_target_service_has = partial(_the_target_service_has, running_read_mcp)

    Scenario() \
        .given(
            the_target_service_has(
                metrics=[
                    a_metric_at(some_time_the_cause_happened),
                    a_metric_at(
                        some_time_the_error_appeared, error_rate=some_anomalous_error_rate
                    ),
                ],
                logs=[
                    a_cause_line_at(some_time_the_cause_happened),
                    a_failure_line_at(some_time_the_error_appeared),
                ],
            )
        ) \
        .when(
            _drilling_down_from_metrics_to_logs(
                some_alert_time, into=_error_rate_above(some_error_rate_threshold)
            )
        ) \
        .then(all_of(
            _the_onset_is(an_iso_minute(some_time_the_error_appeared)),
            # The cause line sits in a minute the summary called healthy. A
            # window anchored on onset reaches back past it; scoping to the
            # anomalous minutes never could.
            _the_retrieved_lines_are([
                a_cause_line_at(some_time_the_cause_happened),
                a_failure_line_at(some_time_the_error_appeared),
            ]),
        ))


class _DrillDown(NamedTuple):
    """Both phases' output, so `then` can assert on each.

    Phase one's onset is as much the behavior under test as the lines phase
    two returns - asserting only on the lines would pass even if the summary
    had flagged the wrong minute.
    """

    onset: str | None
    lines: list[str]


def _drilling_down_from_metrics_to_logs(alert_time: str,
                                        into: Callable[[MetricBucket], bool]
) -> Callable[[], _DrillDown]:
    def step() -> _DrillDown:
        buckets = get_metrics_summary(alert_time=alert_time)
        anomalous = [bucket for bucket in buckets if into(bucket)]
        onset = anomalous[0].bucket_id if anomalous else None

        if onset is None:
            return _DrillDown(onset=None, lines=[])

        window_start, window_end = _a_window_anchored_on(onset)

        return _DrillDown(
            onset=onset,
            lines=get_log_lines(window_start=window_start, window_end=window_end),
        )

    return step


def _a_window_anchored_on(onset: str) -> tuple[str, str]:
    """The log window §16 anchors on onset rather than on the alert time.

    Back by the configured lookback, which is what has to contain the cause;
    forward by the lookahead, which contains the symptoms already seen.
    """
    settings = get_settings()
    onset_minute = parse_iso(onset)

    return (
        an_iso_minute(onset_minute - timedelta(minutes=settings.log_initial_lookback_minutes)),
        an_iso_minute(onset_minute + timedelta(minutes=settings.log_initial_lookahead_minutes)),
    )


def _error_rate_above(threshold: float) -> Callable[[MetricBucket], bool]:
    def is_anomalous(bucket: MetricBucket) -> bool:
        return bucket.error_rate > threshold

    return is_anomalous


def _an_alert_time_within_window_after(onset: datetime) -> str:
    settings = get_settings()

    return an_iso_minute(onset + timedelta(minutes=settings.log_initial_lookback_minutes // 2))


def _the_target_service_has(handler: type[FakeTargetServiceHandler],
                            logs: list[str],
                            metrics: list[dict[str, object]] | None = None) -> Callable[[], None]:
    def step() -> None:
        handler.logs = logs
        handler.metrics = metrics or []

    return step


def _the_onset_is(expected: str) -> Assertion[_DrillDown]:
    def assertion(drill_down: _DrillDown) -> bool:
        if drill_down.onset != expected:
            raise AssertionError(f"Expected onset {expected}, got {drill_down.onset}.")

        return True

    return assertion


def _the_returned_lines_are(expected: list[str]) -> Assertion[list[str]]:
    def assertion(lines: list[str]) -> bool:
        return _lines_match(lines, expected)

    return assertion


def _the_retrieved_lines_are(expected: list[str]) -> Assertion[_DrillDown]:
    def assertion(drill_down: _DrillDown) -> bool:
        return _lines_match(drill_down.lines, expected)

    return assertion


def _lines_match(actual: list[str], expected: list[str]) -> bool:
    if actual != expected:
        raise AssertionError(f"Expected lines {expected}, got {actual}.")

    return True
