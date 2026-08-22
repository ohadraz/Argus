from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

import httpx
from argus_core.config import get_settings
from argus_core.models.metrics import MetricBucket
from argus_core.timestamps import parse_iso, to_iso, to_iso_minute

from read_mcp_server.window import (
    ResolvedWindow,
    resolve_log_window,
    resolve_metrics_window,
)

settings = get_settings()

FetchLogs = Callable[[], list[str]]
FetchMetrics = Callable[[], list[MetricBucket]]


def _parse_log_timestamp(line: str) -> datetime | None:
    """Extracts a log line's leading ISO-8601 timestamp, or `None` if it has none.

    Parsing lives here rather than in the log source so that the port contract
    stays "return the log lines" - a future filesystem or S3 adapter needs no
    windowing logic of its own.
    """
    head, _, _rest = line.partition(" ")
    try:
        return parse_iso(head)
    except ValueError:
        return None


def _format_bound(moment: datetime | None) -> str:
    return to_iso(moment) if moment is not None else "unbounded"


def _clamp_notice(window: ResolvedWindow) -> str:
    return (
        f"WARN argus-read-mcp: requested window exceeded the configured maximum of "
        f"{settings.log_max_window_minutes} minutes - clamped to "
        f"{_format_bound(window.start)}..{_format_bound(window.end)}"
    )


def _in_window(moment: datetime, window: ResolvedWindow) -> bool:
    """Whether `moment` falls inside `window`, both bounds inclusive."""
    if window.start is not None and moment < window.start:
        return False
    return not (window.end is not None and moment > window.end)


def _fetch_target_service_logs() -> list[str]:
    response = httpx.get(f"{settings.target_service_url}/logs", timeout=10.0)
    response.raise_for_status()
    logs: list[str] = response.json()
    return logs


def _fetch_target_service_metrics() -> list[MetricBucket]:
    response = httpx.get(f"{settings.target_service_url}/metrics", timeout=10.0)
    response.raise_for_status()
    return [MetricBucket.model_validate(bucket) for bucket in response.json()]


def get_log_lines(alert_time: str | None = None,
                  window_start: str | None = None,
                  window_end: str | None = None,
                  filters: str | None = None,
                  bucket_ids: list[str] | None = None,
                  fetch: FetchLogs = _fetch_target_service_logs) -> list[str]:
    """Returns the Target Service's log lines for one window of an incident.

    Phase two of spec §16's two-phase retrieval: `bucket_ids` scopes retrieval
    to the minutes a metrics summary flagged. Windowing follows
    `resolve_log_window`, and a clamped window is announced in a leading
    notice line rather than silently returning less than was asked for.

    This is the public seam the `@mcp.tool()` wrapper in `server.py`
    delegates to. It lives here rather than on the decorated function because
    a `Callable`-typed default parameter - the `fetch` injection point - breaks
    FastMCP's JSON-schema generation (verified directly:
    `pydantic.errors.PydanticInvalidForJsonSchema: Cannot generate a
    JsonSchema for core_schema.CallableSchema`).

    `filters` matches the tool's eventual shape (§16 field-level filtering)
    but isn't acted on yet - no caller supplies one until the ReAct loop
    exists to drive it.
    """
    lines = fetch()
    window = resolve_log_window(alert_time, window_start, window_end)

    if window.start is None and window.end is None and not bucket_ids:
        return lines

    selected = [
        line
        for line in lines
        # A line with no parseable timestamp cannot be shown to fall inside
        # the window, so a windowed call drops it rather than guessing.
        if (moment := _parse_log_timestamp(line)) is not None
        and _in_window(moment, window)
        and (not bucket_ids or to_iso_minute(moment) in bucket_ids)
    ]

    return [_clamp_notice(window), *selected] if window.clamped else selected


def get_metrics_summary(alert_time: str | None = None,
                        window_start: str | None = None,
                        window_end: str | None = None,
                        fetch: FetchMetrics = _fetch_target_service_metrics
                        ) -> list[MetricBucket]:
    """Returns per-minute aggregated metrics for one window of an incident.

    Phase one of spec §16's two-phase retrieval: cheap enough to read whole,
    it shows the incident's shape - which minutes are anomalous, and whether
    error rate or latency moved - so a caller can pick the buckets worth
    pulling raw log lines for. Windowing follows `resolve_metrics_window`;
    the `fetch` seam is here for the same reason as in `get_log_lines`.
    """
    buckets = fetch()
    window = resolve_metrics_window(alert_time, window_start, window_end)

    if window.start is None and window.end is None:
        return buckets

    return [
        bucket for bucket in buckets if _in_window(parse_iso(bucket.bucket_id), window)
    ]
