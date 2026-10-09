"""The door a person tells Argus the incident is over through.

Beside the withdrawal and shaped like it, for the same reason: `argus_web` calls
it - and PagerDuty's webhook will - and anything `argus_web` can import must
reach nothing that walks a graph.

It publishes, which the repository beneath it does not, and what it publishes
names the person. A resolution is a status change Argus did not decide, and the
account is where every reader - the page, Slack, the postmortem - finds out who
did.
"""

from __future__ import annotations

import logging

import pytest
from argus_core import connect_from_env
from argus_core.events import IncidentEvent, StatusChanged
from argus_core.models import Alert, IncidentStatus, Report, ReportChannel
from argus_incidents.repository import incidents
from argus_incidents.resolution import resolve_incident
from argus_testkit import Assertion, Scenario, all_of, calling, one_record_was_logged

SOME_REPORT = Report(by="some person", channel=ReportChannel.ARGUS_UI,
                     note="rolled the flag back by hand")


@pytest.mark.component
def test_a_resolution_that_took_effect_is_published_with_who_reported_it(
    a_clean_database: None
) -> None:
    some_alert = Alert(service="kuki-service", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)

    published: list[IncidentEvent] = []

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: resolve_incident(incident_id, SOME_REPORT, connect_from_env,
                                     publisher=published.append)
        ) \
        .then(all_of(
            _it_reports(True),
            _the_incident_was_published_as_resolved(published, incident_id, SOME_REPORT)
        ))


@pytest.mark.component
def test_a_resolution_that_changed_nothing_publishes_nothing(a_clean_database: None) -> None:
    # A second press, or a press on an incident somebody withdrew while the page
    # was open. Publishing either would tell every watcher something about the
    # incident that is not true.
    some_alert = Alert(service="buki-service", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)
        incidents.withdraw(conn, incident_id)

    published: list[IncidentEvent] = []

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: resolve_incident(incident_id, SOME_REPORT, connect_from_env,
                                     publisher=published.append)
        ) \
        .then(all_of(
            _it_reports(False),
            _nothing_was_published(published)
        ))


@pytest.mark.component
def test_a_resolution_reaches_the_incident_itself(a_clean_database: None) -> None:
    # The publishing above is a narration of a change; this is the change. A
    # walk asks the incident, not the event stream, whether somebody ended it.
    some_alert = Alert(service="muki-service", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: resolve_incident(incident_id, SOME_REPORT, connect_from_env,
                                     publisher=_nobody_is_listening)
        ) \
        .then(
            _the_incident_is(incident_id, IncidentStatus.RESOLVED)
        )


@pytest.mark.component
def test_a_resolution_that_took_effect_is_logged_with_where_it_came_from(
    a_clean_database: None, caplog: pytest.LogCaptureFixture
) -> None:
    # The response ended at somebody's word, and which door the word came in
    # through is the part of it nothing else in the log records.
    some_alert = Alert(service="kuki-service", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)

    Scenario() \
        .given(
            calling(lambda: caplog.set_level(logging.INFO))
        ) \
        .when(
            lambda: resolve_incident(incident_id, SOME_REPORT, connect_from_env,
                                     publisher=_nobody_is_listening)
        ) \
        .then(
            one_record_was_logged(caplog, "argus_incidents.resolution", logging.INFO,
                                  "incident resolved",
                                  values={"channel": ReportChannel.ARGUS_UI})
        )


def _nobody_is_listening(_event: IncidentEvent) -> None:
    """A publisher for a case that is not about publishing."""


def _it_reports(expected: bool) -> Assertion[bool]:
    def assertion(resolved: bool) -> bool:
        if resolved != expected:
            raise AssertionError(
                f"Expected the resolution to report that it "
                f"{"took effect" if expected else "changed nothing"}, "
                f"got [{resolved!r}]."
            )

        return True

    return assertion


def _the_incident_was_published_as_resolved(
    published: list[IncidentEvent], incident_id: str, reported: Report
) -> Assertion[bool]:
    def assertion(_resolved: bool) -> bool:
        resolutions = [
            event for event in published
            if isinstance(event, StatusChanged)
            and event.to_status == IncidentStatus.RESOLVED
        ]

        if len(resolutions) != 1:
            raise AssertionError(
                f"Expected exactly one status change to resolved, got "
                f"{[type(event).__name__ for event in published]}."
            )

        if resolutions[0].incident_id != incident_id:
            raise AssertionError(
                f"Expected the event to name incident [{incident_id}], got "
                f"[{resolutions[0].incident_id}]."
            )

        if resolutions[0].reported != reported:
            raise AssertionError(
                f"Expected the event to carry the report [{reported}], got "
                f"[{resolutions[0].reported}]."
            )

        return True

    return assertion


def _nothing_was_published(published: list[IncidentEvent]) -> Assertion[bool]:
    def assertion(_resolved: bool) -> bool:
        if published:
            raise AssertionError(
                f"Expected nothing to be published, got "
                f"{[type(event).__name__ for event in published]}."
            )

        return True

    return assertion


def _the_incident_is(incident_id: str, status: IncidentStatus) -> Assertion[bool]:
    def assertion(_resolved: bool) -> bool:
        with connect_from_env() as conn:
            incident = incidents.get(conn, incident_id)

        if incident is None:
            raise AssertionError(f"No incident found with id [{incident_id}].")

        if incident.status != status:
            raise AssertionError(
                f"Expected status [{status!r}], got [{incident.status!r}]."
            )

        return True

    return assertion
