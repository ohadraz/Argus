"""Reading Prometheus - what is asked of it, and what its answer means.

What is injected is the HTTP call, so the request is built by the real adapter
and only Prometheus's answer is written. Whether that request reaches a real
Prometheus and parses there is the contract suite's business; what this pins is
the shape of the question and the reading of the answer.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx2
import pytest
from argus_core.models import MetricBucket
from argus_testkit import (
    Assertion,
    Kept,
    Scenario,
    all_of,
    an_error_was_raised,
    attempting,
    the_answer_was,
    the_error_mentioned,
)
from metrics_source.minutes import MetricsSettings, MetricsUnavailable
from metrics_source.prometheus_adapter import buckets_between

# Prometheus's own vocabulary, spelled out here rather than shared with the
# module under test: the assertion is that Argus speaks *these* words, and a
# constant imported from the speaker would agree with itself whatever it said.
THE_RANGE_QUERY_PATH = "/api/v1/query_range"
A_MINUTE_STEP = "60s"

# What Argus asks for each field of a bucket, written out in full for the same
# reason. These are also the expressions the demo app's stand-in answers, so a
# change here is a change to a contract with a second repository.
QUERY_FOR = {
    "error_rate": (
        'sum(rate(http_requests_total{code=~"5.."}[1m]))'
        " / sum(rate(http_requests_total[1m]))"
    ),
    "p50_ms": 'max(http_request_duration_seconds{quantile="0.5"}) * 1000',
    "p95_ms": 'max(http_request_duration_seconds{quantile="0.95"}) * 1000',
    "p99_ms": 'max(http_request_duration_seconds{quantile="0.99"}) * 1000',
    "request_volume": "sum(increase(http_requests_total[1m]))",
    "memory_used_bytes": "max(max_over_time(process_resident_memory_bytes[1m]))",
    "memory_limit_bytes": "max(container_spec_memory_limit_bytes)",
    "process_start_time_seconds": "max(process_start_time_seconds)",
    "cpu_used_cores": "sum(rate(container_cpu_usage_seconds_total[1m]))",
    "cpu_limit_cores": 'sum(kube_pod_container_resource_limits{resource="cpu"})',
    "cache_hit_ratio": "avg(cache_hit_ratio)"
}

SOME_BASE_URL = "http://some-host:8080/prometheus"


@pytest.mark.unit
def test_every_question_is_put_to_prometheus_range_query_api() -> None:
    # The base URL is the setting's and the path after it is Prometheus's own,
    # which is what lets the same adapter be aimed at a real Prometheus or at a
    # stand-in mounted under a prefix. A minute step, because a minute is what a
    # bucket is.
    some_window_start = datetime(2026, 10, 4, 12, 0, tzinfo=UTC)
    some_window_end = some_window_start + timedelta(minutes=30)
    asked: Kept[httpx2.Request] = Kept()

    Scenario() \
        .when(
            lambda: buckets_between(
                some_window_start, some_window_end,
                settings=MetricsSettings(prometheus_base_url=SOME_BASE_URL),
                get=_a_prometheus_answering({}, asked=asked))
        ) \
        .then(
            _every_request_went_to(f"{SOME_BASE_URL}{THE_RANGE_QUERY_PATH}", asked),
            _every_request_asked(step=A_MINUTE_STEP, of=asked),
            _every_request_named(["query", "start", "end"], of=asked)
        )


@pytest.mark.unit
def test_a_minutes_samples_become_that_minutes_bucket() -> None:
    # A sample at `t` describes the minute that ended at `t` - Prometheus's own
    # convention for a `[1m]` range - so the bucket it fills is the one that
    # began a minute earlier. Each field comes from its own query; the
    # whole-number fields are rounded, because `* 1000` on a float answers
    # 119.99999999999999 for a latency the service measured as 120.
    some_minute = datetime(2026, 10, 4, 12, 0, tzinfo=UTC)
    its_end = (some_minute + timedelta(minutes=1)).timestamp()

    Scenario() \
        .given(
            prometheus := _a_prometheus_answering({
                QUERY_FOR["error_rate"]: [(its_end, "0.015")],
                QUERY_FOR["p50_ms"]: [(its_end, "120.00000000000001")],
                QUERY_FOR["p95_ms"]: [(its_end, "339.99999999999994")],
                QUERY_FOR["p99_ms"]: [(its_end, "610")],
                QUERY_FOR["request_volume"]: [(its_end, "1200")],
                QUERY_FOR["memory_used_bytes"]: [(its_end, "300000000")],
                QUERY_FOR["memory_limit_bytes"]: [(its_end, "512000000")],
                QUERY_FOR["process_start_time_seconds"]: [(its_end, "1759570000.25")],
                QUERY_FOR["cpu_used_cores"]: [(its_end, "0.75")],
                QUERY_FOR["cpu_limit_cores"]: [(its_end, "3")],
                QUERY_FOR["cache_hit_ratio"]: [(its_end, "0.9")]
            })
        ) \
        .when(
            lambda: buckets_between(
                some_minute, some_minute,
                settings=MetricsSettings(prometheus_base_url=SOME_BASE_URL),
                get=prometheus)
        ) \
        .then(
            the_answer_was([
                MetricBucket(
                    bucket_id="2026-10-04T12:00:00Z",
                    error_rate=0.015,
                    p50_ms=120,
                    p95_ms=340,
                    p99_ms=610,
                    request_volume=1200,
                    memory_used_bytes=300_000_000,
                    memory_limit_bytes=512_000_000,
                    process_start_time_seconds=1759570000.25,
                    cpu_used_cores=0.75,
                    cpu_limit_cores=3.0,
                    cache_hit_ratio=0.9
                )
            ])
        )


@pytest.mark.unit
def test_a_minute_missing_a_reading_every_bucket_needs_is_not_reported() -> None:
    # Not reported, rather than reported as zero: a bucket of zeros describes a
    # shop serving nothing, and a reader who could not tell that from a minute
    # nobody heard about would diagnose the second as the first.
    some_minute = datetime(2026, 10, 4, 12, 0, tzinfo=UTC)
    the_next_minute = some_minute + timedelta(minutes=1)
    dont_care_reading = "1"

    Scenario() \
        .given(
            samples := {
                **{
                    query: [(_the_end_of(some_minute), dont_care_reading),
                            (_the_end_of(the_next_minute), dont_care_reading)]
                    for query in QUERY_FOR.values()
                },
                QUERY_FOR["error_rate"]: [(_the_end_of(some_minute), dont_care_reading)]
            }
        ) \
        .when(
            lambda: buckets_between(
                some_minute, the_next_minute,
                settings=MetricsSettings(prometheus_base_url=SOME_BASE_URL),
                get=_a_prometheus_answering(samples))
        ) \
        .then(
            _the_buckets_were_for(["2026-10-04T12:00:00Z"])
        )


@pytest.mark.unit
def test_a_series_a_service_does_not_expose_is_reported_as_absent() -> None:
    # A service that sets no limit and keeps no cache exposes no series for
    # either, and Prometheus answers an empty result. Absent is what `None`
    # says; a zero would be a limit of nothing, or a cache that never hits.
    some_minute = datetime(2026, 10, 4, 12, 0, tzinfo=UTC)
    dont_care_reading = "1"
    not_exposed = ("memory_limit_bytes", "cpu_limit_cores", "cache_hit_ratio")

    Scenario() \
        .given(
            prometheus := _a_prometheus_answering({
                query: [(_the_end_of(some_minute), dont_care_reading)]
                for field, query in QUERY_FOR.items()
                if field not in not_exposed
            })
        ) \
        .when(
            lambda: buckets_between(
                some_minute, some_minute,
                settings=MetricsSettings(prometheus_base_url=SOME_BASE_URL),
                get=prometheus)
        ) \
        .then(
            _the_only_bucket_left_absent(not_exposed)
        )


def _the_only_bucket_left_absent(fields: Sequence[str]) -> Assertion[list[MetricBucket]]:
    def assertion(buckets: list[MetricBucket]) -> bool:
        if len(buckets) != 1:
            raise AssertionError(f"Expected one bucket, but {len(buckets)} came back.")

        present = {field: getattr(buckets[0], field) for field in fields
                   if getattr(buckets[0], field) is not None}

        if present:
            raise AssertionError(
                f"Expected {list(fields)} to be absent, but the bucket carried "
                f"{present}."
            )

        return True

    return assertion


@pytest.mark.unit
def test_the_window_is_asked_for_by_the_ends_of_its_minutes() -> None:
    # A sample at `t` describes the minute ending at `t`, so the window's
    # minutes are asked for by their ends. The first is the first minute to
    # begin inside the window - one beginning before it is not in it - and the
    # last is the minute the window ends in, unfinished or not: asking up to
    # its end is what lets a source that can report it do so.
    some_window_start = datetime(2026, 10, 4, 12, 0, 20, tzinfo=UTC)
    some_window_end = datetime(2026, 10, 4, 12, 7, 30, tzinfo=UTC)
    asked: Kept[httpx2.Request] = Kept()

    Scenario() \
        .when(
            lambda: buckets_between(
                some_window_start, some_window_end,
                settings=MetricsSettings(prometheus_base_url=SOME_BASE_URL),
                get=_a_prometheus_answering({}, asked=asked))
        ) \
        .then(
            _every_request_asked_from(
                _the_end_of(datetime(2026, 10, 4, 12, 1, tzinfo=UTC)),
                to=_the_end_of(datetime(2026, 10, 4, 12, 7, tzinfo=UTC)),
                of=asked
            )
        )


@pytest.mark.unit
def test_an_error_prometheus_reports_is_unavailability() -> None:
    # Prometheus refuses a query it cannot run with a status and an envelope
    # saying why. Read as an empty window, that would be a quiet service; it
    # has to arrive as "nobody could say", carrying Prometheus's own reason.
    some_window_start = datetime(2026, 10, 4, 12, 0, tzinfo=UTC)
    some_window_end = some_window_start + timedelta(minutes=30)
    some_reason = "parse error at char 5: unexpected identifier"

    Scenario() \
        .when(
            attempting(lambda: buckets_between(
                some_window_start, some_window_end,
                settings=MetricsSettings(prometheus_base_url=SOME_BASE_URL),
                get=_a_prometheus_refusing_with(400, "bad_data", some_reason)))
        ) \
        .then(
            all_of(
                an_error_was_raised(MetricsUnavailable),
                the_error_mentioned(some_reason)
            )
        )


@pytest.mark.unit
def test_a_prometheus_nobody_can_reach_is_unavailability() -> None:
    # The transport's own error stops here: nothing above the adapter knows
    # what library asked.
    some_window_start = datetime(2026, 10, 4, 12, 0, tzinfo=UTC)
    some_window_end = some_window_start + timedelta(minutes=30)

    Scenario() \
        .when(
            attempting(lambda: buckets_between(
                some_window_start, some_window_end,
                settings=MetricsSettings(prometheus_base_url=SOME_BASE_URL),
                get=_a_prometheus_nobody_can_reach()))
        ) \
        .then(
            an_error_was_raised(MetricsUnavailable)
        )


def _a_prometheus_refusing_with(status: int, error_type: str, error: str) -> Any:
    """An HTTP call answering every query with Prometheus's error envelope."""
    def get(url: str, *, params: Mapping[str, str], **dont_care: Any) -> httpx2.Response:
        return httpx2.Response(
            status,
            json={"status": "error", "errorType": error_type, "error": error},
            request=httpx2.Request("GET", url, params=params)
        )

    return get


