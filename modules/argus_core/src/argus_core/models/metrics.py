from __future__ import annotations

from pydantic import BaseModel


class MetricBucket(BaseModel):
    """One minute of pre-aggregated service metrics (spec §16, phase one).

    `bucket_id` is the bucket's minute in wire format, per
    `argus_core.timestamps.to_iso_minute` - the same string a log line of that
    minute yields, so the earliest anomalous bucket's id is directly usable as
    the onset a `get_log_lines` window is anchored on, with no separate id
    scheme to keep in sync.

    The resource fields are gauges where the rest of the bucket is rates and
    quantiles, so each says how its minute's single value is taken from the
    instants within it. `memory_used_bytes` is the minute's **maximum**: what
    matters about memory is the peak that could have breached the limit, not
    the average that hid it. `memory_limit_bytes` and
    `process_start_time_seconds` are the minute's **last observed** value, each
    describing a configuration in force rather than a quantity accumulated - so
    a minute containing a restart reports the new process.

    `memory_limit_bytes` is nullable because a deployment imposing no limit is
    ordinary, and zero would make "no limit set" indistinguishable from "no
    memory available". Usage and limit are carried as absolute byte counts
    rather than as a ratio: the ratio is derivable from the pair, the pair is
    not derivable from the ratio, and forecasting when usage reaches the limit
    needs both.
    """

    bucket_id: str
    error_rate: float
    p50_ms: int
    p95_ms: int
    request_volume: int
    memory_used_bytes: int
    memory_limit_bytes: int | None = None
    process_start_time_seconds: float
