"""A service's minutes, as whatever monitors it reports them.

The port's own vocabulary lives here rather than beside the adapter, so that
naming what a source needs never costs importing the vendor it talks to.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from argus_core import SettingsSlice
from argus_core.models import MetricBucket, WorseWhen


@dataclass(frozen=True)
class RuleSeries:
    """The series a paging rule evaluates, as the source is asked for it: the
    rule's own query, and which side of its threshold is worse.

    Carried down from whoever read the rule, so that the source reads one more
    series without learning what a rule is.
    """

    query: str
    worse_when: WorseWhen


class MetricsSource(Protocol):
    """What Argus needs from whatever monitors a service: its minute buckets
    between two instants, chronological, one per minute - and, where a rule's
    series is named, that series' reading on each minute it answers for.

    A `Protocol` so that a test doubling it has something introspectable, and
    so that the read tier names the port rather than any vendor behind it.
    Raises `MetricsUnavailable` where the source cannot be read - an empty list
    already means a window nobody heard from. The rule's series is not part of
    that promise: a source that cannot read it leaves the readings off and
    serves the window.
    """

    def __call__(self,
                 started_at: datetime,
                 ended_at: datetime,
                 rule_series: RuleSeries | None = None) -> list[MetricBucket]: ...


class MetricsSettings(SettingsSlice):
    """Where the metrics source answers, and nothing else.

    A base URL rather than a host, so that the path after it is always the
    vendor's own: a real Prometheus at its root, or a stand-in mounted under a
    prefix, are the same adapter aimed differently.
    """

    prometheus_base_url: str


class MetricsUnavailable(Exception):
    """The metrics source could not be read.

    An exception rather than an empty window, because an empty window already
    means something - a service nobody heard from - and "nobody could ask" is
    a different answer.
    """