def _a_prometheus_nobody_can_reach() -> Any:
    def get(url: str, *, params: Mapping[str, str], **dont_care: Any) -> httpx2.Response:
        raise httpx2.ConnectError(
            "connection refused", request=httpx2.Request("GET", url, params=params)
        )

    return get


def _every_request_asked_from(start: float,
                              to: float,
                              of: Kept[httpx2.Request]) -> Assertion[Any]:
    def assertion(_: Any) -> bool:
        windows = {
            (float(request.url.params["start"]), float(request.url.params["end"]))
            for request in of.taken
        }

        if windows != {(start, to)}:
            raise AssertionError(
                f"Expected every request to ask from [{start}] to [{to}], but the "
                f"windows asked for were {sorted(windows)}."
            )

        return True

    return assertion


def _the_end_of(minute: datetime) -> float:
    return (minute + timedelta(minutes=1)).timestamp()


def _the_buckets_were_for(minutes: list[str]) -> Assertion[list[MetricBucket]]:
    def assertion(buckets: list[MetricBucket]) -> bool:
        reported = [bucket.bucket_id for bucket in buckets]

        if reported != minutes:
            raise AssertionError(
                f"Expected buckets for {minutes}, but buckets came back for "
                f"{reported}."
            )

        return True

    return assertion


