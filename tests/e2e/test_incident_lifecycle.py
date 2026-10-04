from __future__ import annotations

from http import HTTPStatus as HttpStatus

import pytest
from argus_core.models import IncidentStatus
from argus_testkit import Scenario, all_of, calling, eventually

from tests.e2e.framework.argus import (
    RECORDED_ABSENCE_OF_EVIDENCE,
    THE_SERVICE_NAME,
    WALK_TIMEOUT_SECONDS,
    argus_created_a_postmortem_for_the_incident,
    argus_ended_with_status,
    argus_is_triggered_with_alert,
    argus_registered_an_incident_for_the_alert,
    argus_returns_status,
    argus_went_through_statuses,
    the_model_answers_from,
)
from tests.e2e.framework.builders import a_grafana_style_alert_with
from tests.e2e.framework.world import a_scenario_was_seeded, the_shops_window


@pytest.mark.e2e
def test_an_alert_over_a_window_nobody_could_read_escalates_with_a_postmortem() -> None:
    # No scenario is seeded, so the Target Service serves no metrics at all -
    # `/metrics` answers with an empty list where nothing is staged. So Argus is
    # told a service is failing and cannot see the service.
    #
    # It escalates, and must. An empty window is an indication of nothing: not
    # that the service is well, not that it is broken. The one thing Argus must
    # not do with it is close the alarm - `disproven` is for a window that was
    # read and held no departure in any judged signal, and reaching it from no
    # readings at all would report "nothing is wrong" on the strength of never
    # having looked.
    #
    # So this stays the honest-failure path (spec §9) it always was, and the case
    # below is its pair: the same flat reading of the same five signals, over a
    # window that exists. Together they are what stops one ending standing in for
    # the other - the distinction is between having looked and not.
    some_alert_name = "HighErrorRate"
    some_severity = "critical"
    some_alert = a_grafana_style_alert_with(service=THE_SERVICE_NAME,
                                            alert_name=some_alert_name,
                                            severity=some_severity)

    Scenario() \
        .given(
            calling(the_model_answers_from(RECORDED_ABSENCE_OF_EVIDENCE))
        ) \
        .when(
            argus_is_triggered_with_alert(some_alert)
        ) \
        .then(all_of(
            argus_returns_status(HttpStatus.ACCEPTED),
            eventually(
                all_of(
                    argus_registered_an_incident_for_the_alert(some_alert),
                    # Not `acknowledged`: Argus having the alert is published
                    # as the alert arriving rather than as a status the
                    # incident entered, so the first transition is a worker
                    # taking the run up.
                    argus_went_through_statuses(
                        IncidentStatus.INVESTIGATING,
                        IncidentStatus.ESCALATED,
                    ),
                    argus_ended_with_status(IncidentStatus.ESCALATED),
                    argus_created_a_postmortem_for_the_incident(),
                ),
                timeout=WALK_TIMEOUT_SECONDS
            )
        ))


@pytest.mark.e2e
def test_an_alarm_the_metrics_contradict_is_closed_as_disproven() -> None:
    # The one ending that says there was no incident. A rule fired claiming an
    # error rate above a threshold - a condition on a series Argus also
    # retrieves - and the window Argus retrieved holds no departure in any
    # series it judges. That window is not short of evidence about this alarm:
    # it is evidence against it, and what to go and look at is the rule.
    #
    # `escalated` is the opposite finding and must not be reached here. It is
    # the ending for an incident nobody could explain, and it sends a responder
    # to the service. Reported as one status, a dashboard of spurious pages is
    # indistinguishable from a dashboard of unsolved outages.
    #
    # A scenario is seeded, and that is the whole of the staging. What this case
    # needs is a shop that is reporting and whose report is flat, which is what
    # `silent-data-corruption` says of itself: nothing throws so the error rate
    # never moves, nothing waits so no quantile moves, the heap is flat, the
    # shop is the right size, the cache is answering and the process has been up
    # for hours. Every series Argus judges is well. What is wrong is in the
    # stored totals, which no series carries.
    #
    # The alert is the suite's own plain one rather than the shop's. The shop's
    # weekly check states an onset and declares that its subject was never a
    # series, and both would correctly keep this off the branch under test.
    some_alert_name = "HighErrorRate"
    some_severity = "critical"
    some_alert = a_grafana_style_alert_with(service=THE_SERVICE_NAME,
                                            alert_name=some_alert_name,
                                            severity=some_severity)

    Scenario() \
        .given(
            calling(a_scenario_was_seeded("silent-data-corruption")),
            calling(_the_shop_is_reporting),
            calling(the_model_answers_from(RECORDED_ABSENCE_OF_EVIDENCE))
        ) \
        .when(
            argus_is_triggered_with_alert(some_alert)
        ) \
        .then(all_of(
            argus_returns_status(HttpStatus.ACCEPTED),
            eventually(
                all_of(
                    argus_registered_an_incident_for_the_alert(some_alert),
                    # Through `investigating`, because it was investigated:
                    # reading the metrics is what settled it. Two transitions
                    # and not three - the ending is reached from the
                    # investigating step without passing through mitigating,
                    # because there is nothing to mitigate.
                    argus_went_through_statuses(
                        IncidentStatus.INVESTIGATING,
                        IncidentStatus.DISPROVEN
                    ),
                    argus_ended_with_status(IncidentStatus.DISPROVEN),
                    argus_created_a_postmortem_for_the_incident()
                ),
                timeout=WALK_TIMEOUT_SECONDS
            )
        ))


def _the_shop_is_reporting() -> bool:
    """That the Target Service is serving a window at all, before the alert goes in.

    The precondition the disproven case turns on, checked rather than assumed. A
    disproof requires a window that was read and found flat; an empty window
    takes the branch the case above covers, and this one would then pass or fail
    for a reason that has nothing to do with the ending it names.

    Read straight from the shop, and asked only whether it answered with
    anything. How flat the readings are is Argus's judgement to make and not an
    assertion to restate here.
    """
    the_shops_window()

    return True
