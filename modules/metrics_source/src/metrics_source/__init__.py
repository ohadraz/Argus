"""A service's per-minute metrics, read from whatever monitors it.

The port the read tier reads minute buckets through, and asks what a rule's
series measures through, and the Prometheus adapter behind it. What travels
upwards is Argus's own `MetricBucket` and `SeriesKind`; a vendor's query
language, envelope and errors stop at the adapter that speaks them.

The adapter is not exported here. It is built where the read server is wired,
and everything else is handed the port.
"""

from metrics_source.minutes import (
    Measure,
    MetricsSettings,
    MetricsSource,
    MetricsUnavailable,
    SeriesClassifier,
    SeriesKind,
)

__all__ = [
    "Measure",
    "MetricsSettings",
    "MetricsSource",
    "MetricsUnavailable",
    "SeriesClassifier",
    "SeriesKind"
]
