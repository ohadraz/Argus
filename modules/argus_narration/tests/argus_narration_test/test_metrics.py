"""One minute of the service's metrics, as a row on the page.

Nothing here judges the incident. `elevated` is the mark a reader's eye lands
on and nothing more - the judgement of which minutes departed from the baseline
was made by `argus_core.anomaly` while the investigation ran, and is already in
the narration as the onset.

The threshold is stated here rather than imported, deliberately. It is the same
figure the Target Service's own console reddens a row at, copied rather than
shared: the two screens sit side by side during a demo, and one that marked a
different set of minutes than the other would make a reader translate between
them. A test that read the figure out of the code could not notice the day the
two stopped agreeing.

The memory column is the one figure here that is rendered rather than reported.
A working set is nine digits changing in their middle, which is a column nobody
can see a climb in, and it means nothing without the ceiling it is approaching -
so the row says both, in the units a dashboard says them in.
"""

from __future__ import annotations

import pytest
from argus_core.models import MetricBucket, RuleReading
from argus_narration.metrics import BucketRow, a_bucket_row
from argus_testkit import Assertion, Scenario, all_of

THE_RATE_A_MINUTE_IS_MARKED_AT = 0.05

SOME_MINUTE = "2026-08-30T10:14:00Z"

A_MEGABYTE = 1024**2
A_GIGABYTE = 1024**3

DONT_CARE_STARTED_AT = 1_756_000_000.0


@pytest.mark.unit
def test_a_minute_over_the_threshold_is_marked() -> None:
    # The mark a reader scanning ninety rows actually navigates by.
    a_rate_over_the_threshold = THE_RATE_A_MINUTE_IS_MARKED_AT + 0.01

    Scenario() \
        .given(some_bad_minute := _a_bucket(error_rate=a_rate_over_the_threshold)) \
        .when(lambda: a_bucket_row(some_bad_minute)) \
        .then(_it_is_marked(True))


@pytest.mark.unit
def test_a_minute_under_the_threshold_is_not_marked() -> None:
    # Most of the window is this. A page that marked ordinary trade would be a
    # page with nothing to find.
    a_rate_under_the_threshold = THE_RATE_A_MINUTE_IS_MARKED_AT - 0.01

    Scenario() \
        .given(some_quiet_minute := _a_bucket(error_rate=a_rate_under_the_threshold)) \
        .when(lambda: a_bucket_row(some_quiet_minute)) \
        .then(_it_is_marked(False))


@pytest.mark.unit
def test_a_minute_exactly_at_the_threshold_is_marked() -> None:
    # Which side of the line the line itself falls on. The shop's console
    # reddens at the figure rather than past it, and a page disagreeing by one
    # row is a page a reader has to reconcile.
    Scenario() \
        .given(
            a_minute_right_on_the_line := _a_bucket(
                error_rate=THE_RATE_A_MINUTE_IS_MARKED_AT
            )
        ) \
        .when(lambda: a_bucket_row(a_minute_right_on_the_line)) \
        .then(_it_is_marked(True))


@pytest.mark.unit
def test_a_minute_keeps_its_own_identity_and_gains_a_clock_time() -> None:
    # `bucket_id` is what the row is keyed and linked by - a finding's link
    # lands on it - so it stays exactly as it arrived. `when` is that same
    # identity said out loud, for a reader beside a wall clock.
    the_clock_time_it_reads_as = SOME_MINUTE[11:16]

    Scenario() \
        .given(some_minute := _a_bucket(bucket_id=SOME_MINUTE)) \
        .when(lambda: a_bucket_row(some_minute)) \
        .then(all_of(_it_is_keyed_by(SOME_MINUTE), _it_reads_as(the_clock_time_it_reads_as)))


@pytest.mark.unit
def test_a_minutes_numbers_are_the_ones_that_were_measured() -> None:
    # Nothing here is rounded, scaled or recomputed. The row is the reading,
    # arranged - and a page that quietly adjusted a latency would be reporting
    # a service nobody ran.
    some_bucket = MetricBucket(
        bucket_id=SOME_MINUTE,
        error_rate=0.31,
        p50_ms=120,
        p95_ms=240,
        p99_ms=420,
        request_volume=200,
        memory_used_bytes=440 * A_MEGABYTE,
        process_start_time_seconds=DONT_CARE_STARTED_AT,
        cpu_used_cores=0.77,
        cpu_limit_cores=3.0
    )

    Scenario() \
        .given(some_bucket) \
        .when(lambda: a_bucket_row(some_bucket)) \
        .then(_it_reports_what_was_measured(some_bucket))


