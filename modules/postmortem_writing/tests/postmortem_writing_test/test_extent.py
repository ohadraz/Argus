"""Which kind of stretch an incident's impact was, decided once for every site
that says it.

Each case names the facts that decide it and leaves the rest as the builder has
them, so a case that passes for the wrong reason has a fact in it the rule
should not have looked at.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from argus_testkit import Assertion, Scenario
from core.models import ImpactExtent
from postmortem_writing.extent import the_extent

from postmortem_writing_test.framework.builders import ONSET, RECOVERED_AT, a_measured_incident

DONT_CARE_PERSON = "Kuki Buki"
DONT_CARE_METRICS_STOPPED_AT = ONSET + timedelta(minutes=2)
DONT_CARE_METRICS_RESUMED_AT = ONSET + timedelta(minutes=8)


@pytest.mark.unit
def test_a_disproven_alarm_has_no_stretch_whatever_was_measured() -> None:
    Scenario() \
        .given(
            an_incident_measured_as_if_broken := a_measured_incident(
                metrics_stopped_at=DONT_CARE_METRICS_STOPPED_AT)
        ) \
        .when(
            lambda: the_extent(an_incident_measured_as_if_broken, disproven=True)
        ) \
        .then(
            _is(ImpactExtent.DISPROVEN)
        )


@pytest.mark.unit
@pytest.mark.parametrize(("resumed_at", "expected"), [
    pytest.param(DONT_CARE_METRICS_RESUMED_AT, ImpactExtent.METRICS_RESUMED, id="they resumed"),
    pytest.param(None, ImpactExtent.METRICS_MISSING, id="they never resumed")
])
def test_metrics_that_stopped_decide_the_stretch_before_any_end_does(
        resumed_at: datetime | None, expected: ImpactExtent) -> None:
    # A person's report and a recovery are both ends of a stretch the metrics
    # did not cover: what the stretch was is that they stopped.
    Scenario() \
        .given(
            an_incident_measured := a_measured_incident(
                metrics_stopped_at=DONT_CARE_METRICS_STOPPED_AT,
                metrics_resumed_at=resumed_at,
                back_to_normal_at=RECOVERED_AT,
                reported_by=DONT_CARE_PERSON)
        ) \
        .when(
            lambda: the_extent(an_incident_measured, disproven=False)
        ) \
        .then(
            _is(expected)
        )


@pytest.mark.unit
def test_an_end_a_person_reported_is_their_report() -> None:
    Scenario() \
        .given(
            an_incident_measured := a_measured_incident(back_to_normal_at=RECOVERED_AT,
                                                        reported_by=DONT_CARE_PERSON)
        ) \
        .when(
            lambda: the_extent(an_incident_measured, disproven=False)
        ) \
        .then(
            _is(ImpactExtent.REPORTED)
        )


@pytest.mark.unit
def test_a_service_never_seen_back_is_at_least_as_long_as_measured() -> None:
    Scenario() \
        .given(
            an_incident_measured := a_measured_incident(back_to_normal_at=None)
        ) \
        .when(
            lambda: the_extent(an_incident_measured, disproven=False)
        ) \
        .then(
            _is(ImpactExtent.AT_LEAST)
        )


@pytest.mark.unit
def test_a_service_the_metrics_show_back_is_measured() -> None:
    Scenario() \
        .given(
            an_incident_measured := a_measured_incident(back_to_normal_at=RECOVERED_AT)
        ) \
        .when(
            lambda: the_extent(an_incident_measured, disproven=False)
        ) \
        .then(
            _is(ImpactExtent.MEASURED)
        )


def _is(expected: ImpactExtent) -> Assertion[ImpactExtent]:
    def assertion(extent: ImpactExtent) -> bool:
        if extent is not expected:
            raise AssertionError(f"Expected the stretch to be [{expected}], got [{extent}].")

        return True

    return assertion