def _a_prometheus_answering(samples: Mapping[str, Sequence[tuple[float, str]]],
                            asked: Kept[httpx2.Request] | None = None) -> Any:
    """An HTTP call answering each query with its samples, in Prometheus's
    matrix envelope, and recording each request where asked to.

    A query with no samples is answered as Prometheus answers a series nobody
    exposes: success, and an empty result - not an error.
    """
    def get(url: str, *, params: Mapping[str, str], **dont_care: Any) -> httpx2.Response:
        request = httpx2.Request("GET", url, params=params)

        if asked is not None:
            asked.take(request)

        values = [[at, value] for at, value in samples.get(params["query"], [])]

        return httpx2.Response(
            200,
            json={
                "status": "success",
                "data": {
                    "resultType": "matrix",
                    "result": [{"metric": {}, "values": values}] if values else []
                }
            },
            request=request
        )

    return get


def _every_request_went_to(expected: str, asked: Kept[httpx2.Request]) -> Assertion[Any]:
    def assertion(_: Any) -> bool:
        if not asked.taken:
            raise AssertionError(f"Expected requests to [{expected}], but none were made.")

        wrong = [
            str(request.url.copy_with(query=None))
            for request in asked.taken
            if str(request.url.copy_with(query=None)) != expected
        ]

        if wrong:
            raise AssertionError(
                f"Expected every request to go to [{expected}], but these went "
                f"elsewhere: {wrong}."
            )

        return True

    return assertion


def _every_request_asked(step: str, of: Kept[httpx2.Request]) -> Assertion[Any]:
    def assertion(_: Any) -> bool:
        steps = {request.url.params.get("step") for request in of.taken}

        if steps != {step}:
            raise AssertionError(
                f"Expected every request to step by [{step}], but the steps asked "
                f"for were {sorted(map(str, steps))}."
            )

        return True

    return assertion


def _every_request_named(parameters: list[str], of: Kept[httpx2.Request]) -> Assertion[Any]:
    def assertion(_: Any) -> bool:
        missing = [
            (str(request.url), name)
            for request in of.taken
            for name in parameters
            if not request.url.params.get(name)
        ]

        if missing:
            raise AssertionError(
                f"Expected every request to carry {parameters}, but these were "
                f"missing: {missing}."
            )

        return True

    return assertion
