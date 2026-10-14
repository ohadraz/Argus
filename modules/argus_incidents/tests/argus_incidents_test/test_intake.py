"""How an incident starts: a new one, or the one the alert already belongs to.

A rule that fires again while Argus is still on its incident is that incident
going on, not a second one beside it. So is a reminder of a firing an incident
already holds - the monitor saying again that an alert it told Argus about is
still firing - however that incident ended, unless Argus said it mitigated it:
an alarm still going contradicts that, and the contradiction is a new incident.
Everything else is a new incident - a rule whose incident ended firing anew, a
rule firing for another service, and an alert naming neither a rule nor a
firing, which has nothing to be joined by.

A new incident keeps the trace its alert arrived in. Every walk of it, every
unwind and every withdrawal continues that trace, so the incident's whole story
is one trace, and it starts at the alert.
"""

from __future__ import annotations

import logging

import pytest
from argus_core import connect_from_env
from argus_core.models import ALERT_FIRING, Alert, IncidentStatus, Reference
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

# One firing of one alert, as a monitor names it.
SOME_FIRING = Reference(source="some-monitor", kind=ALERT_FIRING,
                        value="fp-1@2026-10-14T15:59:00Z")


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
@pytest.mark.parametrize("ending", [IncidentStatus.DISPROVEN,
                                    IncidentStatus.WITHDRAWN,
                                    IncidentStatus.ESCALATED,
                                    IncidentStatus.RECOMMENDED,
                                    IncidentStatus.RESOLVED])
def test_a_reminder_of_a_firing_joins_the_incident_it_opened_however_it_ended(
        ending: IncidentStatus) -> None:
    # None of these endings says the alarm stopped, so the alarm still going
    # is what each predicts - and a second walk would pay again for an answer
    # the incident already has.
    some_service = "kuki-service"
    some_alert = _a_reminder_of(SOME_FIRING, service=some_service)

    Scenario() \
        .given(
            first := _an_incident_ended_as(ending, some_alert)
        ) \
        .when(
            lambda: _started(some_alert)
        ) \
        .then(all_of(
            _it_is(first),
            _incidents_were_opened_for(some_service, count=1)
        ))


@pytest.mark.component
@pytest.mark.parametrize("still", [IncidentStatus.ACKNOWLEDGED,
                                   IncidentStatus.INVESTIGATING,
                                   IncidentStatus.MITIGATING,
                                   IncidentStatus.FIXING])
def test_a_reminder_of_a_firing_joins_the_incident_it_opened_while_it_is_still_going(
        still: IncidentStatus) -> None:
    # A reminder names no rule, so only its firing can join it - and the
    # incident walking that firing is the one it is about.
    some_service = "kuki-service"
    some_alert = _a_reminder_of(SOME_FIRING, service=some_service)

    Scenario() \
        .given(
            first := _an_incident_walked_to(still, some_alert)
        ) \
        .when(
            lambda: _started(some_alert)
        ) \
        .then(all_of(
            _it_is(first),
            _incidents_were_opened_for(some_service, count=1)
        ))


@pytest.mark.component
def test_a_reminder_of_a_firing_argus_said_it_mitigated_opens_a_new_incident() -> None:
    # Argus said the symptom stopped, and the alarm says it has not.
    some_service = "kuki-service"
    some_alert = _a_reminder_of(SOME_FIRING, service=some_service)

    Scenario() \
        .given(
            first := _an_incident_ended_as(IncidentStatus.MITIGATED, some_alert)
        ) \
        .when(
            lambda: _started(some_alert)
        ) \
        .then(all_of(
            _it_is_not(first),
            _incidents_were_opened_for(some_service, count=2)
        ))


@pytest.mark.component
def test_a_reminder_after_a_mitigation_was_contradicted_joins_the_incident_that_followed() -> None:
    # The firing is held by the incident Argus mitigated and by the one its
    # reminder opened. The later incident is the latest word about it, and it
    # was escalated, which the alarm going on does not contradict.
    some_service = "kuki-service"
    some_alert = _a_reminder_of(SOME_FIRING, service=some_service)

    Scenario() \
        .given(
            _an_incident_ended_as(IncidentStatus.MITIGATED, some_alert),
            second := _an_incident_ended_as(IncidentStatus.ESCALATED, some_alert)
        ) \
        .when(
            lambda: _started(some_alert)
        ) \
        .then(all_of(
            _it_is(second),
            _incidents_were_opened_for(some_service, count=2)
        ))


