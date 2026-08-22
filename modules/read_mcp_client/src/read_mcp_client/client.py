from __future__ import annotations

from typing import cast

from argus_core.config import get_settings
from argus_core.mcp_transport import call_mcp_tool
from argus_core.models.metrics import MetricBucket


def get_log_lines(alert_time: str | None = None,
                  window_start: str | None = None,
                  window_end: str | None = None,
                  filters: str | None = None,
                  bucket_ids: list[str] | None = None) -> list[str]:
    """Reads the Target Service's log lines for one window of an incident.

    Phase two of spec §16's two-phase retrieval - see `argus-read-mcp`'s
    `get_log_lines` for how the window is derived and clamped. Times are
    ISO-8601 strings, and `bucket_ids` are ids taken from a
    `get_metrics_summary` result.
    """
    settings = get_settings()
    result = call_mcp_tool(
        f"{settings.read_mcp_url}/mcp",
        "get_log_lines",
        alert_time=alert_time,
        window_start=window_start,
        window_end=window_end,
        filters=filters,
        bucket_ids=bucket_ids,
    )
    return cast(list[str], result)


def get_metrics_summary(alert_time: str | None = None,
                        window_start: str | None = None,
                        window_end: str | None = None) -> list[MetricBucket]:
    """Reads per-minute aggregated metrics for one window of an incident.

    Phase one of spec §16's two-phase retrieval: the buckets it returns show
    which minutes are anomalous, and their ids scope a follow-up
    `get_log_lines(bucket_ids=...)` to just those minutes.
    """
    settings = get_settings()
    result = call_mcp_tool(
        f"{settings.read_mcp_url}/mcp",
        "get_metrics_summary",
        alert_time=alert_time,
        window_start=window_start,
        window_end=window_end)
    return [MetricBucket.model_validate(bucket) for bucket in cast(list[object], result)]
