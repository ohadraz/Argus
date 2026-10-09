"""How an incident starts: a new one, or the one its rule already has open.

A rule that fires again while Argus is still on its incident is that incident
going on, not a second one beside it. Everything else is a new incident - a
rule whose incident ended, a rule firing for another service, and an alert
naming no rule at all, which has nothing to be joined by.

A new incident keeps the trace its alert arrived in. Every walk of it, every
unwind and every withdrawal continues that trace, so the incident's whole story
is one trace, and it starts at the alert.
"""

from __future__ import annotations

import logging

import pytest
from argus_core import connect_from_env
from argus_core.models import Alert, Reference
from argus_core.telemetry import ARGUS_INCIDENT_ID
from argus_incidents import events_into_connection, start_incident
from argus_incidents.repository import incidents, references
from argus_testkit import Assertion, Scenario, all_of, calling, one_record_was_logged

# Two carriers as a W3C propagator writes them: what the alert arrived in, and
# what a later alert for the same incident arrived in.
SOME_TRACE_CONTEXT = {
    "traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
}
SOME_OTHER_TRACE_CONTEXT = {
    "traceparent": "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"
}


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


@pytest.mark.component
def test_an_incident_keeps_the_trace_its_alert_arrived_in() -> None:
    Scenario() \
        .given(
            some_alert := Alert(service="kuki-service", alert_name="HighErrorRate")
        ) \
        .when(
            lambda: _started(some_alert, trace_context=SOME_TRACE_CONTEXT)
        ) \
        .then(
            _its_trace_is(SOME_TRACE_CONTEXT)
        )


@pytest.mark.component
def test_an_alert_joining_an_open_incident_leaves_its_trace_as_it_was() -> None:
    # The incident's trace is the first alert's. A later alert for it is a
    # request of its own, in a trace of its own, and an incident whose trace
    # moved with every alert would scatter its walk across all of them.
    some_alert = Alert(service="kuki-service", alert_name="HighErrorRate", rule="some-rule")

    Scenario() \
        .given(
            _started(some_alert, trace_context=SOME_TRACE_CONTEXT)
        ) \
        .when(
            lambda: _started(some_alert, trace_context=SOME_OTHER_TRACE_CONTEXT)
        ) \
        .then(
            _its_trace_is(SOME_TRACE_CONTEXT)
        )


@pytest.mark.component
def test_an_incident_is_found_by_the_names_its_alert_gave_it() -> None:
    # The alert is the only moment Argus hears what the monitor will call this
    # incident to the paging tool. A name not written down here is one no
    # later word from that tool can be matched by.
    Scenario() \
        .given(
            some_name := Reference(source="some-monitor", kind="some-kind", value="k-1"),
            some_alert := Alert(
                service="kuki-service", alert_name="HighErrorRate", references=(some_name,)
            )
        ) \
        .when(
            lambda: _started(some_alert)
        ) \
        .then(
            _it_is_found_by(some_name)
        )


@pytest.mark.component
def test_an_alert_joining_an_open_incident_gives_it_its_names_too() -> None:
    # A rule firing again can come from a new alert group, which the monitor
    # pages for under a new key. That page is about this incident, so its key
    # has to find this incident as well.
    some_rule = "some-rule"
    the_later_name = Reference(source="some-monitor", kind="some-kind", value="k-2")

    Scenario() \
        .given(
            _started(Alert(
                service="kuki-service", alert_name="HighErrorRate", rule=some_rule,
                references=(Reference(source="some-monitor", kind="some-kind", value="k-1"),)
            ))
        ) \
        .when(
            lambda: _started(Alert(
                service="kuki-service", alert_name="HighErrorRate", rule=some_rule,
                references=(the_later_name,)
            ))
        ) \
        .then(
            _it_is_found_by(the_later_name)
        )


@pytest.mark.component
def test_an_incident_started_outside_any_trace_keeps_none() -> None:
    # Started by something that traces nothing - a test, a script. Its walks
    # are then traced from the run that walks it.
    Scenario() \
        .given(
            some_alert := Alert(service="kuki-service", alert_name="HighErrorRate")
        ) \
        .when(
            lambda: _started(some_alert)
        ) \
        .then(
            _its_trace_is({})
        )


@pytest.mark.component
def test_an_incident_opened_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    # Nothing is walking it yet, so there is no walk to say which incident a
    # line is about - the line names it itself.
    some_service = "kuki-service"

    Scenario() \
        .given(
            calling(lambda: caplog.set_level(logging.INFO)),
            some_alert := Alert(service=some_service, alert_name="HighErrorRate")
        ) \
        .when(
            lambda: _started(some_alert)
        ) \
        .then(
            _it_was_logged_naming_it(caplog, "incident opened", service=some_service)
        )


@pytest.mark.component
def test_an_alert_joining_an_open_incident_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    # The alert opened nothing, and somebody asking where it went needs the
    # incident it went to.
    some_rule = "some-rule"
    some_alert = Alert(service="kuki-service", alert_name="HighErrorRate", rule=some_rule)

    Scenario() \
        .given(
            calling(lambda: caplog.set_level(logging.INFO)),
            _started(some_alert)
        ) \
        .when(
            lambda: _started(some_alert)
        ) \
        .then(
            _it_was_logged_naming_it(caplog, "alert joined open incident", rule=some_rule)
        )


def _it_is_found_by(reference: Reference) -> Assertion[str]:
    """That a tool using this name for the incident would reach it."""
    def assertion(incident_id: str) -> bool:
        with connect_from_env() as conn:
            found = references.get_incident_by_values(
                conn, reference.kind, [reference.value]
            )

        if found != incident_id:
            raise AssertionError(
                f"Expected the name {reference} to find the incident "
                f"[{incident_id}], and it found [{found}]."
            )

        return True

    return assertion


def _started(alert: Alert, trace_context: dict[str, str] | None = None) -> str:
    if trace_context is None:
        return start_incident(alert, connect_from_env, events_into_connection)

    return start_incident(alert, connect_from_env, events_into_connection,
                          trace_context=trace_context)


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


def _it_was_logged_naming_it(caplog: pytest.LogCaptureFixture,
                             message: str,
                             **values: object) -> Assertion[str]:
    """One line saying `message`, naming the incident the alert landed in.

    Asked of the answer rather than fixed beforehand, because which incident
    that is is what the case finds out.
    """
    def assertion(incident_id: str) -> bool:
        return one_record_was_logged(
            caplog, "argus_incidents.intake", logging.INFO, message,
            values={ARGUS_INCIDENT_ID: incident_id, **values}
        )(incident_id)

    return assertion


def _its_trace_is(expected: dict[str, str]) -> Assertion[str]:
    def assertion(incident_id: str) -> bool:
        with connect_from_env() as conn:
            incident = incidents.get(conn, incident_id)

        actual = incident.trace_context if incident is not None else "no such incident"

        if actual != expected:
            raise AssertionError(
                f"Expected the incident [{incident_id}] to keep the trace {expected}, "
                f"and it kept {actual}."
            )

        return True

    return assertion
