from __future__ import annotations

from argus_core.config import get_settings
from argus_core.models.change_event import ChangeEvent
from argus_core.models.metrics import MetricBucket
from mcp.server.fastmcp import FastMCP

from read_mcp_server import retrieval

settings = get_settings()
mcp = FastMCP(
    "argus-read-mcp",
    host=settings.read_mcp_host,
    port=settings.read_mcp_port,
)


@mcp.tool()
def get_log_lines(alert_time: str | None = None,
                  window_start: str | None = None,
                  window_end: str | None = None,
                  filters: str | None = None) -> list[str]:
    """Returns the Target Service's log lines for one window of an incident.

    Phase two of the Two-phase retrieval:
    1. call `get_metrics_summary` first, to find the minute the incident
       started,
    2. then ask for a window anchored on that onset - reaching back before it,
       since the cause lands in a minute that still looks healthy.

    `alert_time` is the incident's `T0` and derives the window from configured
    lookback/lookahead;
    `window_start`/`window_end` override it and are clamped to the configured 
    maximum span, with a leading notice line when that happens.
    All times are ISO-8601 strings, since an `@mcp.tool()` parameter must be 
    JSON-schema-representable. Passing nothing returns the whole log, which is 
    what `agent_investigator` still does.
    `filters` matches the tool's eventual shape (§16 field-level filtering)
    but isn't acted on yet. The behavior itself - and the `fetch` injection
    seam a `Callable` default cannot have on a decorated function - lives in
    `retrieval.get_log_lines`; this is registration only."""
    return retrieval.get_log_lines(alert_time, window_start, window_end, filters)


@mcp.tool()
def get_metrics_summary(alert_time: str | None = None,
                        window_start: str | None = None,
                        window_end: str | None = None) -> list[MetricBucket]:
    """Returns per-minute aggregated metrics for one window of an incident.

    Phase one of Two-phase retrieval: cheap enough to read whole, it shows the 
    incident's shape - which minutes are anomalous, and whether error rate or 
    latency moved - so a caller can locate the onset and anchor a log window 
    on it.
    Windowing works exactly as in `get_log_lines`; the behavior lives in
    `retrieval.get_metrics_summary`."""
    return retrieval.get_metrics_summary(alert_time, window_start, window_end)


@mcp.tool()
def get_change_events(service: str,
                      window_start: str,
                      window_end: str) -> list[ChangeEvent]:
    """Returns what changed on a service within one window.

    The third retrieval channel. Metrics locate the minute an incident started
    and logs say what the service said about it; this answers "what changed" -
    which is what a cause is. Ask over a window far wider than any log window:
    a change can precede the symptoms it causes by an unbounded lag, and
    changes are sparse where log lines are not.

    The window is explicit and required - unlike the other two tools, there is
    no alert-time default, because how far back a cause may lie is the
    caller's judgement and not retrieval's.

    Raises rather than returning nothing when the change source cannot be
    reached: "nothing changed" is a conclusion, and an outage is not evidence
    for it. The behavior, and the source injection seam, live in
    `retrieval.get_change_events`; this is registration only."""
    return retrieval.get_change_events(service, window_start, window_end)


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
