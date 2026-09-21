"""One minute of the service's metrics, as the model carries it.

The resource fields are the ones worth pinning here, because each is nullable
for a reason and the reasons differ. A limit is absent where a deployment
imposes none; a hit ratio is absent where a deployment consults no cache. In
both cases zero would be a different claim - "no memory available", "the cache
answered nothing" - and both are claims a reader would act on.
"""

from __future__ import annotations

import pytest
from argus_core.models import MetricBucket
from argus_testkit import Assertion, Scenario, all_of

SOME_MINUTE = "2026-09-20T12:10:00Z"


def a_bucket(**overrides: object) -> MetricBucket:
    fields: dict[str, object] = {
        "bucket_id": SOME_MINUTE,
        "error_rate": 0.01,
        "p50_ms": 25,
        "p95_ms": 185,
        "p99_ms": 200,
        "request_volume": 1200,
        "memory_used_bytes": 461_373_440,
        "memory_limit_bytes": 2_147_483_648,
        "process_start_time_seconds": 1_756_000_000.0,
    }
    fields.update(overrides)

    return MetricBucket.model_validate(fields)


@pytest.mark.unit
def test_a_bucket_carries_how_much_of_its_work_the_cache_answered() -> None:
    Scenario() \
        .given(a_minute_mostly_served_from_cache := a_bucket(cache_hit_ratio=0.91)) \
        .when(lambda: a_minute_mostly_served_from_cache) \
        .then(_the_hit_ratio_is(0.91))


@pytest.mark.unit
def test_a_service_with_no_cache_reports_no_ratio_rather_than_zero() -> None:
    # Zero is what a cache answering nothing reports, which is the incident.
    # A deployment that consults no cache has no fast path to have lost, and a
    # reader has to be able to tell those apart.
    Scenario() \
        .given(a_minute_from_a_service_without_a_cache := a_bucket()) \
        .when(lambda: a_minute_from_a_service_without_a_cache) \
        .then(_the_hit_ratio_is(None))


@pytest.mark.unit
def test_a_cache_answering_nothing_is_a_ratio_of_zero_not_an_absence() -> None:
    Scenario() \
        .given(a_minute_the_cache_was_unreachable := a_bucket(cache_hit_ratio=0.0)) \
        .when(lambda: a_minute_the_cache_was_unreachable) \
        .then(all_of(
            _the_hit_ratio_is(0.0),
            _it_reports_a_ratio()
        ))


def _the_hit_ratio_is(expected: float | None) -> Assertion[MetricBucket]:
    def assertion(bucket: MetricBucket) -> bool:
        if bucket.cache_hit_ratio != expected:
            raise AssertionError(
                f"Expected a hit ratio of [{expected}], and the bucket reported "
                f"[{bucket.cache_hit_ratio}]."
            )

        return True

    return assertion


def _it_reports_a_ratio() -> Assertion[MetricBucket]:
    def assertion(bucket: MetricBucket) -> bool:
        if bucket.cache_hit_ratio is None:
            raise AssertionError(
                "Expected a cache that answered nothing to report a ratio of "
                "zero, and the bucket reported no ratio at all."
            )

        return True

    return assertion
