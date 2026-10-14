"""What other tools call an incident, written down and found again.

The table a tool's later word about an incident is matched through: a person
resolving it in a paging tool arrives carrying that tool's names for it and
nothing of Argus's. So what this owes its readers is that a name, once given to
an incident, finds that incident - and that a name nobody gave finds nothing
rather than something close.

Most names are one incident's alone: a thread, a message in it, an offer posted
there. A few are shared by design, because the tool that hands them out cannot
tell Argus's incidents apart - every firing of an alert group pages under the
group's one key, one page can stay open across two incidents, and one firing
can be reminded of after Argus has opened a second incident for it. A shared
name finds every incident holding it, and which of them a tool meant is the
caller's to decide.
"""

from __future__ import annotations

import psycopg
import pytest
from argus_core import connect_from_env
from argus_core.models import (
    ALERT_FIRING,
    CHAT_THREAD,
    NOTIFICATION_KEY,
    ON_CALL_INCIDENT,
    Alert,
    Incident,
    IncidentStatus,
    Reference,
    a_chat_thread,
)
from argus_incidents.repository import incidents, references
from argus_testkit import Assertion, Scenario, calling

from argus_incidents_test.framework import no_column_is_empty
from argus_incidents_test.framework.builders import an_incident_created_for

SOME_KIND = "some-kind"


@pytest.mark.integration
def test_an_incident_is_found_by_any_one_of_its_names() -> None:
    # A paging tool hands back every key its incident carries - several, where
    # alerts were merged into it - and only one of them need be Argus's.
    some_name = _a_reference(SOME_KIND, "k-1")

    with connect_from_env() as conn:
        some_incident = an_incident_created_for(conn, _an_alert())

        Scenario() \
            .given(calling(lambda: references.add(conn, some_incident, [some_name]))) \
            .when(lambda: references.get_incidents_by_values(
                conn, SOME_KIND, ["some-unknown-key", some_name.value]
            )) \
            .then(_the_incidents_found_are([some_incident]))


@pytest.mark.integration
def test_a_name_nobody_gave_finds_no_incident() -> None:
    # The caller's cue that the tool is talking about an incident Argus never
    # had - which it says and then ignores, rather than acting on a neighbour.
    with connect_from_env() as conn:
        Scenario() \
            .given(SOME_KIND) \
            .when(lambda: references.get_incidents_by_values(
                conn, SOME_KIND, ["some-unknown-key"]
            )) \
            .then(_the_incidents_found_are([]))


@pytest.mark.integration
def test_a_name_of_another_kind_is_not_mistaken_for_this_one() -> None:
    # One tool names an incident several ways, and two tools can hand out the
    # same string. A value matched without its kind is a resolution reaching
    # whichever incident happened to share a spelling.
    some_value = "k-1"

    with connect_from_env() as conn:
        some_incident = an_incident_created_for(conn, _an_alert())

        Scenario() \
            .given(calling(lambda: references.add(
                conn, some_incident, [_a_reference("some-other-kind", some_value)]
            ))) \
            .when(lambda: references.get_incidents_by_values(
                conn, SOME_KIND, [some_value]
            )) \
            .then(_the_incidents_found_are([]))


@pytest.mark.integration
def test_a_name_already_given_stays_with_the_incident_that_had_it() -> None:
    # A name of Argus's own giving is one incident's: a message in a thread
    # must reach exactly one. A second incident claiming it is the same name
    # arriving again, and the first holder keeps it - the write does not fail,
    # because whatever brought it is still worth recording the rest of.
    some_name = _a_reference(SOME_KIND, "k-1")

    with connect_from_env() as conn:
        the_first_holder = an_incident_created_for(conn, _an_alert())
        some_later_incident = an_incident_created_for(conn, _an_alert())

        Scenario() \
            .given(
                calling(lambda: references.add(conn, the_first_holder, [some_name])),
                calling(lambda: references.add(conn, some_later_incident, [some_name])),
                calling(lambda: references.add(conn, the_first_holder, [some_name]))
            ) \
            .when(lambda: references.get_incidents_by_values(
                conn, SOME_KIND, [some_name.value]
            )) \
            .then(_the_incidents_found_are([the_first_holder]))


@pytest.mark.integration
@pytest.mark.parametrize("kind", [NOTIFICATION_KEY, ON_CALL_INCIDENT, ALERT_FIRING])
def test_a_name_several_incidents_share_finds_every_one_of_them(kind: str) -> None:
    # The key of an alert group is every firing's key, a page left open
    # across two incidents is both incidents' page, and a firing reminded of
    # after a mitigation is both incidents' firing. Kept by the first holder
    # alone, the name would send every later word about the second to the
    # first.
    some_name = _a_reference(kind, "k-1")

    with connect_from_env() as conn:
        the_first_holder = an_incident_created_for(conn, _an_alert())
        the_second_holder = an_incident_created_for(conn, _an_alert())

        Scenario() \
            .given(
                calling(lambda: references.add(conn, the_first_holder, [some_name])),
                calling(lambda: references.add(conn, the_second_holder, [some_name]))
            ) \
            .when(lambda: references.get_incidents_by_values(conn, kind, [some_name.value])) \
            .then(_the_incidents_found_are([the_first_holder, the_second_holder]))


