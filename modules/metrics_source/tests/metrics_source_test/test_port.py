"""The metrics source's ports, as every adapter of them answers.

What the ports promise, asked of each adapter over one seed: the Prometheus
adapter against a Prometheus served in-process (`framework.prometheus_world`),
and the in-memory double (`metrics_source_double`). A promise one of them keeps
and the other does not fails here, so the double cannot drift from the ports,
and the ports name nothing only Prometheus's wire could answer.

The promises and nothing beyond them. Which PromQL a minute's fields are read
by, what a query measures and the unit its metric's name carries, and how a
sample that is no number is read, are the wire suites'
(`test_prometheus_adapter.py`, `test_prometheus_units.py`).
"""

from __future__ import annotations

import math
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol

import pytest
from argus_testkit import Scenario, an_error_was_raised, attempting, the_answer_was
from core import to_iso
from core.models import MetricBucket, RuleLine, RuleReading, RuleSeries, SeriesQuery
from metrics_source import Measure, MetricsSource, MetricsUnavailable, SeriesKind
from metrics_source.prometheus_adapter import QUERIES, buckets_between, what_the_series_is
from metrics_source_double import HeldSeries, InMemoryMetrics, MetricsState

from metrics_source_test.framework import PrometheusWorld, prometheus_settings

_A_MINUTE = timedelta(minutes=1)

# Five minutes in a row, each told apart by every figure it carries.
THE_FIRST_MINUTE = datetime(2026, 11, 28, 9, 30, tzinfo=UTC)
MINUTES = tuple(THE_FIRST_MINUTE + _A_MINUTE * at for at in range(5))
PART_OF_A_MINUTE = timedelta(seconds=20)

SOME_RULE_QUERY = SeriesQuery("avg(some_confident_ratio)")
A_QUERY_THE_SOURCE_CANNOT_READ = SeriesQuery("this is not a query (")
SOME_LINE = RuleLine(at=0.05, fires_on_it=False)
SOME_RULE_SERIES = RuleSeries(query=SOME_RULE_QUERY, worse_when="above", line=SOME_LINE)
A_RULE_SERIES_NOT_HELD = RuleSeries(query=A_QUERY_THE_SOURCE_CANNOT_READ, worse_when="below")


def _a_minute(at: int) -> MetricBucket:
    """The minute `at` minutes after the first, every figure its own - here
    rather than among the helpers below, since the cases' parameters are built
    from it. The odd minutes keep no cache and set no limit: absent stays
    absent."""
    return MetricBucket(
        bucket_id=to_iso(MINUTES[at]),
        error_rate=0.0125 * (at + 1),
        p50_ms=40 + at,
        p95_ms=120 + at,
        p99_ms=300 + at,
        request_volume=1000 + at,
        memory_used_bytes=200_000_000 + at,
        memory_limit_bytes=None if at % 2 else 512_000_000,
        process_start_time_seconds=1_764_316_800.0 + at,
        cpu_used_cores=0.25 + at / 100,
        cpu_limit_cores=None if at % 2 else 2.0,
        cache_hit_ratio=None if at % 2 else 0.875 - at / 100
    )


class _StandsUp(Protocol):
    def __call__(self, state: MetricsState, *, unreachable: bool = ...) -> MetricsSource:
        ...


class _StandsUpAClassifier(Protocol):
    def __call__(self,
                 state: MetricsState,
                 *,
                 unreachable: bool = ...) -> Callable[[SeriesQuery], SeriesKind]:
        ...


def _in_memory(state: MetricsState, *, unreachable: bool = False) -> MetricsSource:
    return InMemoryMetrics(state, unreachable=unreachable)


def _prometheus(state: MetricsState, *, unreachable: bool = False) -> MetricsSource:
    world = PrometheusWorld(state, unreachable=unreachable)

    def source(started_at: datetime,
               ended_at: datetime,
               rule_series: RuleSeries | None = None) -> list[MetricBucket]:
        return buckets_between(started_at, ended_at, prometheus_settings(), world.get,
                               rule_series)

    return source


