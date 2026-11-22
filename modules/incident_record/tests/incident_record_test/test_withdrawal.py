"""The door a human stops Argus through.

The Orchestrator's second entrypoint, beside the one that starts an incident,
and in its own module for the same reason that one is: `web_app` calls it, and
anything `web_app` can import must reach nothing that walks a graph.

It publishes, which the repository beneath it does not. A page watching an
incident finds out that somebody stopped it the same way it finds out anything
else - from the event stream - and a withdrawal that only wrote a row would
leave that page polling an incident that had already ended. So the change and
its account are one write: a crash between the two would leave an incident
withdrawn that nothing watching it is ever told of. And the account cannot take
the change down with it: a person who stopped Argus has stopped it, whether or
not the sentence saying so could be written.
"""

from __future__ import annotations

import logging

import psycopg
import pytest
from argus_testkit import Assertion, Scenario, all_of, calling, one_record_was_logged
from core import connect_from_env, utc_now
from core.events import IncidentEvent, Publisher, StatusChanged
from core.models import Alert, IncidentStatus, Report, ReportChannel
from incident_record import PublisherFor
from incident_record.repository import incidents
from incident_record.withdrawal import withdraw_incident

from incident_record_test.framework.assertions import the_account_was_written_inside_the_change
from incident_record_test.framework.transactions import (
    Seen,
    failing_on_its_connection,
    seen_from_both_sides,
)

# The withdraw button takes no note, so the report it makes carries none.
SOME_REPORT = Report(by="some person", channel=ReportChannel.ARGUS_UI)
# A report written in a chat platform's thread, by the name its adapter gives it.
SOME_PLATFORM = "Kukichat"
SOME_REPORT_IN_A_THREAD = Report(by="some person", channel=ReportChannel.CHAT_PLATFORM,
                                 platform=SOME_PLATFORM)


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
                                      publisher_for=_into(published))
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
                                      publisher_for=_into(published))
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
                                      publisher_for=_nobody_is_listening)
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
            lambda: withdraw_incident(incident_id, SOME_REPORT_IN_A_THREAD, connect_from_env,
                                      publisher_for=_nobody_is_listening)
        ) \
        .then(
            one_record_was_logged(caplog, "incident_record.withdrawal", logging.INFO,
                                  "incident withdrawn",
                                  values={"channel": ReportChannel.CHAT_PLATFORM,
                                          "platform": SOME_PLATFORM})
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
                                      publisher_for=_into(published))
        ) \
        .then(
            _it_ended_when_it_was_said_to(published, incident_id)
        )


@pytest.mark.component
def test_a_withdrawal_and_its_account_are_one_write(a_clean_database: None) -> None:
    # Written inside the withdrawal's own transaction: seen there as withdrawn,
    # and by nobody else until the change and its account commit together.
    some_alert = Alert(service="kuki-service", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert, at=utc_now())

    seen: list[Seen] = []

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: withdraw_incident(incident_id, SOME_REPORT, connect_from_env,
                                      publisher_for=seen_from_both_sides(seen, incident_id))
        ) \
        .then(
            the_account_was_written_inside_the_change(seen, IncidentStatus.WITHDRAWN)
        )


@pytest.mark.component
def test_a_withdrawal_whose_account_fails_still_withdraws(a_clean_database: None) -> None:
    # The account is written inside the withdrawal's own transaction, so one
    # that fails there must fail alone - not abort the transaction and lose the
    # person's withdrawal with it.
    some_alert = Alert(service="kuki-service", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert, at=utc_now())

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: withdraw_incident(incident_id, SOME_REPORT, connect_from_env,
                                      publisher_for=failing_on_its_connection)
        ) \
        .then(all_of(
            _it_reports(True),
            _the_incident_is(incident_id, IncidentStatus.WITHDRAWN)
        ))


def _into(published: list[IncidentEvent]) -> PublisherFor:
    """A publisher that keeps what it is told, on whichever connection."""
    def publisher_for(_conn: psycopg.Connection) -> Publisher:
        return published.append

    return publisher_for


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


def _nobody_is_listening(_conn: psycopg.Connection) -> Publisher:
    """A publisher for a case that is not about publishing."""
    def publisher(_event: IncidentEvent) -> None:
        return None

    return publisher


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