@pytest.mark.unit
def test_memory_is_said_against_the_limit_it_is_measured_against() -> None:
    # A working set on its own answers nothing. The only question a reader asks
    # of this column is how near the ceiling the service has got, so the row
    # carries both ends of that comparison.
    Scenario() \
        .given(
            a_minute_using_a_fifth_of_its_limit := _a_bucket(
                memory_used_bytes=440 * A_MEGABYTE,
                memory_limit_bytes=2 * A_GIGABYTE
            )
        ) \
        .when(lambda: a_bucket_row(a_minute_using_a_fifth_of_its_limit)) \
        .then(_it_says_the_memory_is("440 MB of 2.0 GB"))


@pytest.mark.unit
def test_a_working_set_past_a_gigabyte_is_said_in_gigabytes() -> None:
    # The unit follows the figure, the way every dashboard a reader has seen
    # does it. `1946 MB of 2.0 GB` is one fact in two units, and the comparison
    # is the only reason both are on the row.
    Scenario() \
        .given(
            a_minute_near_its_limit := _a_bucket(
                memory_used_bytes=1946 * A_MEGABYTE,
                memory_limit_bytes=2 * A_GIGABYTE
            )
        ) \
        .when(lambda: a_bucket_row(a_minute_near_its_limit)) \
        .then(_it_says_the_memory_is("1.9 GB of 2.0 GB"))


@pytest.mark.unit
def test_a_service_with_no_limit_says_what_it_used_and_nothing_more() -> None:
    # A deployment that imposes no limit is ordinary, and it has no ceiling to
    # be near. Saying `of 0 MB` would read as a service already over one.
    Scenario() \
        .given(
            a_minute_with_no_ceiling := _a_bucket(
                memory_used_bytes=440 * A_MEGABYTE, memory_limit_bytes=None
            )
        ) \
        .when(lambda: a_bucket_row(a_minute_with_no_ceiling)) \
        .then(_it_says_the_memory_is("440 MB"))


@pytest.mark.unit
def test_cpu_is_said_against_the_capacity_it_is_measured_against() -> None:
    # A figure in cores means nothing alone: 0.8 is a quiet afternoon across three
    # replicas and an emergency on one.
    Scenario() \
        .given(a_minute_with_headroom := _a_bucket(
            cpu_used_cores=0.77, cpu_limit_cores=3.0
        )) \
        .when(lambda: a_bucket_row(a_minute_with_headroom)) \
        .then(_it_says_the_cpu_is("0.8 of 3.0 cores"))


@pytest.mark.unit
def test_a_minute_at_its_capacity_is_said_to_be_saturated() -> None:
    # The one reading a reader must not have to divide. Usage clamps at capacity,
    # so two equal figures are the whole signal - and a reader scanning a column
    # of pairs is being asked to spot equality rather than read a word.
    Scenario() \
        .given(a_saturated_minute := _a_bucket(
            cpu_used_cores=3.0, cpu_limit_cores=3.0
        )) \
        .when(lambda: a_bucket_row(a_saturated_minute)) \
        .then(_it_says_the_cpu_is("3.0 of 3.0 cores, saturated"))


@pytest.mark.unit
def test_a_deployment_with_no_cpu_limit_says_what_it_used_and_nothing_more() -> None:
    # The memory column's rule, for the other resource: a deployment that imposes
    # no limit has no ceiling to be near, and `of 0.0 cores` would read as a
    # service already over one.
    Scenario() \
        .given(a_minute_with_no_ceiling := _a_bucket(cpu_limit_cores=None)) \
        .when(lambda: a_bucket_row(a_minute_with_no_ceiling)) \
        .then(_it_says_the_cpu_is("0.8 cores"))


@pytest.mark.unit
def test_a_minute_carrying_the_rules_reading_shows_its_value() -> None:
    # The series the paging rule evaluates, and on an incident in what the
    # service answers the only column that moved. The value alone: which way the
    # rule calls worse is the same on every minute and is not a reading. To three
    # figures, because a backend's average arrives with sixteen and nobody reads
    # past the third.
    some_share = 0.8823529411764706

    Scenario() \
        .given(a_minute_read_for_a_rule := _a_bucket(
            rule_reading=RuleReading(value=some_share, worse_when="below")
        )) \
        .when(lambda: a_bucket_row(a_minute_read_for_a_rule)) \
        .then(_it_shows_the_rules_reading("0.882"))


