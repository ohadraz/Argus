"""What a metrics source holds before anybody asks it anything.

The seed both adapters in the ports' suite are built from: the double reads it
directly, and the suite's Prometheus stand-in serves it in Prometheus's own
shapes. Every value is frozen and every collection a tuple, so a seed is the
same seed whoever holds it and however many sources are built from it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from core.models import MetricBucket, SeriesQuery


@dataclass(frozen=True)
class HeldSeries:
    """One series beyond a minute's own fields that the source can read - a
    rule's, asked by its query - and its value on each minute it answers for,
    each against the minute it is of."""

    query: SeriesQuery
    readings: tuple[tuple[datetime, float], ...]


@dataclass(frozen=True)
class MetricsState:
    """Everything the source holds.

    `minutes` is every minute it reports, in any order, each as a bucket with
    no rule's reading on it: which rule's series is read is the caller's to
    say. `series` is every series beyond those it can read.

    What a query measures is not held. The source's language is read by its
    adapter alone, so nothing a suite could seed here is something both
    adapters can be asked; a consumer that needs a query read stands the
    classifier in with `create_autospec`.
    """

    minutes: tuple[MetricBucket, ...]
    series: tuple[HeldSeries, ...] = ()
