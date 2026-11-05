"""A service's per-minute metrics, read from whatever monitors it.

The port the read tier reads minute buckets through, and the Prometheus adapter
behind it. What travels upwards is Argus's own `MetricBucket`; a vendor's
query language, envelope and errors stop at the adapter that speaks them.
"""

from metrics_source.minutes import (
    MetricsSettings,
    MetricsSource,
    MetricsUnavailable,
    RuleSeries,
)
from metrics_source.prometheus_adapter import is_a_latency, is_the_error_rate

__all__ = [
    "MetricsSettings",
    "MetricsSource",
    "MetricsUnavailable",
    "RuleSeries",
    "is_a_latency",
    "is_the_error_rate",
]
