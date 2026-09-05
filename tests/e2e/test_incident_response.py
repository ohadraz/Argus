from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from http import HTTPStatus as HttpStatus
from typing import Any

import httpx
import psycopg
import pytest
from argus_core.timestamps import parse_iso
from argus_testkit import Assertion, Scenario, all_of
from argus_testkit.assertions import eventually
from orchestrator.repository import postmortems

from tests.e2e.framework.argus import (
    DATABASE_URL,
    RECORDED_FLAG_TOGGLE,
    TARGET_SERVICE_BASE_URL,
    THE_SERVICE_NAME,
    WALK_TIMEOUT_SECONDS,
    argus_is_triggered_with_alert,
    incident_id_from,
    the_model_answers_from,
)
from tests.e2e.framework.builders import a_grafana_style_alert_with

"""What the response cost, over an incident somebody was actually paged for.

The minutes are the one figure resting on an on-call provider, and every layer
between the two is a place they can quietly become absent: a credential nobody
set, an incident the provider does not hold, an acknowledgement in a shape the
SDK does not recognise. Each is a legitimate answer on its own, which is why
only a run of the whole stack tells them apart from a figure that was measured.

The figure asserted is person-minutes: each responder's own acknowledgement to
the end of the incident, added together. Two responders acknowledging some
minutes in is what makes that different from three other numbers a wrong
implementation would produce - the incident's own length, one responder's
span, or two full incidents - so the arithmetic is spelled out here rather
than trusted.
"""

# What the Target Service authors on every incident it reports: two people
# paged, neither of them instantly.
# MIRRORED FROM THE DEMO APP - NOT ARBITRARY VALUES!!! 
# The first assertion below checks them against what the provider  actually 
# answered, so a fixture that moves fails here saying so.
THE_TARGET_SERVICE_PAGES = {
    "PDUSERA": timedelta(minutes=4),
    "PDUSERB": timedelta(minutes=9)
}

A_MINUTE = timedelta(minutes=1)


@pytest.mark.e2e
def test_an_incident_somebody_was_paged_for_reports_the_minutes_they_spent() -> None:
    some_alert_name = "HighErrorRate"
    some_severity = "critical"
    some_alert = a_grafana_style_alert_with(service=THE_SERVICE_NAME,
                                            alert_name=some_alert_name,
                                            severity=some_severity)

    Scenario() \
        .given(
            _a_feature_flag_was_toggled_on(),
            the_model_answers_from(RECORDED_FLAG_TOGGLE),
        ) \
        .when(
            argus_is_triggered_with_alert(some_alert)
        ) \
        .then(
            # `eventually`, because the webhook now answers as soon as the
            # incident exists and a worker walks it afterwards: the postmortem
            # is written minutes after the response this asserts against.
            eventually(
                all_of(
                    _the_provider_paged_the_people_this_test_assumes(),
                    _the_postmortem_reports_the_minutes_they_spent(),
                    _the_responders_were_counted()
                ),
                timeout=WALK_TIMEOUT_SECONDS
            )
        )


def _the_provider_paged_the_people_this_test_assumes() -> Assertion[httpx.Response]:
    """The stand-in still authors the acknowledgements mirrored above.

    Checked first and separately, because everything below computes an expected
    figure from these offsets. Were the fixture to page nobody, or page them
    instantly, the arithmetic below would still agree with Argus and would have
    stopped proving anything.
    """
    def assertion(response: httpx.Response) -> bool:
        reported = _the_incident_as_the_provider_holds_it(
            incident_id_from(response))
        began_at = parse_iso(reported["created_at"])

        acknowledged_at = {
            acknowledgement["acknowledger"]["id"]: parse_iso(acknowledgement["at"])
            for acknowledgement in reported["acknowledgements"]
        }

        expected = {responder: began_at + waited
                    for responder, waited in THE_TARGET_SERVICE_PAGES.items()}

        if acknowledged_at != expected:
            raise AssertionError(
                f"This test assumes the Target Service pages "
                f"{sorted(THE_TARGET_SERVICE_PAGES)} at "
                f"{[str(waited) for waited in THE_TARGET_SERVICE_PAGES.values()]} "
                f"into the incident, but it reported {acknowledged_at} against "
                f"an incident that began at [{began_at}].")

        return True

    return assertion


