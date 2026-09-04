from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from math import isclose

import pytest
from agent_postmortem.estimate import error_rate_delta, loss_between
from argus_core.models.metrics import MetricBucket
from argus_testkit import Assertion, Scenario

"""What the incident cost the business, term by term.

Two quantities, measured separately and never multiplied: the loss itself,
which is a subtraction between two sums a payment provider reported, and the
rise in errors, which no figure rests on and which exists to tell the model
what happened.

Every case here is arithmetic. Nothing asks a model anything - a figure a
model could be talked out of is not a measurement.
"""

INCIDENT_START = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)
INCIDENT_END = INCIDENT_START + timedelta(minutes=30)

DONT_CARE_ERROR_RATE = 0.5


@pytest.mark.unit
def test_the_rise_in_errors_is_measured_against_the_calm_minutes_before_it() -> None:
    # Not the raw rate during the incident. A service that always fails two
    # requests in a hundred did not start doing so because of this incident,
    # and charging those to it overstates every estimate by the same amount.
    some_baseline_error_rate = 0.02
    some_error_rate_during_the_incident = 0.30
    some_incident_start = INCIDENT_START
    some_incident_end = INCIDENT_END
    some_time_before_the_incident = timedelta(minutes=2)
    some_time_into_the_incident = timedelta(minutes=5)

    Scenario() \
        .given(
            buckets := [
                _a_bucket(at=some_incident_start - some_time_before_the_incident,
                          error_rate=some_baseline_error_rate),
                _a_bucket(at=some_incident_start + some_time_into_the_incident,
                          error_rate=some_error_rate_during_the_incident)
            ]
        ) \
        .when(
            lambda: error_rate_delta(buckets, some_incident_start, some_incident_end)
        ) \
        .then(
            _is_a_rise_of(some_error_rate_during_the_incident - some_baseline_error_rate)
        )


@pytest.mark.unit
def test_a_window_with_no_calm_minutes_measures_no_rise_at_all() -> None:
    # A delta against nothing is not a small delta - there is no baseline to
    # say what "normal" was, and answering zero would report an incident that
    # cost nothing rather than a question nobody could answer.
    some_time_after_the_incident = timedelta(minutes=5)
    some_incident_start = INCIDENT_START
    some_incident_end = INCIDENT_END

    Scenario() \
        .given(
            buckets := [
                _a_bucket(at=some_incident_start + some_time_after_the_incident,
                          error_rate=DONT_CARE_ERROR_RATE)
            ]
        ) \
        .when(
            lambda: error_rate_delta(buckets, some_incident_start, some_incident_end)
        ) \
        .then(
            _nothing_could_be_measured()
        )


@pytest.mark.unit
def test_a_window_with_no_minutes_inside_the_incident_measures_no_rise_at_all() -> None:
    # The mirror case, and the one a too-narrow window produces: metrics that
    # stop before the incident starts describe a service that was fine.
    some_incident_start = INCIDENT_START
    some_incident_end = INCIDENT_END
    some_time_before_the_incident = timedelta(minutes=2)

    Scenario() \
        .given(
            buckets := [
                _a_bucket(at=some_incident_start - some_time_before_the_incident,
                          error_rate=DONT_CARE_ERROR_RATE)
            ]
        ) \
        .when(
            lambda: error_rate_delta(buckets, some_incident_start, some_incident_end)
        ) \
        .then(
            _nothing_could_be_measured()
        )


@pytest.mark.unit
def test_the_loss_is_the_shortfall_against_what_the_calm_period_predicted() -> None:
    # The whole estimate: the calm rate scaled to the length of the incident,
    # less what actually came in while it was broken.
    some_baseline_revenue = Decimal("4800")
    some_baseline_span_in_hours = 1.0
    some_incident_span_in_hours = 0.5
    some_revenue_during_the_incident = Decimal("900")
    expected_loss = (
        some_baseline_revenue
        / Decimal(str(some_baseline_span_in_hours))
        * Decimal(str(some_incident_span_in_hours))
        - some_revenue_during_the_incident
    )

    Scenario() \
        .when(
            lambda: loss_between(some_baseline_revenue,
                                 over_hours=some_baseline_span_in_hours,
                                 taken_during=some_revenue_during_the_incident,
                                 for_hours=some_incident_span_in_hours)
        ) \
        .then(
            _estimates(expected_loss)
        )


@pytest.mark.unit
def test_a_shop_that_took_more_than_predicted_lost_nothing_rather_than_less_than_nothing() -> None:
    # A quiet baseline hour against a busy incident. The subtraction goes
    # negative and the answer does not: a negative loss is not a small loss,
    # it is a category error, and zero here is a measurement rather than an
    # absence.
    some_baseline_revenue = Decimal("100")
    some_baseline_span_in_hours = 1.0
    some_incident_span_in_hours = 0.5
    some_busy_revenue_during_the_incident = Decimal("900")

    Scenario() \
        .when(
            lambda: loss_between(some_baseline_revenue,
                                 over_hours=some_baseline_span_in_hours,
                                 taken_during=some_busy_revenue_during_the_incident,
                                 for_hours=some_incident_span_in_hours)
        ) \
        .then(
            _estimates(Decimal(0))
        )


def _estimates(expected: Decimal) -> Assertion[Decimal]:
    def assertion(estimate: Decimal) -> bool:
        if estimate != expected:
            raise AssertionError(f"Expected a loss of [{expected}], got [{estimate}].")

        return True

    return assertion


def _a_bucket(at: datetime, error_rate: float) -> MetricBucket:
    return MetricBucket(
        bucket_id=at.strftime("%Y-%m-%dT%H:%M"),
        error_rate=error_rate,
        p50_ms=20,
        p95_ms=40,
        request_volume=1_000
    )


def _is_a_rise_of(expected: float) -> Assertion[float | None]:
    def assertion(delta: float | None) -> bool:
        if delta is None or not isclose(delta, expected):
            raise AssertionError(f"expected a rise of [{expected}], got [{delta}]")
        return True

    return assertion


def _nothing_could_be_measured() -> Assertion[float | None]:
    def assertion(delta: float | None) -> bool:
        if delta is not None:
            raise AssertionError(
                f"expected no measurement where one side of it is missing, got [{delta}]")
        return True

    return assertion
