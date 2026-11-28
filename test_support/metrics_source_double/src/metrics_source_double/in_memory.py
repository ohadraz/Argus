"""Both metrics-source ports, answered from memory.

Built from a `MetricsState`, and changed by nothing: the ports only read.
Everything it says is what the ports promise and their suite pins over both
adapters: the minutes a window holds, chronological, from the first to begin
at or after its start to the one its end falls in; a rule's series read on the
minutes it answers for, and left off - never refused - where it cannot be
read; and every query measuring something else, in no unit it can say, since
it reads no query language at all.

A seed no source could report is refused when the double is built, rather
than answered: a figure that is no number (a source's NaN is no reading, and
never reaches a bucket), and a minute already carrying a rule's reading (which
rule's series is read is the caller's).
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Final

from core import parse_iso
from core.models import MetricBucket, RuleReading, RuleSeries, SeriesQuery
from metrics_source import Measure, MetricsUnavailable, SeriesKind

from metrics_source_double.state import MetricsState

_A_MINUTE: Final = timedelta(minutes=1)


class InMemoryMetrics:
    """A metrics source held in memory: called, a window's minutes; asked to
    `classify`, what a query measures.

    `unreachable` builds a source nothing reaches: every window is refused.
    Classifying reads no source, so it answers whatever `unreachable` says.
    """

    def __init__(self, state: MetricsState, *, unreachable: bool = False) -> None:
        _refuse_what_no_source_holds(state)
        self._minutes = sorted(state.minutes, key=lambda bucket: parse_iso(bucket.bucket_id))
        self._series = {held.query: dict(held.readings) for held in state.series}
        self._unreachable = unreachable

    def __call__(self,
                 started_at: datetime,
                 ended_at: datetime,
                 rule_series: RuleSeries | None = None) -> list[MetricBucket]:
        if self._unreachable:
            raise MetricsUnavailable("the source is not reachable")

        first = _the_first_minute_at_or_after(started_at)
        last = _the_minute_of(ended_at)
        readings = self._series.get(rule_series.query, {}) if rule_series is not None else {}

        return [
            _with_its_reading(bucket, rule_series, readings)
            for bucket in self._minutes
            if first <= parse_iso(bucket.bucket_id) <= last
        ]

    def classify(self, query: SeriesQuery, /) -> SeriesKind:
        """Something else, in no unit it can say: this source reads no query."""
        return SeriesKind(measures=Measure.OTHER, unit=None)


def _refuse_what_no_source_holds(state: MetricsState) -> None:
    for bucket in state.minutes:
        if bucket.rule_reading is not None:
            raise ValueError(f"minute [{bucket.bucket_id}] carries a rule's reading: "
                             f"the caller's series says which")

        figures = bucket.model_dump(exclude={"bucket_id", "rule_reading"}).values()

        if any(isinstance(figure, float) and not math.isfinite(figure) for figure in figures):
            raise ValueError(f"minute [{bucket.bucket_id}] holds a figure that is no number")

    for held in state.series:
        if any(not math.isfinite(value) for _, value in held.readings):
            raise ValueError(f"series [{held.query}] holds a reading that is no number")


def _with_its_reading(bucket: MetricBucket,
                      rule_series: RuleSeries | None,
                      readings: dict[datetime, float]) -> MetricBucket:
    """The minute, carrying the rule's reading on it where the series answers
    for it."""
    value = readings.get(parse_iso(bucket.bucket_id))

    if rule_series is None or value is None:
        return bucket

    return bucket.model_copy(update={"rule_reading": RuleReading(
        value=value, worse_when=rule_series.worse_when, line=rule_series.line
    )})


def _the_minute_of(moment: datetime) -> datetime:
    return moment.replace(second=0, microsecond=0)


def _the_first_minute_at_or_after(moment: datetime) -> datetime:
    minute = _the_minute_of(moment)

    return minute if minute == moment else minute + _A_MINUTE
