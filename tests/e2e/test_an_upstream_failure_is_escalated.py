"""The incident Argus is right to do nothing about, end to end.

Every other scenario ends with Argus changing something. This one ends with it
declining to, and that is the whole point: the account page depends on a payment
provider Io does not own, the provider stops answering, and no flag to revert or
process to restart reaches the fault. An agent that acted here would be acting
because acting is what it knows how to do.

So what is asserted is a diagnosis *and* a refusal. The cause is named - this is
not an incident nobody could explain - and the world is exactly as Argus found
it: the flag the shop stages its other scenarios with is still where it rests,
and the service is still failing, because nothing Argus may do could have
stopped it.
"""

from __future__ import annotations

from collections.abc import Callable
from http import HTTPStatus as HttpStatus
from typing import Any

import httpx
import pytest
from argus_core.models import FailureMode, IncidentStatus
from argus_testkit import Assertion, Scenario, all_of, calling, eventually

from tests.e2e.framework.argus import (
    RECORDED_UPSTREAM_DEPENDENCY_FAILURE,
    TARGET_SERVICE_BASE_URL,
    THE_SERVICE_NAME,
    WALK_TIMEOUT_SECONDS,
    about_the_hypothesis,
    argus_ended_with_status,
    argus_is_triggered_with_alert,
    argus_wrote_a_postmortem,
    the_model_answers_from,
)
from tests.e2e.framework.builders import a_grafana_style_alert_with
from tests.e2e.framework.flags import THE_DEMO_FLAG, the_flag_provider_reports
from tests.framework.assertions import (
    some_confidence_was_given,
    the_cause_was_identified_as,
)

# How many of the last minute's requests still have to be failing for this to
# count as "nothing helped". Far below what the scenario actually produces -
# every account page asks the provider for a card - so the assertion is about
# the incident still being live rather than about a particular rate.
STILL_BROKEN_ABOVE = 0.2


@pytest.mark.e2e
def test_an_incident_arriving_from_outside_is_named_and_handed_to_a_person() -> None:
    # Diagnosed and escalated, which is a pair no other case has. `escalated`
    # on its own is what a walk that found nothing ends with; here the cause is
    # named exactly, and escalation is the correct answer to it rather than
    # what was left over.
    some_alert_name = "HighErrorRate"
    some_severity = "critical"
    some_alert = a_grafana_style_alert_with(service=THE_SERVICE_NAME,
                                            alert_name=some_alert_name,
                                            severity=some_severity)

    Scenario() \
        .given(
            calling(_the_payment_provider_stopped_answering()),
            calling(the_model_answers_from(RECORDED_UPSTREAM_DEPENDENCY_FAILURE))
        ) \
        .when(
            argus_is_triggered_with_alert(some_alert)
        ) \
        .then(
            eventually(
                all_of(
                    about_the_hypothesis(
                        the_cause_was_identified_as(
                            FailureMode.UPSTREAM_DEPENDENCY_FAILURE
                        ),
                        some_confidence_was_given()
                    ),
                    argus_ended_with_status(IncidentStatus.ESCALATED),
                    argus_wrote_a_postmortem(),
                    the_flag_provider_reports(THE_DEMO_FLAG, enabled=False),
                    _the_service_is_still_failing()
                ),
                timeout=WALK_TIMEOUT_SECONDS
            )
        )


def _the_payment_provider_stopped_answering() -> Callable[[], bool]:
    def seed_scenario() -> bool:
        response = httpx.post(
            f"{TARGET_SERVICE_BASE_URL}/scenario/seed",
            json={"scenario_id": "upstream-dependency-failure"},
            timeout=10.0
        )

        return response.status_code == HttpStatus.OK

    return seed_scenario


def _the_service_is_still_failing() -> Assertion[Any]:
    """The shop is as broken as it was, read from the shop itself.

    The evidence that Argus did not quietly fix this by accident, and the
    grading the spec asks for: the scenario has no Argus-controllable
    condition, so a run that ended with the service recovered would mean
    something in the stack ended an outage it does not own.
    """
    def assertion(dont_care_response: Any) -> bool:
        response = httpx.get(f"{TARGET_SERVICE_BASE_URL}/metrics", timeout=10.0)
        response.raise_for_status()
        buckets = response.json()

        if not buckets:
            raise AssertionError("The Target Service reported no metrics at all.")

        error_rate = buckets[-1]["error_rate"]

        if error_rate <= STILL_BROKEN_ABOVE:
            raise AssertionError(
                f"Expected the shop to still be failing, but its last minute "
                f"reports an error rate of [{error_rate}]."
            )

        return True

    return assertion
