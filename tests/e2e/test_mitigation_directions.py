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
    the_model_answers_from,
)
from tests.e2e.framework.builders import a_grafana_style_alert_with
from tests.e2e.framework.flags import the_flag_provider_reports
from tests.framework.assertions import the_cause_was_identified_as

"""Mitigation against a real provider, in both directions and both outcomes.

The cases in `test_scenario_investigation.py` are about what Argus concludes.
These are about what it then does to a world that can answer back:

- a flag switched *off* caused the incident, so ending it means switching that
  flag back on - the direction a revert-only write tier could not perform at
  all;
- a flag was switched on, the logs say so, and it was not the cause - so the
  action is refuted, and the flag has to be found where it was left.

Both are staged by the Target Service, whose telemetry is a live function of
flag state, so nothing here asserts on what Argus reported about itself. The
provider's own answer about the flag is the evidence.
"""

A_RECORDED_FLAG_TOGGLE = "feature-flag-toggle"

A_GENEROUS_MODEL_CALL_SECONDS = 90
AN_INVESTIGATION_TIMEOUT_SECONDS = (
    get_settings().investigation_max_iterations * A_GENEROUS_MODEL_CALL_SECONDS
)
A_MITIGATION_TIMEOUT_SECONDS = (
    AN_INVESTIGATION_TIMEOUT_SECONDS
    + get_settings().mitigation_verification_timeout_seconds
)

THE_DEMO_FLAG = "monthly-spend-feature"
THE_FALLBACK_FLAG = "legacy-checkout-fallback"


@pytest.mark.e2e
def test_a_flag_switched_off_is_mitigated_by_switching_it_back_on() -> None:
    # The direction that did not exist before this change. The incident began
    # when a kill switch was withdrawn, so the flag is *off* while the shop is
    # broken - a state indistinguishable, by evaluation alone, from a flag that
    # has been off for a year. Only the provider's record of what changed can
    # tell Argus which flag this is about, and only a write tier that can set a
    # flag either way can end it.
    service = "io-shop"
    some_alert_name = "HighErrorRate"
    some_severity = "critical"
    some_alert = a_grafana_style_alert_with(service=service,
                                            alert_name=some_alert_name,
                                            severity=some_severity)

    Scenario() \
        .given(
            _a_fallback_flag_was_switched_off(),
            the_model_answers_from(A_RECORDED_FLAG_TOGGLE),
        ) \
        .when(
            argus_is_triggered_with_alert(some_alert)
        ) \
        .then(
            eventually(
                all_of(
                    argus_ended_with_status(IncidentStatus.RESOLVED),
                    the_flag_provider_reports(THE_FALLBACK_FLAG, enabled=True),
                ),
                timeout=A_MITIGATION_TIMEOUT_SECONDS,
            )
        )


@pytest.mark.e2e
def test_an_action_that_does_not_help_is_refuted_and_the_flag_is_put_back() -> None:
    # The flag really was switched on, the logs really do show it, and it is
    # not what is breaking the shop. Argus is right to try it and wrong about
    # the cause, which is the ordinary case of a correlated change.
    #
    # Two things have to follow. The incident must not reach `resolved` - the
    # shop is still broken, and an incident closed over a live fault is worse
    # than one left open. And the flag must be back on: production state was
    # changed on a hypothesis that did not hold, and leaving it changed would
    # mean Argus altered the world for a cause that was not the cause, with
    # nobody told.
    service = "io-shop"
    some_alert_name = "HighErrorRate"
    some_severity = "critical"
    some_alert = a_grafana_style_alert_with(service=service,
                                            alert_name=some_alert_name,
                                            severity=some_severity)

    Scenario() \
        .given(
            _a_flag_was_toggled_but_is_not_the_cause(),
            the_model_answers_from(A_RECORDED_FLAG_TOGGLE),
        ) \
        .when(
            argus_is_triggered_with_alert(some_alert)
        ) \
        .then(
            eventually(
                all_of(
                    about_the_hypothesis(
                        the_cause_was_identified_as(CauseType.FEATURE_FLAG_TOGGLE),
                    ),
                    argus_ended_with_status(IncidentStatus.FIXING),
                    the_flag_provider_reports(THE_DEMO_FLAG, enabled=True),
                ),
                timeout=A_MITIGATION_TIMEOUT_SECONDS,
            )
        )


def _a_fallback_flag_was_switched_off() -> Callable[[], bool]:
    return _a_scenario_was_seeded("fallback-disabled")


def _a_flag_was_toggled_but_is_not_the_cause() -> Callable[[], bool]:
    return _a_scenario_was_seeded("flag-toggle-red-herring")


def _a_scenario_was_seeded(scenario_id: str) -> Callable[[], bool]:
    def seed_scenario() -> bool:
        response = httpx.post(
            f"{TARGET_SERVICE_BASE_URL}/scenario/seed",
            json={"scenario_id": scenario_id},
            timeout=10.0,
        )

        return response.status_code == HttpStatus.OK

    return seed_scenario