@pytest.mark.component
def test_a_firing_held_by_another_services_incident_opens_this_services_own() -> None:
    # One alert group spans every service its rule watches, so an incident
    # holds firings its notification carried for other services.
    some_other_service = "buki-service"

    Scenario() \
        .given(
            first := _an_incident_ended_as(IncidentStatus.ESCALATED,
                                           _a_reminder_of(SOME_FIRING, service="kuki-service"))
        ) \
        .when(
            lambda: _started(_a_reminder_of(SOME_FIRING, service=some_other_service))
        ) \
        .then(all_of(
            _it_is_not(first),
            _incidents_were_opened_for(some_other_service, count=1)
        ))


@pytest.mark.component
def test_a_reminder_joining_the_incident_it_belongs_to_gives_it_its_names_too() -> None:
    # A reminder can carry firings the first notification did not - an alert
    # of the group that started since - and the group's key with them.
    the_later_firing = Reference(source="some-monitor", kind=ALERT_FIRING,
                                 value="fp-2@2026-10-14T17:20:00Z")

    Scenario() \
        .given(
            first := _an_incident_ended_as(IncidentStatus.ESCALATED, _a_reminder_of(SOME_FIRING))
        ) \
        .when(
            lambda: _started(_a_reminder_of(SOME_FIRING, the_later_firing))
        ) \
        .then(all_of(
            _it_is(first),
            _it_is_found_by(the_later_firing)
        ))


@pytest.mark.component
def test_a_reminder_joining_the_incident_it_belongs_to_is_logged(
        caplog: pytest.LogCaptureFixture) -> None:
    # The alert opened nothing, and somebody asking where it went needs the
    # incident it went to - and why an ended one, which is the firing.
    some_alert = _a_reminder_of(SOME_FIRING)

    Scenario() \
        .given(
            calling(lambda: caplog.set_level(logging.INFO)),
            _an_incident_ended_as(IncidentStatus.ESCALATED, some_alert)
        ) \
        .when(
            lambda: _started(some_alert)
        ) \
        .then(
            _it_was_logged_naming_it(caplog, "alert joined the incident of its firing",
                                     status=IncidentStatus.ESCALATED)
        )


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
            found = [incident.id for incident in references.get_incidents_by_values(
                conn, reference.kind, [reference.value]
            )]

        if found != [incident_id]:
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


def _a_reminder_of(*firings: Reference, service: str = "kuki-service") -> Alert:
    """An alert naming no rule - so nothing but its firings can join it to an
    incident - carrying these firings as the monitor stamped them."""
    return Alert(service=service, alert_name="HighErrorRate", references=firings)


def _an_incident_walked_to(status: IncidentStatus, alert: Alert) -> str:
    """An incident `alert` opened, which the walk has since moved to `status`
    - or left where intake put it, where that is `status` already."""
    incident_id = _started(alert)

    if status != IncidentStatus.ACKNOWLEDGED:
        with connect_from_env() as conn:
            incidents.transition(conn, incident_id, status)
            conn.commit()

    return incident_id


def _an_incident_ended_as(status: IncidentStatus, alert: Alert) -> str:
    """An incident `alert` opened, ended as `status` through the door that
    ending comes through: a person's through theirs, Argus's through the
    walk's."""
    incident_id = _started(alert)

    with connect_from_env() as conn:
        match status:
            case IncidentStatus.RESOLVED:
                incidents.resolve(conn, incident_id)
            case IncidentStatus.WITHDRAWN:
                incidents.withdraw(conn, incident_id)
            case _:
                incidents.transition(conn, incident_id, status)
                conn.commit()

    return incident_id


def _it_is(expected: str) -> Assertion[str]:
    def assertion(incident_id: str) -> bool:
        if incident_id != expected:
            raise AssertionError(
                f"Expected the alert to join the incident [{expected}], got "
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
