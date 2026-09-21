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

    `p99_ms` is the slowest one request in a hundred, and it is required where
    `cache_hit_ratio` below is not. The difference is what an absence would
    mean: a deployment consulting no cache genuinely has no hit ratio, where no
    deployment lacks a tail - so a missing `p99_ms` would be a measurement that
    went astray rather than a fact about the service, and nothing should be
    invited to read it as one. It is carried beside the other two quantiles
    rather than derived from them, because a fault reaching a few requests in a
    hundred moves it and moves neither of them, which is the only reason to
    report a third quantile at all.

    `cache_hit_ratio` is the share of the minute's lookups a cache answered,
    and it is a ratio where memory is a pair - unlike a limit there is no
    threshold whose crossing anybody forecasts, so what a reader asks of it is
    simply how much of the work the cache is carrying. Nullable for the reason
    below: a service consulting no cache has none, and zero is what a cache
    answering nothing reports. A reader has to be able to tell a deployment
    without a fast path from one whose fast path has gone.

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
    p99_ms: int
    request_volume: int
    memory_used_bytes: int
    memory_limit_bytes: int | None = None
    process_start_time_seconds: float
    cache_hit_ratio: float | None = None
