from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from math import isclose

import pytest
from agent_postmortem.estimate import error_rate_delta, loss_estimate, revenue_per_hour
from argus_core.models.metrics import MetricBucket
from argus_testkit import Assertion, Scenario

"""What the incident cost the business, term by term.

The estimate is four numbers multiplied together and three of them are
measured, so this is where each one is pinned down on its own - the skeleton
test proves they are multiplied, and these prove they are the right numbers to
multiply.

Every case here is arithmetic. Nothing asks a model anything: a figure a model
could be talked out of is not a measurement, and the one term that is a
judgment - how much of the affected path carried revenue - arrives from
outside as a plain number.
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
def test_a_rate_is_what_was_taken_over_the_span_it_was_taken_in() -> None:
    # The port answers with an amount and the window it covers; the estimate
    # needs a rate. Halving the window doubles the rate, which is the whole
    # content of the conversion.
    some_amount = Decimal("2400")
    some_half_hour = 0.5
    expected_rate = 4800.0

    Scenario() \
        .when(
            lambda: revenue_per_hour(some_amount, over_hours=some_half_hour)
        ) \
        .then(
            _is_a_rate_of(expected_rate)
        )


@pytest.mark.unit
def test_an_incident_away_from_the_revenue_path_costs_nothing() -> None:
    # An account page failing is a real incident and a zero-dollar one. The
    # weight is what says so, and it is the only term that can.
    dont_care_hourly_rate = 4800.0
    dont_care_duration_hours = 0.5
    dont_care_error_rate_delta = 0.28
    path_carrying_no_revenue_impact = 0.0

    Scenario() \
        .when(
            lambda: loss_estimate(rate_per_hour=dont_care_hourly_rate,
                                  duration_hours=dont_care_duration_hours,
                                  delta=dont_care_error_rate_delta,
                                  impact_weight=path_carrying_no_revenue_impact)
        ) \
        .then(
            _estimates(Decimal(0))
        )


@pytest.mark.unit
def test_an_incident_squarely_on_the_revenue_path_costs_the_whole_rise() -> None:
    # Checkout. Every failed request was a sale that did not happen, so the
    # weight takes nothing off: 4800 an hour, half an hour, 28% of it lost.
    some_hourly_rate = 4800.0
    some_duration_hours = 0.5
    some_error_rate_delta = 0.28
    path_that_is_all_revenue = 1.0
    expected_loss = (
        some_hourly_rate * some_duration_hours * some_error_rate_delta * path_that_is_all_revenue
    )
    
    Scenario() \
        .when(
            lambda: loss_estimate(rate_per_hour=some_hourly_rate,
                                  duration_hours=some_duration_hours,
                                  delta=some_error_rate_delta,
                                  impact_weight=path_that_is_all_revenue)
        ) \
        .then(
            _estimates_about(expected_loss)
        )


@pytest.mark.unit
def test_a_longer_incident_costs_proportionally_more() -> None:
    # Two incidents, identical but for their length. Nothing else in the
    # estimate should move, and the longer one should cost exactly twice.
    dont_care_rate = 4800.0
    dont_care_delta = 0.28
    dont_care_weight = 1.0
    some_incident_duration_hours = 0.5
    some_other_incident_duration_hours = 1.0
    expected_loss_ratio = some_other_incident_duration_hours / some_incident_duration_hours

    Scenario() \
        .given(
            incident_loss := loss_estimate(dont_care_rate, some_incident_duration_hours,
                                           dont_care_delta, dont_care_weight)
        ) \
        .when(
            lambda: loss_estimate(dont_care_rate, some_other_incident_duration_hours,
                                  dont_care_delta, dont_care_weight)
        ) \
        .then(
            _estimates_about(float(incident_loss) * expected_loss_ratio)
        )


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


def _is_a_rate_of(expected: float) -> Assertion[float]:
    def assertion(rate: float) -> bool:
        if not isclose(rate, expected):
            raise AssertionError(f"expected a rate of [{expected}] an hour, got [{rate}]")
        return True

    return assertion


def _estimates(expected: Decimal) -> Assertion[Decimal]:
    def assertion(estimate: Decimal) -> bool:
        if estimate != expected:
            raise AssertionError(f"expected an estimate of [{expected}], got [{estimate}]")
        return True

    return assertion


def _estimates_about(expected: float) -> Assertion[Decimal]:
    """Close enough, because the terms are floats.

    An estimate resting on a judgment about which paths carry revenue is not
    accurate to the cent, and a test demanding that it match to the last bit
    would be asserting the order the multiplications happen in rather than
    what they come to.
    """
    def assertion(estimate: Decimal) -> bool:
        if not isclose(float(estimate), expected, rel_tol=1e-9):
            raise AssertionError(f"expected an estimate near [{expected}], got [{estimate}]")
        return True

    return assertion
