from __future__ import annotations

import pytest
from argus_core.models.metrics import MetricBucket
from argus_narration.metrics import BucketRow, a_bucket_row
from argus_testkit import Assertion, Scenario, all_of

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
"""

THE_RATE_A_MINUTE_IS_MARKED_AT = 0.05

SOME_MINUTE = "2026-08-30T10:14:00Z"


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
        request_volume=200
    )

    Scenario() \
        .given(some_bucket) \
        .when(lambda: a_bucket_row(some_bucket)) \
        .then(_it_reports_what_was_measured(some_bucket))


def _a_bucket(error_rate: float = 0.01, bucket_id: str = SOME_MINUTE) -> MetricBucket:
    """One minute of metrics, with the latencies nothing here reads."""
    return MetricBucket(
        bucket_id=bucket_id,
        error_rate=error_rate,
        p50_ms=120,
        p95_ms=240,
        request_volume=200
    )


def _it_is_marked(expected: bool) -> Assertion[BucketRow]:
    def assertion(row: BucketRow) -> bool:
        if row.elevated is not expected:
            raise AssertionError(
                f"expected a minute at {row.error_rate} to be "
                f"{'marked' if expected else 'left unmarked'}, it was not"
            )

        return True

    return assertion


def _it_is_keyed_by(expected: str) -> Assertion[BucketRow]:
    def assertion(row: BucketRow) -> bool:
        if row.bucket_id != expected:
            raise AssertionError(
                f"expected the row keyed by [{expected}], got [{row.bucket_id}]"
            )

        return True

    return assertion


def _it_reads_as(expected: str) -> Assertion[BucketRow]:
    def assertion(row: BucketRow) -> bool:
        if row.when != expected:
            raise AssertionError(f"expected [{expected}], got [{row.when}]")

        return True

    return assertion


def _it_reports_what_was_measured(measured: MetricBucket) -> Assertion[BucketRow]:
    """Every figure the reading carried, checked against the reading itself.

    Asserted together rather than one test each: they are one claim - that the
    row is the measurement arranged and not a second opinion about it - and a
    failure naming only the first figure to differ would send a reader looking
    for the wrong mistake.
    """
    def assertion(row: BucketRow) -> bool:
        reported = (row.error_rate, row.p50_ms, row.p95_ms, row.request_volume)
        expected = (
            measured.error_rate, measured.p50_ms, measured.p95_ms, measured.request_volume
        )

        if reported != expected:
            raise AssertionError(
                f"expected the figures {expected} as measured, got {reported}"
            )

        return True

    return assertion
