"""An incident, as the record holds it.

Its life is from the moment Argus heard of it to the moment it ended, and an
incident still being worked has not ended - which is what the doors matching
it against another tool's incident read it by.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from argus_core.models import Incident, IncidentStatus, Lifespan
from argus_testkit import Assertion, Scenario

SOME_MOMENT = datetime(2026, 10, 14, 16, 0, tzinfo=UTC)
DONT_CARE_ID = "5f0c6a8e-4b8f-4c55-9a51-0d5f3b8f2a11"


@pytest.mark.unit
def test_an_ended_incidents_life_is_from_its_creation_to_its_end() -> None:
    some_end = SOME_MOMENT + timedelta(minutes=20)

    Scenario() \
        .given(an_incident := _an_incident(created_at=SOME_MOMENT, ended_at=some_end,
                                           status=IncidentStatus.ESCALATED)) \
        .when(lambda: an_incident.lifespan) \
        .then(_the_life_is(Lifespan(began_at=SOME_MOMENT, ended_at=some_end)))


@pytest.mark.unit
def test_an_incident_still_being_worked_has_a_life_with_no_end() -> None:
    Scenario() \
        .given(an_incident := _an_incident(created_at=SOME_MOMENT, ended_at=None,
                                           status=IncidentStatus.INVESTIGATING)) \
        .when(lambda: an_incident.lifespan) \
        .then(_the_life_is(Lifespan(began_at=SOME_MOMENT, ended_at=None)))


def _an_incident(created_at: datetime,
                 ended_at: datetime | None,
                 status: IncidentStatus) -> Incident:
    return Incident(id=DONT_CARE_ID, alert_payload={}, status=status,
                    created_at=created_at, ended_at=ended_at)


def _the_life_is(expected: Lifespan) -> Assertion[Lifespan]:
    def assertion(lifespan: Lifespan) -> bool:
        if lifespan != expected:
            raise AssertionError(f"Expected the incident's life to be {expected}, got {lifespan}.")

        return True

    return assertion
