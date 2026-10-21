"""The door a human stops Argus through.

The Orchestrator's second entrypoint, beside the one that starts an incident,
and in its own module for the same reason that one is: `argus_web` calls it, and
anything `argus_web` can import must reach nothing that walks a graph.

It publishes, which the repository beneath it does not. A page watching an
incident finds out that somebody stopped it the same way it finds out anything
else - from the event stream - and a withdrawal that only wrote a row would
leave that page polling an incident that had already ended.
"""

from __future__ import annotations

import logging

import pytest
from argus_core import connect_from_env, utc_now
from argus_core.events import IncidentEvent, StatusChanged
from argus_core.models import Alert, IncidentStatus, Report, ReportChannel
from argus_incidents.repository import incidents
from argus_incidents.withdrawal import withdraw_incident
from argus_testkit import Assertion, Scenario, all_of, calling, one_record_was_logged

# The withdraw button takes no note, so the report it makes carries none.
SOME_REPORT = Report(by="some person", channel=ReportChannel.ARGUS_UI)


@pytest.mark.component
def test_a_withdrawal_that_took_effect_is_published_with_who_reported_it(
    a_clean_database: None
) -> None:
    some_alert = Alert(service="kuki-service", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert, at=utc_now())

    published: list[IncidentEvent] = []

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: withdraw_incident(incident_id, SOME_REPORT, connect_from_env,
                                      publisher=published.append)
        ) \
        .then(all_of(
            _it_reports(True),
            _the_incident_was_published_as_withdrawn(published, incident_id, SOME_REPORT)
        ))


@pytest.mark.component
def test_a_withdrawal_that_changed_nothing_publishes_nothing(a_clean_database: None) -> None:
    # A second press, or a press on an incident that resolved while the page
    # was open. Publishing either would tell every watcher that an incident
    # ended twice, and would end one that never did.
    some_alert = Alert(service="buki-service", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert, at=utc_now())
        incidents.transition(
            conn,
            incident_id,
            IncidentStatus.RESOLVED,
            at=utc_now(),
        )

    published: list[IncidentEvent] = []

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: withdraw_incident(incident_id, SOME_REPORT, connect_from_env,
                                      publisher=published.append)
        ) \
        .then(all_of(
            _it_reports(False),
            _nothing_was_published(published)
        ))


@pytest.mark.component
def test_a_withdrawal_reaches_the_incident_itself(a_clean_database: None) -> None:
    # The publishing above is a narration of a change; this is the change. A
    # walk asks the incident, not the event stream, whether it is still wanted.
    some_alert = Alert(service="muki-service", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert, at=utc_now())

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: withdraw_incident(incident_id, SOME_REPORT, connect_from_env,
                                      publisher=_nobody_is_listening)
        ) \
        .then(
            _the_incident_is(incident_id, IncidentStatus.WITHDRAWN)
        )


@pytest.mark.component
def test_a_withdrawal_that_took_effect_is_logged_with_where_it_came_from(
    a_clean_database: None, caplog: pytest.LogCaptureFixture
) -> None:
    # The response stopped at somebody's say-so, and which door it came in
    # through is the part of it nothing else in the log records.
    some_alert = Alert(service="kuki-service", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert, at=utc_now())

    Scenario() \
        .given(
            calling(lambda: caplog.set_level(logging.INFO))
        ) \
        .when(
            lambda: withdraw_incident(incident_id, SOME_REPORT, connect_from_env,
                                      publisher=_nobody_is_listening)
        ) \
        .then(
            one_record_was_logged(caplog, "argus_incidents.withdrawal", logging.INFO,
                                  "incident withdrawn",
                                  values={"channel": ReportChannel.ARGUS_UI})
        )


@pytest.mark.component
def test_a_withdrawal_ends_the_incident_at_the_moment_it_is_published(
    a_clean_database: None
) -> None:
    # The row's end and the account's line are one instant.
    some_alert = Alert(service="tuki-service", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert, at=utc_now())

    published: list[IncidentEvent] = []

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: withdraw_incident(incident_id, SOME_REPORT, connect_from_env,
                                      publisher=published.append)
        ) \
        .then(
            _it_ended_when_it_was_said_to(published, incident_id)
        )


def _it_ended_when_it_was_said_to(published: list[IncidentEvent],
                                  incident_id: str) -> Assertion[bool]:
    def assertion(_ended: bool) -> bool:
        said_at = [event.at for event in published
                   if isinstance(event, StatusChanged)
                   and event.to_status == IncidentStatus.WITHDRAWN]

        with connect_from_env() as conn:
            incident = incidents.get(conn, incident_id)

        ended_at = incident.ended_at if incident is not None else None
        if said_at != [ended_at]:
            raise AssertionError(
                f"Expected the incident to end at the moment its line says, it ended "
                f"at [{ended_at}] and was said to at {said_at}."
            )

        return True

    return assertion


def _nobody_is_listening(_event: IncidentEvent) -> None:
    """A publisher for a case that is not about publishing."""


def _it_reports(expected: bool) -> Assertion[bool]:
    def assertion(withdrawn: bool) -> bool:
        if withdrawn != expected:
            raise AssertionError(
                f"Expected the withdrawal to report that it "
                f"{"took effect" if expected else "changed nothing"}, "
                f"got [{withdrawn!r}]."
            )

        return True

    return assertion


def _the_incident_was_published_as_withdrawn(
    published: list[IncidentEvent], incident_id: str, reported: Report
) -> Assertion[bool]:
    def assertion(_withdrawn: bool) -> bool:
        withdrawals = [
            event for event in published
            if isinstance(event, StatusChanged)
            and event.to_status == IncidentStatus.WITHDRAWN
        ]

        if len(withdrawals) != 1:
            raise AssertionError(
                f"Expected exactly one status change to withdrawn, got "
                f"{[type(event).__name__ for event in published]}."
            )

        if withdrawals[0].incident_id != incident_id:
            raise AssertionError(
                f"Expected the event to name incident [{incident_id}], got "
                f"[{withdrawals[0].incident_id}]."
            )

        if withdrawals[0].reported != reported:
            raise AssertionError(
                f"Expected the event to carry the report [{reported}], got "
                f"[{withdrawals[0].reported}]."
            )

        return True

    return assertion


def _nothing_was_published(published: list[IncidentEvent]) -> Assertion[bool]:
    def assertion(_withdrawn: bool) -> bool:
        if published:
            raise AssertionError(
                f"Expected nothing to be published, got "
                f"{[type(event).__name__ for event in published]}."
            )

        return True

    return assertion


def _the_incident_is(incident_id: str, status: IncidentStatus) -> Assertion[bool]:
    def assertion(_withdrawn: bool) -> bool:
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
