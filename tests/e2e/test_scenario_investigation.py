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
from tests.framework.assertions import (
    some_confidence_was_given,
    the_cause_was_identified_as,
)

"""What Argus concludes about a seeded scenario, end to end.

Both stand-ins are arranged per case: the Target Service is seeded with a
scenario, and the Anthropic double is seeded with the recorded answer for it.

Run two ways, and they prove different things:

- `nox -s e2e_replay` - what CI runs on every push. Every model answer comes
  from a recording committed to this repo, so a green run proves the pipeline
  works: webhook, graph, all three retrieval channels over MCP, the Argo CD
  adapter, the real Anthropic adapter parsing a real Anthropic body,
  persistence, terminal status. It proves nothing about whether the model was
  right - that answer was decided when the recording was made. Judgement is
  measured by `nox -s eval`, over fifty samples a case.

- `nox -s e2e` - the paid, manual, pre-merge run. A real model reads the real
  retrieved evidence. The seeding step above is inert there, because nothing
  points the web app at the double.

Which is why nothing below asserts on wording. `cause_type` is a closed enum
and the final status is what Argus did; both hold whichever way this runs,
where the prose never would.
"""

# The recordings that answer for the model, by the names they are stored under
# in modules/anthropic_double/recordings/.
A_RECORDED_FLAG_TOGGLE = "feature-flag-toggle"
A_RECORDED_BAD_DEPLOYMENT = "bad-deployment"

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
    service = "io-shop"  # Not arbitrary! the Target Service names itself in its own log
    some_alert_name = "HighErrorRate"
    some_severity = "critical"
    some_alert = a_grafana_style_alert_with(service=service,
                                            alert_name=some_alert_name,
                                            severity=some_severity)

    try:
        Scenario() \
            .given(
                _a_feature_flag_was_toggled_on(),
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
                            some_confidence_was_given(),
                        ),
                        argus_ended_with_status(IncidentStatus.RESOLVED),
                    ),
                    timeout=AN_INVESTIGATION_TIMEOUT_SECONDS,
                )
            )
    finally:
        _reset_target_service_scenario()


@pytest.mark.e2e
def test_investigator_diagnoses_a_bad_deployment_as_the_cause() -> None:
    # The change channel, end to end and load-bearing. This scenario's log
    # lines report symptoms only - climbing latency, then timeouts - and never
    # mention a deploy. The deploy exists in exactly one place: the Argo CD
    # revision history the read MCP server fetches. So a diagnosis of
    # BAD_DEPLOYMENT cannot have come from anywhere else, and the whole path
    # is under test - the adapter, the onset-anchored change window, the
    # events reaching the prompt, and the model judging them.
    #
    # The other half of the point is the metrics shape: p95 departs while the
    # error rate stays mild, so a diagnosis that reached for the flag-toggle
    # story would be reading the alert rather than the evidence.
    some_alert_name = "HighLatency"
    some_severity = "critical"
    some_service = "kukibuki-service"
    some_alert = a_grafana_style_alert_with(service=some_service,
                                            alert_name=some_alert_name,
                                            severity=some_severity)

    try:
        Scenario() \
            .given(
                _a_bad_version_was_deployed(),
                the_model_answers_from(A_RECORDED_BAD_DEPLOYMENT),
            ) \
            .when(
                argus_is_triggered_with_alert(some_alert)
            ) \
            .then(
                eventually(
                    all_of(
                        about_the_hypothesis(
                            the_cause_was_identified_as(CauseType.BAD_DEPLOYMENT),
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
    return _a_scenario_was_seeded("feature-flag-toggle")


def _a_bad_version_was_deployed() -> Callable[[], bool]:
    return _a_scenario_was_seeded("bad-deployment")


def _a_scenario_was_seeded(scenario_id: str) -> Callable[[], bool]:
    def seed_scenario() -> bool:
        response = httpx.post(
            f"{TARGET_SERVICE_BASE_URL}/scenario/seed",
            json={"scenario_id": scenario_id},
            timeout=10.0,
        )

        return response.status_code == HttpStatus.OK

    return seed_scenario


def _reset_target_service_scenario() -> None:
    httpx.post(f"{TARGET_SERVICE_BASE_URL}/scenario/reset", timeout=10.0)
