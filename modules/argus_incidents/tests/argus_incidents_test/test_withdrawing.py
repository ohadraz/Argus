from __future__ import annotations

import pytest
from argus_core.db import connect
from argus_core.events import IncidentEvent, StatusChanged
from argus_core.models.actor import Actor
from argus_core.models.alert import Alert
from argus_core.models.incident_status import IncidentStatus
from argus_incidents.repository import incidents
from argus_incidents.withdrawal import wanted_via, withdraw_incident
from argus_testkit import Assertion, Scenario, all_of

"""The door a human stops Argus through.

The Orchestrator's second entrypoint, beside the one that starts an incident,
and in its own module for the same reason that one is: `argus_web` calls it, and
anything `argus_web` can import must reach nothing that walks a graph.

It publishes, which the repository beneath it does not. A page watching an
incident finds out that somebody stopped it the same way it finds out anything
else - from the event stream - and a withdrawal that only wrote a row would
leave that page polling an incident that had already ended.
"""


@pytest.mark.component
def test_a_withdrawal_that_took_effect_is_published(a_clean_database: None) -> None:
    some_alert = Alert(service="kuki-service", alert_name="HighErrorRate")

    with connect() as conn:
        incident_id = incidents.create(conn, some_alert)

    published: list[IncidentEvent] = []

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: withdraw_incident(incident_id, connect, publisher=published.append)
        ) \
        .then(all_of(
            _it_reports(True),
            _the_incident_was_published_as_withdrawn(published, incident_id)
        ))


@pytest.mark.component
def test_a_withdrawal_that_changed_nothing_publishes_nothing(a_clean_database: None) -> None:
    # A second press, or a press on an incident that resolved while the page
    # was open. Publishing either would tell every watcher that an incident
    # ended twice, and would end one that never did.
    some_alert = Alert(service="buki-service", alert_name="HighErrorRate")

    with connect() as conn:
        incident_id = incidents.create(conn, some_alert)
        incidents.transition(
            conn,
            incident_id,
            IncidentStatus.RESOLVED,
            actor=Actor.MITIGATION,
            action="dont care",
        )

    published: list[IncidentEvent] = []

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: withdraw_incident(incident_id, connect, publisher=published.append)
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

    with connect() as conn:
        incident_id = incidents.create(conn, some_alert)

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: withdraw_incident(incident_id, connect, publisher=_nobody_is_listening)
        ) \
        .then(
            _the_incident_is(incident_id, IncidentStatus.WITHDRAWN)
        )


@pytest.mark.component
def test_an_incident_argus_resolved_is_still_wanted(a_clean_database: None) -> None:
    # The walk's own ending, not somebody taking the incident back. Reading a
    # resolve as a withdrawal costs twice over: the run that just finished is
    # unwound, putting back the mitigation that worked, and the Postmortem node
    # is skipped before it can write up the incident that reached it.
    some_alert = Alert(service="kuki-service", alert_name="HighErrorRate")

    with connect() as conn:
        incident_id = incidents.create(conn, some_alert)
        incidents.transition(
            conn,
            incident_id,
            IncidentStatus.RESOLVED,
            actor=Actor.MITIGATION,
            action="dont care",
        )

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: wanted_via(connect)(incident_id)
        ) \
        .then(
            _it_reports(True)
        )


@pytest.mark.component
def test_an_incident_somebody_withdrew_is_not_wanted(a_clean_database: None) -> None:
    some_alert = Alert(service="buki-service", alert_name="HighErrorRate")

    with connect() as conn:
        incident_id = incidents.create(conn, some_alert)
        incidents.withdraw(conn, incident_id, Actor.HUMAN)

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: wanted_via(connect)(incident_id)
        ) \
        .then(
            _it_reports(False)
        )


@pytest.mark.component
def test_an_incident_with_no_row_at_all_is_not_wanted(a_clean_database: None) -> None:
    # Reading a missing incident as "carry on" is how a walk goes on writing
    # rows for something that no longer exists - which is the state a suite
    # leaves behind when it empties the database between cases.
    some_incident_id_nobody_created = "5ff3b8e4-6d2a-4b1e-9a77-0c9a1d2e3f40"

    Scenario() \
        .given(
            some_incident_id_nobody_created
        ) \
        .when(
            lambda: wanted_via(connect)(some_incident_id_nobody_created)
        ) \
        .then(
            _it_reports(False)
        )


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
    published: list[IncidentEvent], incident_id: str
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
        with connect() as conn:
            incident = incidents.get(conn, incident_id)

        if incident is None:
            raise AssertionError(f"No incident found with id [{incident_id}].")

        if incident.status != status:
            raise AssertionError(
                f"Expected status [{status!r}], got [{incident.status!r}]."
            )

        return True

    return assertion
