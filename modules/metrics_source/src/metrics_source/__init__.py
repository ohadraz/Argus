"""A service's per-minute metrics, read from whatever monitors it.

The port the read tier reads minute buckets through, and the Prometheus adapter
behind it. What travels upwards is Argus's own `MetricBucket`; a vendor's
query language, envelope and errors stop at the adapter that speaks them.
"""

from metrics_source.minutes import MetricsSettings, MetricsSource, MetricsUnavailable

__all__ = [
    "MetricsSettings",
    "MetricsSource",
    "MetricsUnavailable",
]
