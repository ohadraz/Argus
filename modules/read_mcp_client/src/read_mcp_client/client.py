from __future__ import annotations

from typing import cast

from argus_core.config import get_settings
from argus_core.mcp_transport import call_mcp_tool
from argus_core.models.change_event import ChangeEvent
from argus_core.models.metrics import MetricBucket


def get_log_lines(alert_time: str | None = None,
                  window_start: str | None = None,
                  window_end: str | None = None,
                  filters: str | None = None) -> list[str]:
    """Reads the Target Service's log lines for one window of an incident.

    Phase two of spec §16's two-phase retrieval - see `argus-read-mcp`'s
    `get_log_lines` for how the window is derived and clamped. Times are
    ISO-8601 strings. Retrieval is by window only: a window anchored on the
    onset a `get_metrics_summary` result located, reaching back before it.
    """
    settings = get_settings()
    result = call_mcp_tool(
        f"{settings.read_mcp_url}/mcp",
        "get_log_lines",
        alert_time=alert_time,
        window_start=window_start,
        window_end=window_end,
        filters=filters,
    )
    return cast(list[str], result)


def get_metrics_summary(alert_time: str | None = None,
                        window_start: str | None = None,
                        window_end: str | None = None) -> list[MetricBucket]:
    """Reads per-minute aggregated metrics for one window of an incident.

    Phase one of spec §16's two-phase retrieval: the buckets it returns show
    which minutes are anomalous, and the earliest anomalous one gives the
    onset a follow-up `get_log_lines` window is anchored on.
    """
    settings = get_settings()
    result = call_mcp_tool(
        f"{settings.read_mcp_url}/mcp",
        "get_metrics_summary",
        alert_time=alert_time,
        window_start=window_start,
        window_end=window_end)
    return [MetricBucket.model_validate(bucket) for bucket in cast(list[object], result)]


def get_change_events(service: str,
                      window_start: str,
                      window_end: str) -> list[ChangeEvent]:
    """Reads what changed on a service within one window of an incident.

    The third retrieval channel (spec §16). Its window is deliberately far
    wider than a log window's: a deploy or a flag flip can precede the symptoms
    it causes by an unbounded lag, and there are only ever a handful of changes
    to read where there would be millions of log lines.

    Raises rather than returning an empty list when the change source cannot be
    reached, because "nothing changed" is a conclusion a caller will act on.
    """
    settings = get_settings()
    result = call_mcp_tool(
        f"{settings.read_mcp_url}/mcp",
        "get_change_events",
        service=service,
        window_start=window_start,
        window_end=window_end,
    )
    return [ChangeEvent.model_validate(change) for change in cast(list[object], result)]
