"""What the incident cost the business, term by term.

Two quantities, measured separately and never multiplied: the loss itself,
which is a subtraction between two sums a payment provider reported, and the
rise in errors, which no figure rests on and which exists to tell the model
what happened.

Every case here is arithmetic. Nothing asks a model anything - a figure a
model could be talked out of is not a measurement.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from math import isclose

import pytest
from agent_postmortem.estimate import ErrorRates, error_rates_over, loss_between
from argus_core.models import MetricBucket
from argus_testkit import Assertion, Scenario

INCIDENT_START = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)
INCIDENT_END = INCIDENT_START + timedelta(minutes=30)

DONT_CARE_ERROR_RATE = 0.5


@pytest.mark.unit
def test_the_rise_is_measured_against_the_calm_minutes_before_it() -> None:
    # Not the raw rate while it was broken. A service that always fails two
    # requests in a hundred did not start doing so because of this incident,
    # and charging those to it overstates every estimate by the same amount.
    some_baseline_error_rate = 0.02
    some_error_rate_while_broken = 0.30
    some_recovery = INCIDENT_END
    some_time_before_the_incident = timedelta(minutes=2)
    some_time_into_the_incident = timedelta(minutes=5)

    Scenario() \
        .given(
            buckets := [
                _a_bucket(at=INCIDENT_START - some_time_before_the_incident,
                          error_rate=some_baseline_error_rate),
                _a_bucket(at=INCIDENT_START + some_time_into_the_incident,
                          error_rate=some_error_rate_while_broken)
            ]
        ) \
        .when(
            lambda: error_rates_over(buckets, INCIDENT_START, some_recovery)
        ) \
        .then(
            _is_a_rise_of(some_error_rate_while_broken - some_baseline_error_rate)
        )


@pytest.mark.unit
def test_the_levels_are_measured_beside_the_rise() -> None:
    # Two questions, two numbers. The model reached past the rise for the
    # per-minute figures because severity is what it was being asked, and the
    # rise cannot answer that - a service that idles at 30% and one that idles
    # at nothing can rise by the same amount and be in very different trouble.
    some_baseline_error_rate = 0.02
    a_bad_minute = 0.30
    the_worst_minute = 0.34
    some_recovery = INCIDENT_END

    Scenario() \
        .given(
            buckets := [
                _a_bucket(at=INCIDENT_START - timedelta(minutes=2),
                          error_rate=some_baseline_error_rate),
                _a_bucket(at=INCIDENT_START + timedelta(minutes=5),
                          error_rate=a_bad_minute),
                _a_bucket(at=INCIDENT_START + timedelta(minutes=6),
                          error_rate=the_worst_minute)
            ]
        ) \
        .when(
            lambda: error_rates_over(buckets, INCIDENT_START, some_recovery)
        ) \
        .then(
            _the_levels_are(baseline=some_baseline_error_rate,
                            while_broken=(a_bad_minute + the_worst_minute) / 2,
                            at_its_worst=the_worst_minute)
        )


@pytest.mark.unit
def test_minutes_after_the_service_recovered_are_not_counted() -> None:
    # The defect this whole change is about. The window used to run to the
    # moment the walk closed the incident, which is minutes or hours of
    # healthy traffic after the mitigation landed - and averaging those in
    # drags the figure towards the baseline until the rise reads as nothing,
    # or as less than nothing.
    some_baseline_error_rate = 0.02
    some_error_rate_while_broken = 0.32
    a_healthy_minute_after_it = 0.01
    the_minute_it_recovered = INCIDENT_START + timedelta(minutes=6)

    Scenario() \
        .given(
            buckets := [
                _a_bucket(at=INCIDENT_START - timedelta(minutes=2),
                          error_rate=some_baseline_error_rate),
                _a_bucket(at=INCIDENT_START + timedelta(minutes=5),
                          error_rate=some_error_rate_while_broken),
                _a_bucket(at=INCIDENT_START + timedelta(minutes=20),
                          error_rate=a_healthy_minute_after_it)
            ]
        ) \
        .when(
            lambda: error_rates_over(buckets, INCIDENT_START, the_minute_it_recovered)
        ) \
        .then(
            _is_a_rise_of(some_error_rate_while_broken - some_baseline_error_rate)
        )


@pytest.mark.unit
def test_a_calm_stretch_noisier_than_the_broken_one_reports_a_negative_rise() -> None:
    # Deliberately not clamped. Once the window is bounded by the signal
    # rather than by the workflow, a negative rise is no longer an artefact of
    # counting healthy minutes - it says the hour before the incident was
    # worse than the incident, which is a defect report about the baseline or
    # the onset and is worth seeing rather than rounding away.
    a_noisy_calm_hour = 0.40
    a_milder_broken_stretch = 0.05
    some_recovery = INCIDENT_END

    Scenario() \
        .given(
            buckets := [
                _a_bucket(at=INCIDENT_START - timedelta(minutes=2),
                          error_rate=a_noisy_calm_hour),
                _a_bucket(at=INCIDENT_START + timedelta(minutes=5),
                          error_rate=a_milder_broken_stretch)
            ]
        ) \
        .when(
            lambda: error_rates_over(buckets, INCIDENT_START, some_recovery)
        ) \
        .then(
            _is_a_rise_of(a_milder_broken_stretch - a_noisy_calm_hour)
        )


@pytest.mark.unit
def test_a_window_with_no_calm_minutes_measures_nothing_at_all() -> None:
    # A delta against nothing is not a small delta - there is no baseline to
    # say what "normal" was, and answering zero would report an incident that
    # cost nothing rather than a question nobody could answer.
    some_time_after_the_incident = timedelta(minutes=5)

    Scenario() \
        .given(
            buckets := [
                _a_bucket(at=INCIDENT_START + some_time_after_the_incident,
                          error_rate=DONT_CARE_ERROR_RATE)
            ]
        ) \
        .when(
            lambda: error_rates_over(buckets, INCIDENT_START, INCIDENT_END)
        ) \
        .then(
            _nothing_could_be_measured()
        )


@pytest.mark.unit
def test_a_window_with_no_minutes_inside_the_broken_stretch_measures_nothing() -> None:
    # The mirror case, and the one a too-narrow window produces: metrics that
    # stop before the incident starts describe a service that was fine.
    some_time_before_the_incident = timedelta(minutes=2)

    Scenario() \
        .given(
            buckets := [
                _a_bucket(at=INCIDENT_START - some_time_before_the_incident,
                          error_rate=DONT_CARE_ERROR_RATE)
            ]
        ) \
        .when(
            lambda: error_rates_over(buckets, INCIDENT_START, INCIDENT_END)
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
        p99_ms=90,
        request_volume=1_000,
        memory_used_bytes=440 * 1024**2,
        process_start_time_seconds=1_756_000_000.0
    )


def _is_a_rise_of(expected: float) -> Assertion[ErrorRates | None]:
    def assertion(measured: ErrorRates | None) -> bool:
        if measured is None or not isclose(measured.rise, expected):
            raise AssertionError(
                f"Expected a rise of [{expected}], got "
                f"[{measured.rise if measured else None}]."
            )
        return True

    return assertion


def _the_levels_are(baseline: float,
                    while_broken: float,
                    at_its_worst: float) -> Assertion[ErrorRates | None]:
    """That all three levels came back, not only the rise.

    The rise answers attribution - how much of the traffic failed that would
    not have failed anyway - and the levels answer severity. One number was
    being asked both questions, and the labelling defect is what that looked
    like from the outside.
    """
    def assertion(measured: ErrorRates | None) -> bool:
        if measured is None:
            raise AssertionError("Expected three levels, nothing was measured.")

        got = (measured.baseline, measured.while_broken, measured.at_its_worst)
        expected = (baseline, while_broken, at_its_worst)

        if not all(isclose(one, other) for one, other in zip(got, expected, strict=True)):
            raise AssertionError(f"Expected levels {expected}, got {got}")

        return True

    return assertion


def _nothing_could_be_measured() -> Assertion[ErrorRates | None]:
    def assertion(measured: ErrorRates | None) -> bool:
        if measured is not None:
            raise AssertionError(
                f"Expected no measurement where one side of it is missing, "
                f"got [{measured}].")
        return True

    return assertion
