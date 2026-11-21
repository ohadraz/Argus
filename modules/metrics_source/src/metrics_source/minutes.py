"""A service's minutes, as whatever monitors it reports them.

The port's own vocabulary lives here rather than beside the adapter, so that
naming what a source needs never costs importing the vendor it talks to.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from core import SettingsSlice
from core.models import MetricBucket, RuleSeries, SeriesQuery, Unit


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


class Measure(StrEnum):
    """What a series measures, as far as anything that reads the incident
    needs to know: the error rate every reader is already given, a latency
    every reader is already given at its levels, or something else."""

    ERROR_RATE = "error_rate"
    LATENCY = "latency"
    OTHER = "other"


@dataclass(frozen=True)
class SeriesKind:
    """What a rule's series is, said by the source that runs its query.

    `unit` is the unit the query's own metric carries, and `None` where the
    query does something to it that may change the unit, or the metric carries
    none - unknown, never guessed.
    """

    measures: Measure
    unit: Unit | None


class SeriesClassifier(Protocol):
    """How the read tier learns what a rule's series measures.

    The query is in the source's own language, so only the source's adapter
    can say what it means. A `Protocol` so a test stands it in with
    `create_autospec`; bound where the process starts to the one adapter this
    deployment reads metrics through. Never raises: a query it cannot read
    measures something else, in no unit it can say.
    """

    def __call__(self, query: SeriesQuery, /) -> SeriesKind: ...


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
