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
    A_WALK_TIMEOUT_SECONDS,
    AN_INVESTIGATION_TIMEOUT_SECONDS,
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
  action is refuted, the flag has to be found where it was left, and Argus
  goes on to whatever else the evidence offered before it gives up.

Both are staged by the Target Service, whose telemetry is a live function of
flag state, so nothing here asserts on what Argus reported about itself. The
provider's own answer about the flag is the evidence.
"""

A_RECORDED_FLAG_TOGGLE = "feature-flag-toggle"
A_RECORDED_FALLBACK_DISABLED = "fallback-disabled"


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
            the_model_answers_from(A_RECORDED_FALLBACK_DISABLED)

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
    # Three things have to follow. The incident must not reach `resolved` - the
    # shop is still broken, and an incident closed over a live fault is worse
    # than one left open. The flag must be back on: production state was
    # changed on a hypothesis that did not hold, and leaving it changed would
    # mean Argus altered the world for a cause that was not the cause, with
    # nobody told.
    #
    # And the incident ends `escalated`, not `fixing`. A refuted action used to
    # go straight to Code-Fix with the rest of the investigation's explanations
    # untried; now it goes back to the walk, and a human is reached only once
    # there is no candidate left to try and no wider look left to buy. The
    # ending is the observable difference between the two, which is why it is
    # what this asserts - how many candidates a live model volunteers is the
    # model's business, and the walk's own arithmetic is covered where it is
    # free, in the orchestrator's unit tests.
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
                    argus_ended_with_status(IncidentStatus.ESCALATED),
                    the_flag_provider_reports(THE_DEMO_FLAG, enabled=True),
                ),
                timeout=A_WALK_TIMEOUT_SECONDS,
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