def _the_postmortem_reports_the_minutes_they_spent() -> Assertion[httpx.Response]:
    """Person-minutes, from each acknowledgement to the end of the incident.

    Derived from the provider's own answer rather than written out: the
    incident's length is whatever the scenario's telemetry spanned on the day,
    and a number stated here would be asserting how long the fixture happened
    to be.

    The assumptions are reported on failure and not asserted on: when the
    minutes are absent the document has already recorded why, and reprinting
    that is the difference between "the minutes are missing" and knowing which
    way they went missing.
    """
    def assertion(response: httpx.Response) -> bool:
        incident_id = incident_id_from(response)
        postmortem = _the_postmortem_for(incident_id)
        reported = _the_incident_as_the_provider_holds_it(incident_id)

        ended_at = parse_iso(reported["resolved_at"])
        spent = sum(
            (ended_at - parse_iso(acknowledgement["at"])) // A_MINUTE
            for acknowledgement in reported["acknowledgements"]
        )

        if postmortem.engineer_minutes != spent:
            raise AssertionError(
                f"Postmortem for [{incident_id}] reports "
                f"[{postmortem.engineer_minutes}] engineer minutes, but the "
                f"provider reported {len(reported['acknowledgements'])} "
                f"acknowledgement(s) which, counted from each to the end of the "
                f"incident at [{ended_at}], add up to [{spent}]. It says: "
                f"{postmortem.assumptions}.")

        return True

    return assertion


def _the_responders_were_counted() -> Assertion[httpx.Response]:
    """As many people as the provider says acknowledged it.

    A count is what stops the minutes above being read as one person's night:
    the same total means something different shared between two people, and a
    document reporting minutes without the headcount says the wrong one.
    """
    def assertion(response: httpx.Response) -> bool:
        incident_id = incident_id_from(response)
        postmortem = _the_postmortem_for(incident_id)

        if postmortem.responders != len(THE_TARGET_SERVICE_PAGES):
            raise AssertionError(
                f"Postmortem for [{incident_id}] reports "
                f"[{postmortem.responders}] responder(s), but the Target "
                f"Service pages {len(THE_TARGET_SERVICE_PAGES)}.")

        return True

    return assertion


def _the_postmortem_for(incident_id: str) -> postmortems.Postmortem:
    with psycopg.connect(DATABASE_URL) as conn:
        postmortem = postmortems.get_by_incident(conn, incident_id)

    if postmortem is None:
        raise AssertionError(f"No postmortem exists for incident [{incident_id}].")

    return postmortem


def _the_incident_as_the_provider_holds_it(incident_id: str) -> dict[str, Any]:
    """What the on-call stand-in answers for this incident, read directly.

    The same resource Argus read, asked again here: an expectation computed
    from it cannot drift from the fixture, and the two disagreeing is exactly
    the failure worth reporting.
    """
    response = httpx.get(
        f"{TARGET_SERVICE_BASE_URL}/pagerduty/incidents/{incident_id}",
        timeout=10.0,
    )

    if response.status_code != HttpStatus.OK:
        raise AssertionError(
            f"The on-call stand-in answered [{response.status_code}] for "
            f"[{incident_id}], so nothing here can be asserted about who "
            f"responded.")

    incident: dict[str, Any] = response.json()["incident"]

    return incident


def _a_feature_flag_was_toggled_on() -> Callable[[], bool]:
    """The scenario that breaks the shop and gets somebody paged for it.

    Its own copy rather than the one in `test_incident_cost.py`: that one is
    private to its file, and a test reaching into another test module's
    `_name` is the same violation anywhere else in this repo.
    """
    def seed_scenario() -> bool:
        response = httpx.post(
            f"{TARGET_SERVICE_BASE_URL}/scenario/seed",
            json={"scenario_id": "feature-flag-toggle"},
            timeout=10.0,
        )

        return response.status_code == HttpStatus.OK

    return seed_scenario
