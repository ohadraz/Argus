from __future__ import annotations

from argus_core.config import get_settings
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
                  filters: str | None = None,
                  bucket_ids: list[str] | None = None) -> list[str]:
    """Returns the Target Service's log lines for one window of an incident.

    Two-phase retrieval: 
    1. call `get_metrics_summary` first, 
    2. then pass the ids of the anomalous buckets as `bucket_ids` to read only 
       those minutes.
    
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
    return retrieval.get_log_lines(alert_time, window_start, window_end, filters, bucket_ids)


@mcp.tool()
def get_metrics_summary(alert_time: str | None = None,
                        window_start: str | None = None,
                        window_end: str | None = None) -> list[MetricBucket]:
    """Returns per-minute aggregated metrics for one window of an incident.

    Two-phase retrieval: cheap enough to read whole, it shows the incident's 
    shape - which minutes are anomalous, and whether error rate or latency 
    moved - so a caller can pick the buckets worth pulling raw log lines for. 
    Windowing works exactly as in `get_log_lines`; the behavior lives in 
    `retrieval.get_metrics_summary`."""
    return retrieval.get_metrics_summary(alert_time, window_start, window_end)


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
