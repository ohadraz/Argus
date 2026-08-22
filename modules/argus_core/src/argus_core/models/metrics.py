from __future__ import annotations

from pydantic import BaseModel


class MetricBucket(BaseModel):
    """One minute of pre-aggregated service metrics (spec §16, phase one).

    `bucket_id` is the bucket's minute in wire format, per
    `argus_core.timestamps.to_iso_minute` - the same string a log line of that
    minute yields, so the earliest anomalous bucket's id is directly usable as
    the onset a `get_log_lines` window is anchored on, with no separate id
    scheme to keep in sync.
    """

    bucket_id: str
    error_rate: float
    p50_ms: int
    p95_ms: int
    request_volume: int
