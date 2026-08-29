from __future__ import annotations

from http import HTTPStatus as HttpStatus

import pytest
from argus_core.models.incident_status import IncidentStatus
from argus_testkit import Scenario, all_of, eventually

from tests.e2e.framework.argus import (
    argus_created_a_postmortem_for_the_incident,
    argus_ended_with_status,
    argus_is_triggered_with_alert,
    argus_registered_an_incident_for_the_alert,
    argus_returns_status,
    argus_went_through_statuses,
    the_model_answers_from,
)
from tests.e2e.framework.builders import a_grafana_style_alert_with

# The stored answer for a window with nothing in it to blame. Named here for the
# same reason every other case names one: the double answers from whatever was
# seeded last, so a case that seeds nothing is a case whose model answer is
# whichever test ran before it - and this one runs first, when there is no such
# test and nothing is queued at all.
A_RECORDED_ABSENCE_OF_EVIDENCE = "no-evidence"


@pytest.mark.e2e
def test_firing_alert_with_no_cause_to_find_escalates_with_a_postmortem() -> None:
    # No scenario is seeded, so there is nothing in the logs to explain the
    # alert. Argus must say so and escalate - not resolve an incident it never
    # diagnosed. This is the honest-failure path (spec §9); before the ReAct
    # change the Investigator returned a fabricated hypothesis at a fixed 0.9
    # here, and this test asserted the resolve that followed from it.
    some_service = "kuki-service"
    some_alert_name = "HighErrorRate"
    some_severity = "critical"
    some_alert = a_grafana_style_alert_with(service=some_service,
                                            alert_name=some_alert_name,
                                            severity=some_severity)

    Scenario() \
        .given(
            the_model_answers_from(A_RECORDED_ABSENCE_OF_EVIDENCE)
        ) \
        .when(
            argus_is_triggered_with_alert(some_alert)
        ) \
        .then(all_of(
            argus_returns_status(HttpStatus.ACCEPTED),
            eventually(
                all_of(
                    argus_registered_an_incident_for_the_alert(some_alert),
                    argus_went_through_statuses(
                        IncidentStatus.INVESTIGATING,
                        IncidentStatus.ESCALATED,
                    ),
                    argus_ended_with_status(IncidentStatus.ESCALATED),
                    argus_created_a_postmortem_for_the_incident(),
                )
            )
        ))
