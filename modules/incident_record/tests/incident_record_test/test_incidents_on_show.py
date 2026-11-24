"""Which incidents a page shows: every one, for the history, and the one
somebody opening Argus is looking for.

The rows decide both - which incidents there are, and which counts as current -
so the role answers them, on the connection the page reads on.
"""

from __future__ import annotations

import pytest
from argus_testkit import Assertion, Scenario, the_answer_was
from core.models import Alert, Incident
from incident_record import incidents_on_show_on
from postgres import connect_from_env

from incident_record_test.framework.builders import an_incident_created_for

DONT_CARE_ALERT = Alert(service="kuki-service", alert_name="HighErrorRate")


@pytest.mark.component
def test_there_is_no_current_incident_before_there_has_been_one() -> None:
    with connect_from_env() as conn:
        Scenario() \
            .when(lambda: incidents_on_show_on(conn).current()) \
            .then(the_answer_was(None))


@pytest.mark.component
def test_the_history_shows_every_incident() -> None:
    with connect_from_env() as conn:
        some_incidents = {an_incident_created_for(conn, DONT_CARE_ALERT),
                          an_incident_created_for(conn, DONT_CARE_ALERT)}

        Scenario() \
            .when(lambda: incidents_on_show_on(conn).recent()) \
            .then(_the_incidents_are(some_incidents))


@pytest.mark.component
def test_the_current_incident_is_the_newest_still_running() -> None:
    # Both are still running, so the newer is the one somebody opening Argus is
    # looking for.
    with connect_from_env() as conn:
        an_incident_created_for(conn, DONT_CARE_ALERT)
        the_newest = an_incident_created_for(conn, DONT_CARE_ALERT)

        Scenario() \
            .when(lambda: incidents_on_show_on(conn).current()) \
            .then(_the_incident_is(the_newest))


def _the_incidents_are(expected: set[str]) -> Assertion[list[Incident]]:
    def assertion(shown: list[Incident]) -> bool:
        ids = {incident.id for incident in shown}

        if ids != expected:
            raise AssertionError(f"Expected the history to show {expected}, and it showed {ids}.")

        return True

    return assertion


def _the_incident_is(expected: str) -> Assertion[Incident | None]:
    def assertion(current: Incident | None) -> bool:
        shown = current.id if current is not None else None

        if shown != expected:
            raise AssertionError(
                f"Expected the current incident to be {expected}, and it was {shown}."
            )

        return True

    return assertion
