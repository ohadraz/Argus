"""What other tools call an incident, given and found again through its role.

A name given is found again, by the incident it names and - for a kind several
incidents share - from the name to every incident holding it, whichever source
gave it. Built over connections, the role opens nothing until asked, and a name
it gives is kept once it has answered.
"""

from __future__ import annotations

import pytest
from argus_testkit import Assertion, Scenario, calling, the_answer_was
from core.models import NOTIFICATION_KEY, Alert, IncidentStanding, Reference
from incident_record import incident_names_on, incident_names_over
from postgres import connect_from_env

from incident_record_test.framework.builders import an_incident_created_for
from incident_record_test.framework.opening import connections_never_opened, it_was_built

DONT_CARE_ALERT = Alert(service="kuki-service", alert_name="HighErrorRate")
SOME_KEY = "the-alert-groups-key"
SOME_OTHER_KEY = "another-alert-groups-key"
SOME_MONITOR = "Grafana"
SOME_OTHER_MONITOR = "Prometheus"


@pytest.mark.component
def test_a_name_given_is_one_the_incident_is_known_by() -> None:
    with connect_from_env() as conn:
        incident_id = an_incident_created_for(conn, DONT_CARE_ALERT)

        Scenario() \
            .given(calling(lambda: incident_names_on(conn).give(
                incident_id, [_a_key(SOME_MONITOR, SOME_KEY)]))) \
            .when(lambda: incident_names_on(conn).values_for(incident_id, NOTIFICATION_KEY)) \
            .then(the_answer_was([SOME_KEY]))


@pytest.mark.component
def test_a_name_given_twice_is_held_once() -> None:
    # A webhook delivered twice is the same name arriving again.
    with connect_from_env() as conn:
        incident_id = an_incident_created_for(conn, DONT_CARE_ALERT)
        names = incident_names_on(conn)

        Scenario() \
            .given(
                calling(lambda: names.give(incident_id, [_a_key(SOME_MONITOR, SOME_KEY)])),
                calling(lambda: names.give(incident_id, [_a_key(SOME_MONITOR, SOME_KEY)]))
            ) \
            .when(lambda: names.values_for(incident_id, NOTIFICATION_KEY)) \
            .then(the_answer_was([SOME_KEY]))


@pytest.mark.component
def test_the_first_name_of_a_kind_is_the_one_given_first() -> None:
    with connect_from_env() as conn:
        incident_id = an_incident_created_for(conn, DONT_CARE_ALERT)
        names = incident_names_on(conn)

        Scenario() \
            .given(
                calling(lambda: names.give(incident_id, [_a_key(SOME_MONITOR, SOME_KEY)])),
                # Given in transactions of their own: a name is dated by the
                # transaction that gave it, and two given in one share a moment.
                calling(conn.commit),
                calling(lambda: names.give(incident_id,
                                           [_a_key(SOME_MONITOR, SOME_OTHER_KEY)]))
            ) \
            .when(lambda: names.first_of_kind(incident_id, NOTIFICATION_KEY)) \
            .then(_the_first_name_is(SOME_KEY))


@pytest.mark.component
def test_every_incident_holding_a_name_is_found_whichever_source_gave_it() -> None:
    # A paging tool cannot know which monitor stamped a key, so it asks by the
    # kind and the name alone.
    with connect_from_env() as conn:
        one = an_incident_created_for(conn, DONT_CARE_ALERT)
        another = an_incident_created_for(conn, DONT_CARE_ALERT)
        names = incident_names_on(conn)

        Scenario() \
            .given(
                calling(lambda: names.give(one, [_a_key(SOME_MONITOR, SOME_KEY)])),
                calling(lambda: names.give(another, [_a_key(SOME_OTHER_MONITOR, SOME_KEY)]))
            ) \
            .when(lambda: names.incidents_known_as(NOTIFICATION_KEY, [SOME_KEY])) \
            .then(_the_incidents_found_are({one, another}))


@pytest.mark.component
def test_names_over_connections_open_nothing_when_built() -> None:
    Scenario() \
        .when(lambda: incident_names_over(connections_never_opened())) \
        .then(it_was_built())


@pytest.mark.component
def test_a_name_given_over_connections_is_kept_once_it_is_given() -> None:
    # Its own unit of work: read back on a connection that is not the one that
    # gave it, it is there.
    with connect_from_env() as conn:
        incident_id = an_incident_created_for(conn, DONT_CARE_ALERT)

    Scenario() \
        .given(calling(lambda: incident_names_over(connect_from_env).give(
            incident_id, [_a_key(SOME_MONITOR, SOME_KEY)]))) \
        .when(lambda: _the_keys_read_afresh(incident_id)) \
        .then(the_answer_was([SOME_KEY]))


def _a_key(monitor: str, key: str) -> Reference:
    return Reference(source=monitor, kind=NOTIFICATION_KEY, value=key)


def _the_keys_read_afresh(incident_id: str) -> list[str]:
    with connect_from_env() as conn:
        return incident_names_on(conn).values_for(incident_id, NOTIFICATION_KEY)


def _the_first_name_is(expected: str) -> Assertion[object]:
    def assertion(first: object) -> bool:
        value = getattr(getattr(first, "reference", None), "value", None)

        if value != expected:
            raise AssertionError(f"Expected the first name to be {expected}, and it was {value}.")

        return True

    return assertion


def _the_incidents_found_are(expected: set[str]) -> Assertion[list[IncidentStanding]]:
    def assertion(found: list[IncidentStanding]) -> bool:
        ids = {standing.id for standing in found}

        if ids != expected:
            raise AssertionError(f"Expected the name to find {expected}, and it found {ids}.")

        return True

    return assertion
