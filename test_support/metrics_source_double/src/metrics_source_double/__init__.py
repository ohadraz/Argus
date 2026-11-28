"""The metrics source, held in memory: a double of its ports, for suites.

A second adapter of `metrics_source`'s ports, and never one a process runs: a
window read from memory would have Argus judge a mitigation by minutes nobody
measured, so it lives where nothing that ships can install it. It is held to
the ports by their own suite, which runs it beside the vendor's adapter over
one seed and asks both the same questions.

`MetricsState` is the seed - the minutes the source reports, each a
`MetricBucket`, and every series beyond them it can read as a `HeldSeries` -
and `InMemoryMetrics` answers both ports from it: called, the window;
`classify`, every query as measuring something else, in no unit.
"""

from __future__ import annotations

from metrics_source_double.in_memory import InMemoryMetrics
from metrics_source_double.state import HeldSeries, MetricsState

__all__ = [
    "HeldSeries",
    "InMemoryMetrics",
    "MetricsState"
]