def _the_in_memory_classifier(state: MetricsState,
                              *,
                              unreachable: bool = False) -> Callable[[SeriesQuery], SeriesKind]:
    return InMemoryMetrics(state, unreachable=unreachable).classify


def _the_prometheus_classifier(state: MetricsState,
                               *,
                               unreachable: bool = False) -> Callable[[SeriesQuery], SeriesKind]:
    """Reads no source at all, so there is nothing for `unreachable` to stop."""
    return what_the_series_is


EVERY_ADAPTER = pytest.mark.parametrize("stand_up", [
    pytest.param(_in_memory, id="in-memory"),
    pytest.param(_prometheus, id="prometheus")
])

EVERY_CLASSIFIER = pytest.mark.parametrize("stand_up", [
    pytest.param(_the_in_memory_classifier, id="in-memory"),
    pytest.param(_the_prometheus_classifier, id="prometheus")
])


@pytest.mark.unit
@EVERY_ADAPTER
def test_the_minutes_of_a_window_are_those_the_source_holds_in_it_in_order(
    stand_up: _StandsUp
) -> None:
    # Held out of order, so an adapter answering in the order it holds them
    # would be caught.
    Scenario() \
        .given(source := stand_up(_a_source_holding(2, 0, 1))) \
        .when(lambda: source(MINUTES[0], MINUTES[2] + PART_OF_A_MINUTE)) \
        .then(the_answer_was([_a_minute(0), _a_minute(1), _a_minute(2)]))


@pytest.mark.unit
@EVERY_ADAPTER
@pytest.mark.parametrize(("started_at", "ended_at", "minutes"), [
    pytest.param(MINUTES[1], MINUTES[3], [1, 2, 3], id="on-the-minutes"),
    pytest.param(MINUTES[1] + PART_OF_A_MINUTE, MINUTES[3] + PART_OF_A_MINUTE, [2, 3],
                 id="inside-the-minutes")
])
def test_a_window_runs_from_the_first_minute_begun_in_it_to_the_one_it_ends_in(
    stand_up: _StandsUp, started_at: datetime, ended_at: datetime, minutes: list[int]
) -> None:
    # A minute begun before the window starts is not in it; the one its end
    # falls in is, finished or not.
    Scenario() \
        .given(source := stand_up(_a_source_holding(0, 1, 2, 3, 4))) \
        .when(lambda: source(started_at, ended_at)) \
        .then(the_answer_was([_a_minute(at) for at in minutes]))


@pytest.mark.unit
@EVERY_ADAPTER
def test_a_window_nobody_heard_from_is_empty(stand_up: _StandsUp) -> None:
    Scenario() \
        .given(source := stand_up(_a_source_holding(0, 1))) \
        .when(lambda: source(MINUTES[3], MINUTES[4])) \
        .then(the_answer_was([]))


@pytest.mark.unit
@EVERY_ADAPTER
@pytest.mark.parametrize(("started_at", "ended_at"), [
    pytest.param(MINUTES[1] + PART_OF_A_MINUTE, MINUTES[1] + 2 * PART_OF_A_MINUTE,
                 id="inside-one-minute"),
    pytest.param(MINUTES[2], MINUTES[0], id="ended-before-it-began")
])
def test_a_window_with_no_whole_minute_in_it_is_empty(
    stand_up: _StandsUp, started_at: datetime, ended_at: datetime
) -> None:
    # The first minute begun in the window comes after the one its end falls
    # in, so none is in it - an answer, not a source that could not give one.
    Scenario() \
        .given(source := stand_up(_a_source_holding(0, 1, 2))) \
        .when(lambda: source(started_at, ended_at)) \
        .then(the_answer_was([]))


@pytest.mark.unit
@EVERY_ADAPTER
def test_a_source_nothing_reaches_is_unavailable_rather_than_empty(stand_up: _StandsUp) -> None:
    Scenario() \
        .given(source := stand_up(_a_source_holding(0, 1), unreachable=True)) \
        .when(attempting(lambda: source(MINUTES[0], MINUTES[1]))) \
        .then(an_error_was_raised(MetricsUnavailable))