@pytest.mark.integration
def test_a_shared_name_given_twice_to_one_incident_is_held_once() -> None:
    # A webhook delivered twice, or a reminder of the firing that opened the
    # incident, is the same name arriving again for the same incident.
    some_name = _a_reference(NOTIFICATION_KEY, "k-1")

    with connect_from_env() as conn:
        some_incident = an_incident_created_for(conn, _an_alert())

        Scenario() \
            .given(
                calling(lambda: references.add(conn, some_incident, [some_name])),
                calling(lambda: references.add(conn, some_incident, [some_name]))
            ) \
            .when(lambda: references.get_values_for(conn, some_incident, NOTIFICATION_KEY)) \
            .then(_the_values_are([some_name.value]))


@pytest.mark.integration
def test_an_incident_found_by_a_name_is_found_as_it_stands() -> None:
    # Which of several holders a tool meant is read from when each was going
    # on, so an incident found is the whole row - an ended one with its end.
    some_name = _a_reference(NOTIFICATION_KEY, "k-1")

    with connect_from_env() as conn:
        some_incident = an_incident_created_for(conn, _an_alert())

        Scenario() \
            .given(
                calling(lambda: references.add(conn, some_incident, [some_name])),
                calling(lambda: incidents.transition(
                    conn, some_incident, IncidentStatus.ESCALATED
                ))
            ) \
            .when(lambda: references.get_incidents_by_values(
                conn, NOTIFICATION_KEY, [some_name.value]
            )) \
            .then(_they_are_as_recorded(conn, [some_incident]))


@pytest.mark.integration
def test_a_name_leaves_no_column_of_its_row_empty() -> None:
    with connect_from_env() as conn:
        some_incident = an_incident_created_for(conn, _an_alert())

        Scenario() \
            .when(lambda: references.add(
                conn, some_incident, [_a_reference(SOME_KIND, "k-1")]
            )) \
            .then(no_column_is_empty(conn, "incident_reference", "incident_id", some_incident))


@pytest.mark.integration
def test_an_incidents_names_of_one_kind_are_read_back() -> None:
    # What engagement asks the platform with, where nothing linked the two
    # incidents yet: every key the monitor paged under for this one.
    with connect_from_env() as conn:
        some_incident = an_incident_created_for(conn, _an_alert())
        some_values = ["k-1", "k-2"]

        Scenario() \
            .given(calling(lambda: references.add(conn, some_incident, [
                *(_a_reference(SOME_KIND, value) for value in some_values),
                _a_reference("some-other-kind", "k-3")
            ]))) \
            .when(lambda: references.get_values_for(conn, some_incident, SOME_KIND)) \
            .then(_the_values_are(some_values))


@pytest.mark.integration
def test_an_incident_keeps_the_first_thread_it_was_told_in_a_channel() -> None:
    # Two relays at once, or a pass repeated after a crash, each open a thread.
    # The people already reading the first one are where the rest of the
    # incident has to go, so the second is never recorded - though it is a
    # different name, and nothing else stops it.
    the_first_thread = a_chat_thread("some-chat", "C-some-channel", "1.000100")

    with connect_from_env() as conn:
        some_incident = an_incident_created_for(conn, _an_alert())

        Scenario() \
            .given(
                calling(lambda: references.add(conn, some_incident, [the_first_thread])),
                calling(lambda: references.add(conn, some_incident, [
                    a_chat_thread("some-chat", "C-some-channel", "2.000200")
                ]))
            ) \
            .when(lambda: references.get_values_for(conn, some_incident, CHAT_THREAD)) \
            .then(_the_values_are([the_first_thread.value]))


@pytest.mark.integration
def test_an_incident_is_told_in_a_thread_of_its_own_in_each_channel() -> None:
    some_threads = [
        a_chat_thread("some-chat", "C-some-channel", "1.000100"),
        a_chat_thread("some-chat", "C-some-other-channel", "2.000200")
    ]

    with connect_from_env() as conn:
        some_incident = an_incident_created_for(conn, _an_alert())

        Scenario() \
            .given(calling(lambda: references.add(conn, some_incident, some_threads))) \
            .when(lambda: references.get_values_for(conn, some_incident, CHAT_THREAD)) \
            .then(_the_values_are([thread.value for thread in some_threads]))


def _the_values_are(expected: list[str]) -> Assertion[list[str]]:
    def assertion(values: list[str]) -> bool:
        if sorted(values) != sorted(expected):
            raise AssertionError(f"Expected the names {expected}, got {values}.")

        return True

    return assertion


def _an_alert() -> Alert:
    return Alert(service="checkout", alert_name="HighErrorRate")


def _a_reference(kind: str, value: str) -> Reference:
    return Reference(source="some-tool", kind=kind, value=value)


def _the_incidents_found_are(expected: list[str]) -> Assertion[list[Incident]]:
    """The incidents found, in no order: nothing a caller does with several
    holders depends on which came back first."""
    def assertion(found: list[Incident]) -> bool:
        found_ids = [incident.id for incident in found]

        if sorted(found_ids) != sorted(expected):
            raise AssertionError(
                f"Expected the name to find the incidents {sorted(expected)}, got "
                f"{sorted(found_ids)}."
            )

        return True

    return assertion


def _they_are_as_recorded(conn: psycopg.Connection,
                          expected: list[str]) -> Assertion[list[Incident]]:
    def assertion(found: list[Incident]) -> bool:
        recorded = [incidents.get(conn, incident_id) for incident_id in expected]

        if found != recorded:
            raise AssertionError(f"Expected the incidents found to be {recorded}, got {found}.")

        return True

    return assertion
