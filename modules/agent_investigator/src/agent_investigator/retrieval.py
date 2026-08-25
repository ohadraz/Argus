from __future__ import annotations

from collections.abc import Callable

from argus_core.models.metrics import MetricBucket
from read_mcp_client import get_log_lines, get_metrics_summary

MetricsFetcher = Callable[[str | None], list[MetricBucket]]
LogFetcher = Callable[[str, str], list[str]]


def fetch_metrics(alert_time: str | None) -> list[MetricBucket]:
    """Phase one of spec §16's two-phase retrieval: the per-minute buckets the
    onset is located in.

    A named function rather than `get_metrics_summary` passed directly,
    because the loop needs exactly one of that tool's four calling shapes -
    anchored on the alert - and a seam is only useful if a test can spec
    against the shape the caller actually uses.
    """
    return get_metrics_summary(alert_time=alert_time)


def fetch_logs(window_start: str, window_end: str) -> list[str]:
    """Phase two: the log lines for one explicit window, both bounds ISO-8601.

    Always an explicit window, never an alert anchor - by the time the loop
    reads logs it has an onset, and the whole point of two-phase retrieval is
    to spend the expensive phase around that onset rather than around the
    moment somebody's alerting rule happened to fire.
    """
    return get_log_lines(window_start=window_start, window_end=window_end)
