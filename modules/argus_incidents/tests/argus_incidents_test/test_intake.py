"""How an incident starts: a new one, or the one its rule already has open.

A rule that fires again while Argus is still on its incident is that incident
going on, not a second one beside it. Everything else is a new incident - a
rule whose incident ended, a rule firing for another service, and an alert
naming no rule at all, which has nothing to be joined by.
"""

from __future__ import annotations

import pytest
from argus_core import connect_from_env
from argus_core.models import Alert
from argus_incidents import events_into_connection, start_incident
from argus_incidents.repository import incidents
from argus_testkit import Assertion, Scenario, all_of


@pytest.mark.component
def test_a_rule_firing_again_joins_the_incident_it_opened() -> None:
    # The rule resolved and fired again while Argus was still on it.
    some_service = "kuki-service"
    some_alert = Alert(service=some_service, alert_name="HighErrorRate", rule="some-rule")

    Scenario() \
        .given(
            first := _started(some_alert)
        ) \
        .when(
            lambda: _started(some_alert)
        ) \
        .then(all_of(
            _it_is(first),
            _incidents_were_opened_for(some_service, count=1)
        ))


@pytest.mark.component
def test_a_rule_firing_after_its_incident_ended_opens_a_new_one() -> None:
    some_service = "kuki-service"
    some_alert = Alert(service=some_service, alert_name="HighErrorRate", rule="some-rule")

    Scenario() \
        .given(
            first := _an_incident_that_ended(some_alert)
        ) \
        .when(
            lambda: _started(some_alert)
        ) \
        .then(all_of(
            _it_is_not(first),
            _incidents_were_opened_for(some_service, count=2)
        ))


@pytest.mark.component
def test_a_rule_firing_for_another_service_opens_its_own_incident() -> None:
    # A rule watching several services pages for each one, and the service
    # paged for is what an incident investigates.
    some_rule = "some-rule"
    some_other_service = "buki-service"
    an_alert_for_one_service = Alert(
        service="kuki-service", alert_name="HighErrorRate", rule=some_rule
    )
    an_alert_for_another = Alert(
        service=some_other_service, alert_name="HighErrorRate", rule=some_rule
    )

    Scenario() \
        .given(
            first := _started(an_alert_for_one_service)
        ) \
        .when(
            lambda: _started(an_alert_for_another)
        ) \
        .then(all_of(
            _it_is_not(first),
            _incidents_were_opened_for(some_other_service, count=1)
        ))


@pytest.mark.component
def test_alerts_naming_no_rule_each_open_their_own_incident() -> None:
    # Nothing to join them by: an alert's name is a title several rules share.
    some_service = "kuki-service"
    some_alert = Alert(service=some_service, alert_name="HighErrorRate")

    Scenario() \
        .given(
            first := _started(some_alert)
        ) \
        .when(
            lambda: _started(some_alert)
        ) \
        .then(all_of(
            _it_is_not(first),
            _incidents_were_opened_for(some_service, count=2)
        ))


def _started(alert: Alert) -> str:
    return start_incident(alert, connect_from_env, events_into_connection)


def _an_incident_that_ended(alert: Alert) -> str:
    incident_id = _started(alert)

    with connect_from_env() as conn:
        incidents.withdraw(conn, incident_id)
        conn.commit()

    return incident_id


def _it_is(expected: str) -> Assertion[str]:
    def assertion(incident_id: str) -> bool:
        if incident_id != expected:
            raise AssertionError(
                f"Expected the alert to join the open incident [{expected}], got "
                f"[{incident_id}]."
            )

        return True

    return assertion


def _it_is_not(other: str) -> Assertion[str]:
    def assertion(incident_id: str) -> bool:
        if incident_id == other:
            raise AssertionError(
                f"Expected the alert to open an incident other than [{other}], got it."
            )

        return True

    return assertion


def _incidents_were_opened_for(service: str, count: int) -> Assertion[str]:
    def assertion(_: str) -> bool:
        with connect_from_env() as conn:
            opened = [
                incident
                for incident in incidents.get_recent(conn)
                if incident.alert_payload.get("service") == service
            ]

        if len(opened) != count:
            raise AssertionError(
                f"Expected [{count}] incidents for [{service}], got [{len(opened)}]."
            )

        return True

    return assertion
