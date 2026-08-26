from __future__ import annotations

from collections.abc import Callable

from argus_core.models.change_event import ChangeEvent
from argus_core.models.metrics import MetricBucket
from read_mcp_client import get_change_events, get_log_lines, get_metrics_summary

MetricsFetcher = Callable[[str | None], list[MetricBucket]]
LogFetcher = Callable[[str, str], list[str]]
ChangeFetcher = Callable[[str, str, str], list[ChangeEvent]]


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


def fetch_change_events(service: str, window_start: str, window_end: str) -> list[ChangeEvent]:
    """The third channel: what changed on the service over one explicit window.

    A separate seam from the log fetcher because it answers a different
    question on a different timescale - *what changed* rather than what the
    service said - over a window far wider than any the widening schedule
    reaches. There are only ever a handful of changes to read where there
    would be millions of log lines.

    Raises rather than reporting nothing when the change source cannot be
    reached; over MCP that arrives here as a plain `RuntimeError`.
    """
    return get_change_events(
        service=service, window_start=window_start, window_end=window_end
    )
