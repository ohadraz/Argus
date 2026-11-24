"""Which Argus incidents an on-call platform's page is about.

Those an earlier read already linked to the page, and those holding one of the
keys its senders stamped on it that were going on while it was open. A key does
not name one incident. Every firing of an alert group pages under the group's
one key, so an alert that stopped and started again leaves two Argus incidents
holding it - and the platform opened a page for each. What tells them apart is
time: the page is about the incidents going on while it was. Never an older one
that merely shares the key, which is how a resolution of today's page used to
resolve last week's incident and leave today's open.

When the page was open is the platform's to say, and is read only where some
incident holds a key to weigh against it: most pages are about incidents Argus
never opened, and a platform that cannot say must not fail a match the link
alone settled.

The names are stood in for, because their rows are asserted against a real
database in their own suite. What belongs here is the decision made on them.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import Mock, create_autospec

import pytest
from argus_testkit import Assertion, Scenario, all_of, an_error_was_raised, attempting
from core.models import (
    NOTIFICATION_KEY,
    ON_CALL_INCIDENT,
    IncidentStanding,
    IncidentStatus,
    Lifespan,
)
from incident_record import IncidentNames, incidents_a_page_is_about

SOME_PAGE = "Q2FJZEW25HFSAW"
SOME_ARGUS_INCIDENT = "4c1e2a50-0000-4000-8000-000000000001"
SOME_OTHER_ARGUS_INCIDENT = "4c1e2a50-0000-4000-8000-000000000002"
SOME_KEY = "61118811129051d2ae8f1e4a0e1ba2b37f38f44a73bf44cb0b29ce81df1f57d3"

# When the page was open: from the moment the platform opened it to the moment
# the person resolved it.
THE_PAGE_OPENED = datetime(2026, 10, 14, 16, 0, tzinfo=UTC)
THE_PAGE_RESOLVED = THE_PAGE_OPENED + timedelta(minutes=40)
THE_PAGES_LIFE = Lifespan(began_at=THE_PAGE_OPENED, ended_at=THE_PAGE_RESOLVED)
A_MINUTE = timedelta(minutes=1)

NO_KEYS: list[str] = []


class _TheLifeUnreadable(Exception):
    """The platform failing to say when its page was open."""


@pytest.mark.unit
def test_an_incident_holding_the_pages_key_while_the_page_was_open_is_about_it() -> None:
    names = _names_holding({(NOTIFICATION_KEY, SOME_KEY): [_an_incident_during_the_page()]})

    Scenario() \
        .when(lambda: incidents_a_page_is_about(names, SOME_PAGE, [SOME_KEY],
                                                _the_pages_life())) \
        .then(_it_is_about([SOME_ARGUS_INCIDENT]))


@pytest.mark.unit
def test_an_incident_already_linked_to_the_page_is_about_it() -> None:
    # An earlier read matched the two, and that match stands whatever the keys
    # say now.
    names = _names_holding({(ON_CALL_INCIDENT, SOME_PAGE): [_an_incident_during_the_page()]})

    Scenario() \
        .when(lambda: incidents_a_page_is_about(names, SOME_PAGE, NO_KEYS,
                                                _the_pages_life())) \
        .then(_it_is_about([SOME_ARGUS_INCIDENT]))


@pytest.mark.unit
def test_an_incident_both_linked_and_keyed_is_named_once() -> None:
    the_incident = _an_incident_during_the_page()
    names = _names_holding({(ON_CALL_INCIDENT, SOME_PAGE): [the_incident],
                            (NOTIFICATION_KEY, SOME_KEY): [the_incident]})

    Scenario() \
        .when(lambda: incidents_a_page_is_about(names, SOME_PAGE, [SOME_KEY],
                                                _the_pages_life())) \
        .then(_it_is_about([SOME_ARGUS_INCIDENT]))


@pytest.mark.unit
def test_of_incidents_sharing_the_key_only_the_one_the_page_was_open_for_is_about_it() -> None:
    # The alert fired, Argus escalated, the alert stopped and the platform
    # closed its page; then it fired again, under the same key, and the
    # platform opened another. That page is about today's incident - and not
    # last week's, escalated and still resolvable.
    names = _names_holding({(NOTIFICATION_KEY, SOME_KEY): [
        _an_incident_over_before_the_page(SOME_OTHER_ARGUS_INCIDENT),
        _an_incident_during_the_page()
    ]})

    Scenario() \
        .when(lambda: incidents_a_page_is_about(names, SOME_PAGE, [SOME_KEY],
                                                _the_pages_life())) \
        .then(_it_is_about([SOME_ARGUS_INCIDENT]))


@pytest.mark.unit
def test_every_incident_the_page_was_open_for_is_about_it() -> None:
    # Argus said it mitigated the first and the alarm went on, so its reminder
    # opened a second - while the platform kept the one page open across both.
    names = _names_holding({(NOTIFICATION_KEY, SOME_KEY): [
        _an_incident(SOME_OTHER_ARGUS_INCIDENT, IncidentStatus.MITIGATED,
                     created_at=THE_PAGE_OPENED, ended_at=THE_PAGE_OPENED + 10 * A_MINUTE),
        _an_incident(SOME_ARGUS_INCIDENT, IncidentStatus.ESCALATED,
                     created_at=THE_PAGE_OPENED + 20 * A_MINUTE,
                     ended_at=THE_PAGE_OPENED + 25 * A_MINUTE)
    ]})

    Scenario() \
        .when(lambda: incidents_a_page_is_about(names, SOME_PAGE, [SOME_KEY],
                                                _the_pages_life())) \
        .then(_it_is_about([SOME_ARGUS_INCIDENT, SOME_OTHER_ARGUS_INCIDENT]))


@pytest.mark.unit
def test_a_page_opened_after_every_incident_under_its_key_ended_is_about_none() -> None:
    # Argus never had today's firing - it arrived nowhere, or was refused -
    # and the key's only holder is an incident that was over before the page
    # opened. Naming that one would carry a person's word to the wrong
    # incident.
    names = _names_holding({(NOTIFICATION_KEY, SOME_KEY): [
        _an_incident_over_before_the_page(SOME_ARGUS_INCIDENT)
    ]})

    Scenario() \
        .when(lambda: incidents_a_page_is_about(names, SOME_PAGE, [SOME_KEY],
                                                _the_pages_life())) \
        .then(_it_is_about([]))


@pytest.mark.unit
def test_a_page_no_incident_is_known_by_is_about_none() -> None:
    # The webhook covers every incident on the services it watches, and Argus
    # opened only some of them.
    names = _names_holding({})

    Scenario() \
        .when(lambda: incidents_a_page_is_about(names, SOME_PAGE, [SOME_KEY],
                                                _the_pages_life())) \
        .then(_it_is_about([]))


@pytest.mark.unit
def test_the_pages_life_is_not_read_where_no_incident_holds_one_of_its_keys() -> None:
    # Linked, so the page is about it - and nothing keyed to weigh, so when the
    # page was open is never asked: a platform that cannot say must not fail a
    # match the link alone settled.
    names = _names_holding({(ON_CALL_INCIDENT, SOME_PAGE): [_an_incident_during_the_page()]})
    the_pages_life = _the_pages_life()

    Scenario() \
        .when(lambda: incidents_a_page_is_about(names, SOME_PAGE, [SOME_KEY],
                                                the_pages_life)) \
        .then(all_of(
            _it_is_about([SOME_ARGUS_INCIDENT]),
            _the_pages_life_was_read(the_pages_life, times=0)
        ))


@pytest.mark.unit
def test_the_pages_life_is_read_once_however_many_incidents_hold_its_keys() -> None:
    # One page, open once: asking the platform again for each incident would
    # be a call to somebody else's API per incident for the same answer.
    names = _names_holding({(NOTIFICATION_KEY, SOME_KEY): [
        _an_incident_over_before_the_page(SOME_OTHER_ARGUS_INCIDENT),
        _an_incident_during_the_page()
    ]})
    the_pages_life = _the_pages_life()

    Scenario() \
        .when(lambda: incidents_a_page_is_about(names, SOME_PAGE, [SOME_KEY],
                                                the_pages_life)) \
        .then(_the_pages_life_was_read(the_pages_life, times=1))


@pytest.mark.unit
def test_a_failing_read_of_the_pages_life_is_raised() -> None:
    # Raised rather than swallowed, so the delivery is answered as a failure
    # and sent again - a match lost to a blip would be a person's word Argus
    # never heard.
    names = _names_holding({(NOTIFICATION_KEY, SOME_KEY): [_an_incident_during_the_page()]})
    the_pages_life = Mock(side_effect=_TheLifeUnreadable("unreachable"))

    Scenario() \
        .when(attempting(lambda: incidents_a_page_is_about(names, SOME_PAGE, [SOME_KEY],
                                                           the_pages_life))) \
        .then(an_error_was_raised(_TheLifeUnreadable))


def _the_pages_life() -> Mock:
    """When the page was open, as the platform would say it, counting each
    time it is asked."""
    return Mock(return_value=THE_PAGES_LIFE)


def _an_incident(incident_id: str,
                 status: IncidentStatus,
                 created_at: datetime,
                 ended_at: datetime | None) -> IncidentStanding:
    return IncidentStanding(id=incident_id, status=status,
                            created_at=created_at, ended_at=ended_at)


def _an_incident_during_the_page() -> IncidentStanding:
    """`SOME_ARGUS_INCIDENT`, opened with the page and still being worked."""
    return _an_incident(SOME_ARGUS_INCIDENT, IncidentStatus.INVESTIGATING,
                        created_at=THE_PAGE_OPENED + A_MINUTE, ended_at=None)


def _an_incident_over_before_the_page(incident_id: str) -> IncidentStanding:
    """An incident Argus escalated, which ended an hour before the page opened."""
    return _an_incident(incident_id, IncidentStatus.ESCALATED,
                        created_at=THE_PAGE_OPENED - 120 * A_MINUTE,
                        ended_at=THE_PAGE_OPENED - 60 * A_MINUTE)


def _names_holding(knowing: dict[tuple[str, str], list[IncidentStanding]]) -> Any:
    """The incidents' names, each as (kind, value) -> its holders."""
    names = create_autospec(IncidentNames, instance=True)

    def incidents_known_as(kind: str, values: list[str]) -> list[IncidentStanding]:
        found = {incident.id: incident
                 for value in values
                 for incident in knowing.get((kind, value), [])}

        return list(found.values())

    names.incidents_known_as.side_effect = incidents_known_as

    return names


def _it_is_about(incident_ids: list[str]) -> Assertion[list[str]]:
    """These, each once, and nothing else - in no order, since nothing about
    ending several depends on which ends first."""
    def assertion(about: list[str]) -> bool:
        if sorted(about) != sorted(incident_ids):
            raise AssertionError(
                f"Expected the page to be about {sorted(incident_ids)}, each once, got {about}"
            )

        return True

    return assertion


def _the_pages_life_was_read(the_pages_life: Mock, times: int) -> Assertion[object]:
    def assertion(_: object) -> bool:
        if the_pages_life.call_count != times:
            raise AssertionError(
                f"Expected when the page was open to be read [{times}] times, it was read "
                f"[{the_pages_life.call_count}]."
            )

        return True

    return assertion
