from __future__ import annotations

from collections.abc import Callable
from http import HTTPStatus as HttpStatus

import httpx
import pytest
from argus_core.config import get_settings
from argus_core.models.cause import CauseType
from argus_core.models.incident_status import IncidentStatus
from argus_testkit import Scenario, all_of, eventually

from tests.e2e.framework.argus import (
    TARGET_SERVICE_BASE_URL,
    about_the_hypothesis,
    argus_ended_with_status,
    argus_is_triggered_with_alert,
)
from tests.e2e.framework.builders import a_grafana_style_alert_with
from tests.framework.assertions import (
    some_confidence_was_given,
    the_cause_was_identified_as,
)

# A real investigation is up to `investigation_max_iterations` model calls,
# each one adaptive thinking at high effort. Argus answers in seconds when it
# is confident on the first pass; this bound is what "the loop ran out of
# iterations" looks like in wall-clock time, not the expected duration.
A_GENEROUS_MODEL_CALL_SECONDS = 90
AN_INVESTIGATION_TIMEOUT_SECONDS = (
    get_settings().investigation_max_iterations * A_GENEROUS_MODEL_CALL_SECONDS
)


@pytest.mark.e2e
def test_investigator_diagnoses_a_feature_flag_toggle_as_the_cause() -> None:
    # A real model call, so nothing here may depend on how the hypothesis is
    # worded - only on what it identifies. `cause_type` is a closed enum the
    # model must choose from, and the final status is what Argus did about it;
    # both are stable across runs where the prose never is.
    some_service = "kukibuki-service"
    some_alert_name = "HighErrorRate"
    some_severity = "critical"
    some_alert = a_grafana_style_alert_with(service=some_service,
                                            alert_name=some_alert_name,
                                            severity=some_severity)

    try:
        Scenario() \
            .given(
                _a_feature_flag_was_toggled_on()
            ) \
            .when(
                argus_is_triggered_with_alert(some_alert)
            ) \
            .then(
                eventually(
                    all_of(
                        about_the_hypothesis(
                            the_cause_was_identified_as(CauseType.FEATURE_FLAG_TOGGLE),
                            some_confidence_was_given(),
                        ),
                        argus_ended_with_status(IncidentStatus.RESOLVED),
                    ),
                    timeout=AN_INVESTIGATION_TIMEOUT_SECONDS,
                )
            )
    finally:
        _reset_target_service_scenario()


def _a_feature_flag_was_toggled_on() -> Callable[[], bool]:
    def toggle_feature_flag() -> bool:
        response = httpx.post(
            f"{TARGET_SERVICE_BASE_URL}/scenario/seed",
            json={"scenario_id": "feature-flag-toggle"},
            timeout=10.0,
        )

        return response.status_code == HttpStatus.OK

    return toggle_feature_flag


def _reset_target_service_scenario() -> None:
    httpx.post(f"{TARGET_SERVICE_BASE_URL}/scenario/reset", timeout=10.0)