@pytest.mark.unit
@EVERY_ADAPTER
def test_a_rule_s_series_is_read_on_each_minute_it_answers_for(stand_up: _StandsUp) -> None:
    # Read on the second and third minutes, and not the first.
    some_readings = ((MINUTES[1], 0.0625), (MINUTES[2], 0.03125))

    Scenario() \
        .given(source := stand_up(MetricsState(
            minutes=tuple(_a_minute(at) for at in (0, 1, 2)),
            series=(HeldSeries(query=SOME_RULE_QUERY, readings=some_readings),)
        ))) \
        .when(lambda: source(MINUTES[0], MINUTES[2], SOME_RULE_SERIES)) \
        .then(the_answer_was([
            _a_minute(0),
            *(_a_minute(at).model_copy(update={"rule_reading": RuleReading(
                value=value, worse_when=SOME_RULE_SERIES.worse_when, line=SOME_LINE
            )}) for at, (_, value) in zip((1, 2), some_readings, strict=True))
        ]))


@pytest.mark.unit
@EVERY_ADAPTER
def test_a_rule_s_series_the_source_cannot_read_leaves_the_window_served_without_it(
    stand_up: _StandsUp
) -> None:
    Scenario() \
        .given(source := stand_up(_a_source_holding(0, 1))) \
        .when(lambda: source(MINUTES[0], MINUTES[1], A_RULE_SERIES_NOT_HELD)) \
        .then(the_answer_was([_a_minute(0), _a_minute(1)]))


@pytest.mark.unit
@EVERY_CLASSIFIER
@pytest.mark.parametrize("unreachable", [
    pytest.param(False, id="reachable"),
    pytest.param(True, id="unreachable")
])
def test_a_query_the_source_cannot_read_measures_something_else_in_no_unit(
    stand_up: _StandsUpAClassifier, unreachable: bool
) -> None:
    # Never raised: whatever the source says, a query is classified.
    Scenario() \
        .given(classify := stand_up(_a_source_holding(0), unreachable=unreachable)) \
        .when(lambda: classify(A_QUERY_THE_SOURCE_CANNOT_READ)) \
        .then(the_answer_was(SeriesKind(measures=Measure.OTHER, unit=None)))


@pytest.mark.unit
@pytest.mark.parametrize(("stand_up", "state"), [
    pytest.param(_in_memory,
                 MetricsState(minutes=(_a_minute(0).model_copy(update={"error_rate": math.nan}),)),
                 id="in-memory-a-figure-that-is-no-number"),
    pytest.param(_in_memory,
                 MetricsState(minutes=(), series=(
                     HeldSeries(query=SOME_RULE_QUERY, readings=((MINUTES[0], math.nan),)),
                 )),
                 id="in-memory-a-reading-that-is-no-number"),
    pytest.param(_in_memory,
                 MetricsState(minutes=(_a_minute(0).model_copy(update={"rule_reading": RuleReading(
                     value=SOME_LINE.at, worse_when=SOME_RULE_SERIES.worse_when
                 )}),)),
                 id="in-memory-a-minute-carrying-a-rule-s-reading"),
    pytest.param(_prometheus,
                 MetricsState(minutes=(), series=(
                     HeldSeries(query=SeriesQuery(QUERIES["error_rate"]), readings=()),
                 )),
                 id="prometheus-a-series-held-under-a-field-s-own-query")
])
def test_a_seed_no_source_could_report_is_refused(stand_up: _StandsUp,
                                                  state: MetricsState) -> None:
    # Refused when built rather than answered: a stand-in answering it would
    # answer what the adapter never could, and a suite seeded so would pass
    # over a source that does not exist.
    Scenario() \
        .when(attempting(lambda: stand_up(state))) \
        .then(an_error_was_raised(ValueError))


def _a_source_holding(*minutes: int) -> MetricsState:
    """A source reporting these minutes, in this order, and no series beyond."""
    return MetricsState(minutes=tuple(_a_minute(at) for at in minutes))
