from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import NamedTuple

import pytest
from argus_core.config import get_settings
from argus_core.models.metrics import MetricBucket
from argus_testkit.assertions import Assertion, all_of
from argus_testkit.scenario import Scenario
from conftest import FakeTargetServiceHandler
from framework.builders import (
    a_failure_line_at,
    a_metric_at,
    a_success_line_at,
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
    some_quiet_minute = datetime(2026, 8, 20, 11, 45, 0, tzinfo=UTC)
    some_loud_minute = some_quiet_minute + timedelta(minutes=1)
    some_alert_time = _an_alert_time_within_window_after(some_loud_minute)
    some_error_rate_threshold = 0.1
    some_anomalous_error_rate = 0.41
    the_target_service_has = partial(_the_target_service_has, running_read_mcp)

    Scenario() \
        .given(
            the_target_service_has(
                metrics=[
                    a_metric_at(some_quiet_minute),
                    a_metric_at(some_loud_minute, error_rate=some_anomalous_error_rate),
                ],
                logs=[
                    a_success_line_at(some_quiet_minute),
                    a_failure_line_at(some_loud_minute),
                ],
            )
        ) \
        .when(
            _drilling_down_from_metrics_to_logs(
                some_alert_time, into=_error_rate_above(some_error_rate_threshold)
            )
        ) \
        .then(all_of(
            _the_anomalous_buckets_are([an_iso_minute(some_loud_minute)]),
            _the_retrieved_lines_are([a_failure_line_at(some_loud_minute)]),
        ))


class _DrillDown(NamedTuple):
    """Both phases' output, so `then` can assert on each.

    Phase one's choice of buckets is as much the behavior under test as the
    lines phase two returns - asserting only on the lines would pass even if
    the summary had flagged every minute.
    """

    anomalous_bucket_ids: list[str]
    lines: list[str]


def _drilling_down_from_metrics_to_logs(alert_time: str, 
                                        into: Callable[[MetricBucket], bool]
) -> Callable[[], _DrillDown]:
    def step() -> _DrillDown:
        buckets = get_metrics_summary(alert_time=alert_time)
        anomalous_bucket_ids = [bucket.bucket_id for bucket in buckets if into(bucket)]

        return _DrillDown(
            anomalous_bucket_ids=anomalous_bucket_ids,
            lines=get_log_lines(alert_time=alert_time, bucket_ids=anomalous_bucket_ids),
        )

    return step


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


def _the_anomalous_buckets_are(expected: list[str]) -> Assertion[_DrillDown]:
    def assertion(drill_down: _DrillDown) -> bool:
        if drill_down.anomalous_bucket_ids != expected:
            raise AssertionError(
                f"Expected anomalous buckets {expected}, got {drill_down.anomalous_bucket_ids}."
            )

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
