"""What the response cost, over an incident somebody was actually paged for.

The minutes are the one figure resting on an on-call provider, and every layer
between the two is a place they can quietly become absent: a credential nobody
set, an incident the provider does not hold, an incident Argus cannot link to
its own, an acknowledgement in a shape the SDK does not recognise. Each is a
legitimate answer on its own, which is why only a run of the whole stack tells
them apart from a figure that was measured.

The figure asserted is person-minutes: each responder's own acknowledgement to
the end of the incident, added together. Two responders acknowledging some
minutes in is what makes that different from three other numbers a wrong
implementation would produce - the incident's own length, one responder's
span, or two full incidents - so the arithmetic is spelled out here rather
than trusted.
"""

from __future__ import annotations

from datetime import timedelta

import httpx2
import psycopg
import pytest
from argus_core import utc_now
from argus_core.models import Postmortem
from argus_incidents.repository import postmortems
from argus_testkit import Assertion, Scenario, all_of, calling
from argus_testkit.assertions import eventually

from tests.e2e.framework.argus import (
    DATABASE_URL,
    RECORDED_FLAG_TOGGLE,
    THE_SERVICE_NAME,
    WALK_TIMEOUT_SECONDS,
    argus_is_triggered_with_alert,
    argus_wrote_a_postmortem,
    incident_id_from,
    the_model_answers_from,
)
from tests.e2e.framework.builders import a_grafana_style_alert_with
from tests.e2e.framework.oncall import the_on_call_platform_holds
from tests.e2e.framework.world import a_scenario_was_seeded

A_MINUTE = timedelta(minutes=1)


@pytest.mark.e2e
def test_an_incident_somebody_was_paged_for_reports_the_minutes_they_spent() -> None:
    some_alert_name = "HighErrorRate"
    some_severity = "critical"
    some_alert = a_grafana_style_alert_with(service=THE_SERVICE_NAME,
                                            alert_name=some_alert_name,
                                            severity=some_severity)

    some_on_call_incident = "PSOMEINCIDENT"
    # Two people, neither of them instantly, and at different moments: the
    # shape that tells person-minutes apart from every wrong total.
    acknowledged_after = {
        "PSOMEONE": 1 * A_MINUTE,
        "PSOMEONEELSE": 2 * A_MINUTE
    }
    resolved_after = 10 * A_MINUTE

    Scenario() \
        .given(
            calling(a_scenario_was_seeded("feature-flag-toggle")),
            calling(the_model_answers_from(RECORDED_FLAG_TOGGLE)),
            calling(the_on_call_platform_holds(
                some_on_call_incident,
                paged_for=some_alert,
                paged_at=utc_now(),
                resolved_after=resolved_after,
                acknowledged_after=acknowledged_after
            ))
        ) \
        .when(
            argus_is_triggered_with_alert(some_alert)
        ) \
        .then(
            # `eventually` on the row alone: the webhook answers as soon as the
            # incident exists and a worker walks it afterwards, so the document
            # is written minutes after the response this asserts against. Once
            # it is there everything here is settled - the document is one
            # insert and the paging was staged before it - so each is asserted
            # once rather than retried until a deadline.
            all_of(
                eventually(argus_wrote_a_postmortem(),
                           timeout=WALK_TIMEOUT_SECONDS),
                _the_postmortem_reports_the_minutes_they_spent(
                    sum((resolved_after - waited for waited in acknowledged_after.values()),
                        timedelta()) // A_MINUTE
                ),
                _the_responders_were_counted(len(acknowledged_after))
            )
        )


def _the_postmortem_reports_the_minutes_they_spent(
        expected: int) -> Assertion[httpx2.Response]:
    """Person-minutes, from each acknowledgement to the end of the incident.

    The assumptions are reported on failure and not asserted on: when the
    minutes are absent the document has already recorded why, and reprinting
    that is the difference between "the minutes are missing" and knowing which
    way they went missing.
    """
    def assertion(response: httpx2.Response) -> bool:
        incident_id = incident_id_from(response)
        postmortem = _the_postmortem_for(incident_id)

        if postmortem.engineer_minutes != expected:
            raise AssertionError(
                f"Postmortem for [{incident_id}] reports "
                f"[{postmortem.engineer_minutes}] engineer minutes, but the "
                f"acknowledgements staged, counted from each to the end of the "
                f"incident, add up to [{expected}]. It says: "
                f"{postmortem.assumptions}.")

        return True

    return assertion


def _the_responders_were_counted(expected: int) -> Assertion[httpx2.Response]:
    """As many people as the provider says acknowledged it.

    A count is what stops the minutes above being read as one person's night:
    the same total means something different shared between two people, and a
    document reporting minutes without the headcount says the wrong one.
    """
    def assertion(response: httpx2.Response) -> bool:
        incident_id = incident_id_from(response)
        postmortem = _the_postmortem_for(incident_id)

        if postmortem.responders != expected:
            raise AssertionError(
                f"Postmortem for [{incident_id}] reports "
                f"[{postmortem.responders}] responder(s), but [{expected}] "
                f"acknowledged the incident.")

        return True

    return assertion


def _the_postmortem_for(incident_id: str) -> Postmortem:
    with psycopg.connect(DATABASE_URL) as conn:
        postmortem = postmortems.get_by_incident(conn, incident_id)

    if postmortem is None:
        raise AssertionError(f"No postmortem exists for incident [{incident_id}].")

    return postmortem
