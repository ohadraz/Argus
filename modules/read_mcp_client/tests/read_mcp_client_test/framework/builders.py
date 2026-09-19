from __future__ import annotations

from datetime import datetime

TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
# The shop has been up since long before any window here. What matters about
# this field over the wire is that it survives the trip, not what it says.
DONT_CARE_STARTED_AT = 1_756_000_000.0


def an_iso_minute(minute: datetime) -> str:
    return minute.strftime(TIMESTAMP_FORMAT)


def a_metric_at(minute: datetime,
                error_rate: float = 0.01,
                p50_ms: int = 40,
                p95_ms: int = 200,
                requests_per_minute: int = 1000,
                memory_used_bytes: int = 440 * 1024**2,
                memory_limit_bytes: int = 2 * 1024**3,) -> dict[str, object]:
    return {
        "bucket_id": an_iso_minute(minute),
        "error_rate": error_rate,
        "p50_ms": p50_ms,
        "p95_ms": p95_ms,
        "request_volume": requests_per_minute,
        "memory_used_bytes": memory_used_bytes,
        "memory_limit_bytes": memory_limit_bytes,
        "process_start_time_seconds": DONT_CARE_STARTED_AT,
    }


def a_success_line_at(minute: datetime) -> str:
    return f"{an_iso_minute(minute)} INFO target-service: request succeeded"


def a_failure_line_at(minute: datetime) -> str:
    return f"{an_iso_minute(minute)} ERROR target-service: request failed"


def a_cause_line_at(minute: datetime) -> str:
    return (
        f"{an_iso_minute(minute)} WARN target-service: "
        "feature flag 'checkout-v2' toggled from 'off' to 'on'"
    )