@pytest.mark.unit
def test_a_minute_carrying_no_rules_reading_shows_none() -> None:
    # A minute read for no rule has no such reading, and none is not a reading
    # of zero.
    Scenario() \
        .given(a_minute_read_for_no_rule := _a_bucket(rule_reading=None)) \
        .when(lambda: a_bucket_row(a_minute_read_for_no_rule)) \
        .then(_it_shows_the_rules_reading(None))


def _a_bucket(error_rate: float = 0.01,
              bucket_id: str = SOME_MINUTE,
              memory_used_bytes: int = 440 * A_MEGABYTE,
              memory_limit_bytes: int | None = 2 * A_GIGABYTE,
              cpu_used_cores: float = 0.77,
              cpu_limit_cores: float | None = 3.0,
              rule_reading: RuleReading | None = None) -> MetricBucket:
    """One minute of metrics, with the latencies nothing here reads."""
    return MetricBucket(
        bucket_id=bucket_id,
        error_rate=error_rate,
        p50_ms=120,
        p95_ms=240,
        p99_ms=420,
        request_volume=200,
        memory_used_bytes=memory_used_bytes,
        memory_limit_bytes=memory_limit_bytes,
        process_start_time_seconds=DONT_CARE_STARTED_AT,
        cpu_used_cores=cpu_used_cores,
        cpu_limit_cores=cpu_limit_cores,
        rule_reading=rule_reading
    )


def _it_is_marked(expected: bool) -> Assertion[BucketRow]:
    def assertion(row: BucketRow) -> bool:
        if row.elevated is not expected:
            raise AssertionError(
                f"Expected a minute at {row.error_rate} to be "
                f"{'marked' if expected else 'left unmarked'}, it was not."
            )

        return True

    return assertion


def _it_is_keyed_by(expected: str) -> Assertion[BucketRow]:
    def assertion(row: BucketRow) -> bool:
        if row.bucket_id != expected:
            raise AssertionError(
                f"Expected the row keyed by [{expected}], got [{row.bucket_id}]."
            )

        return True

    return assertion


def _it_reads_as(expected: str) -> Assertion[BucketRow]:
    def assertion(row: BucketRow) -> bool:
        if row.when != expected:
            raise AssertionError(f"Expected [{expected}], got [{row.when}].")

        return True

    return assertion


def _it_says_the_memory_is(expected: str) -> Assertion[BucketRow]:
    def assertion(row: BucketRow) -> bool:
        if row.memory != expected:
            raise AssertionError(
                f"Expected the memory said as [{expected}], got [{row.memory}]."
            )

        return True

    return assertion


def _it_reports_what_was_measured(measured: MetricBucket) -> Assertion[BucketRow]:
    """Every figure the reading carried, checked against the reading itself.

    The four numbers the row repeats rather than renders - memory is said in a
    reader's units and has tests of its own above. Asserted together rather
    than one test each: they are one claim - that the row is the measurement
    arranged and not a second opinion about it - and a failure naming only the
    first figure to differ would send a reader looking for the wrong mistake.
    """
    def assertion(row: BucketRow) -> bool:
        reported = (row.error_rate, row.p50_ms, row.p95_ms, row.p99_ms,
                    row.request_volume)
        expected = (
            measured.error_rate, measured.p50_ms, measured.p95_ms, measured.p99_ms,
            measured.request_volume
        )

        if reported != expected:
            raise AssertionError(
                f"Expected the figures {expected} as measured, got {reported}"
            )

        return True

    return assertion


def _it_shows_the_rules_reading(expected: str | None) -> Assertion[BucketRow]:
    def assertion(row: BucketRow) -> bool:
        if row.rule_reading != expected:
            raise AssertionError(
                f"Expected the rule's reading shown as [{expected}], "
                f"got [{row.rule_reading}]."
            )

        return True

    return assertion


def _it_says_the_cpu_is(expected: str) -> Assertion[BucketRow]:
    def assertion(row: BucketRow) -> bool:
        if row.cpu != expected:
            raise AssertionError(
                f"Expected the CPU said as [{expected}], got [{row.cpu}]."
            )

        return True

    return assertion
