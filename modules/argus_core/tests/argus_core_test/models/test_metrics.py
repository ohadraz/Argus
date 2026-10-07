"""One minute of the service's metrics, as the model carries it.

The resource fields are the ones worth pinning here, because each is nullable
for a reason and the reasons differ. A limit is absent where a deployment
imposes none; a hit ratio is absent where a deployment consults no cache. In
both cases zero would be a different claim - "no memory available", "the cache
answered nothing" - and both are claims a reader would act on.

The rule's reading is nullable for a third reason: it is what the rule that paged
evaluates, and a window read for no rule, or for one whose series could not be
followed, has nothing to carry. It carries its direction beside its value,
because a share that falls is as much a departure as a latency that climbs, and
which of the two a given series is belongs to the rule, not to the number.
"""

from __future__ import annotations

import pytest
from argus_core.models import RULE_READING_FIELD, MetricBucket, RuleReading
from argus_testkit import Assertion, Scenario, all_of
from pydantic import ValidationError

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
        "cpu_used_cores": 0.77,
        "cpu_limit_cores": 3.0,
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


@pytest.mark.unit
def test_a_bucket_carries_the_cpu_it_used_against_the_capacity_it_had() -> None:
    Scenario() \
        .given(a_minute_with_headroom := a_bucket(
            cpu_used_cores=0.77, cpu_limit_cores=3.0
        )) \
        .when(lambda: a_minute_with_headroom) \
        .then(all_of(
            _the_cpu_used_is(0.77),
            _the_cpu_capacity_is(3.0)
        ))


@pytest.mark.unit
def test_a_deployment_with_no_cpu_limit_reports_no_capacity_rather_than_zero() -> None:
    # The memory limit's reason, for the same field in a different resource: a
    # deployment that imposes no limit is ordinary, and zero would say the
    # service has no CPU at all - which is a claim a reader would act on.
    Scenario() \
        .given(a_minute_from_an_unlimited_deployment := a_bucket(
            cpu_limit_cores=None
        )) \
        .when(lambda: a_minute_from_an_unlimited_deployment) \
        .then(all_of(
            _the_cpu_used_is(0.77),
            _the_cpu_capacity_is(None)
        ))


@pytest.mark.unit
def test_a_bucket_reporting_no_cpu_at_all_is_refused() -> None:
    # Unlike the capacity beside it, and unlike the hit ratio: every process uses
    # CPU, so an absent figure is a measurement that went astray rather than a
    # fact about the service - and nothing should be invited to read it as one.
    with pytest.raises(ValidationError):
        MetricBucket.model_validate(_a_minute_without_its_cpu())


@pytest.mark.unit
def test_a_bucket_carries_the_paging_rules_reading_and_which_way_is_worse() -> None:
    Scenario() \
        .given(a_minute_read_for_a_rule := a_bucket(
            rule_reading={"value": 0.41, "worse_when": "below"}
        )) \
        .when(lambda: a_minute_read_for_a_rule) \
        .then(_the_rule_reading_is(RuleReading(value=0.41, worse_when="below")))


@pytest.mark.unit
def test_a_bucket_read_for_no_rule_carries_no_rule_reading() -> None:
    Scenario() \
        .given(a_minute_read_for_no_rule := a_bucket()) \
        .when(lambda: a_minute_read_for_no_rule) \
        .then(_the_rule_reading_is(None))


@pytest.mark.unit
def test_a_bucket_keyed_by_the_rule_reading_field_carries_the_reading() -> None:
    # The name a source keys a minute's reading by, and a reader leaves the
    # column out by. Spelled as a string in each, it was free to drift from the
    # field - and a key the bucket does not have is dropped without a word, the
    # reading lost and the window read as one nobody had a rule for.
    Scenario() \
        .given(
            a_minute_keyed_by_name := {RULE_READING_FIELD: {"value": 0.41, "worse_when": "below"}}
        ) \
        .when(lambda: a_bucket(**a_minute_keyed_by_name)) \
        .then(_the_rule_reading_is(RuleReading(value=0.41, worse_when="below")))


@pytest.mark.unit
def test_a_rule_reading_worse_neither_above_nor_below_is_refused() -> None:
    # Above and below are the two directions a threshold has. Anything else is a
    # reading nothing downstream could orient, and judging it either way would be
    # a guess presented as a departure.
    with pytest.raises(ValidationError):
        RuleReading.model_validate({"value": 0.41, "worse_when": "sideways"})


def _the_rule_reading_is(expected: RuleReading | None) -> Assertion[MetricBucket]:
    def assertion(bucket: MetricBucket) -> bool:
        if bucket.rule_reading != expected:
            raise AssertionError(
                f"Expected the rule's reading to be [{expected}], and the bucket "
                f"carried [{bucket.rule_reading}]."
            )

        return True

    return assertion


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


def _a_minute_without_its_cpu() -> dict[str, object]:
    fields = dict(a_bucket().model_dump())
    del fields["cpu_used_cores"]

    return fields


def _the_cpu_used_is(expected: float) -> Assertion[MetricBucket]:
    def assertion(bucket: MetricBucket) -> bool:
        if bucket.cpu_used_cores != expected:
            raise AssertionError(
                f"Expected [{expected}] cores in use, and the bucket reported "
                f"[{bucket.cpu_used_cores}]."
            )

        return True

    return assertion


def _the_cpu_capacity_is(expected: float | None) -> Assertion[MetricBucket]:
    def assertion(bucket: MetricBucket) -> bool:
        if bucket.cpu_limit_cores != expected:
            raise AssertionError(
                f"Expected a capacity of [{expected}] cores, and the bucket "
                f"reported [{bucket.cpu_limit_cores}]."
            )

        return True

    return assertion
