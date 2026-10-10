"""What other tools call an incident, written down and found again.

The table a tool's later word about an incident is matched through: a person
resolving it in a paging tool arrives carrying that tool's names for it and
nothing of Argus's. So what this owes its readers is that a name, once given to
an incident, finds that incident and no other - and that a name nobody gave
finds nothing rather than something close.
"""

from __future__ import annotations

import pytest
from argus_core import connect_from_env
from argus_core.models import CHAT_THREAD, Alert, Reference, a_chat_thread
from argus_incidents.repository import references
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
            .when(lambda: references.get_incident_by_values(
                conn, SOME_KIND, ["some-unknown-key", some_name.value]
            )) \
            .then(_the_incident_found_is(some_incident))


@pytest.mark.integration
def test_a_name_nobody_gave_finds_no_incident() -> None:
    # The caller's cue that the tool is talking about an incident Argus never
    # had - which it says and then ignores, rather than acting on a neighbour.
    with connect_from_env() as conn:
        Scenario() \
            .given(SOME_KIND) \
            .when(lambda: references.get_incident_by_values(
                conn, SOME_KIND, ["some-unknown-key"]
            )) \
            .then(_the_incident_found_is(None))


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
            .when(lambda: references.get_incident_by_values(
                conn, SOME_KIND, [some_value]
            )) \
            .then(_the_incident_found_is(None))


@pytest.mark.integration
def test_a_name_already_given_stays_with_the_incident_that_had_it() -> None:
    # One name, one incident: a tool saying something about it must reach
    # exactly one. A second incident claiming a name is the same name arriving
    # again, and the first holder keeps it - the write does not fail, because
    # the alert that brought it is still worth opening an incident for.
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
            .when(lambda: references.get_incident_by_values(
                conn, SOME_KIND, [some_name.value]
            )) \
            .then(_the_incident_found_is(the_first_holder))


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
def test_a_first_claim_on_a_name_says_it_wrote() -> None:
    with connect_from_env() as conn:
        some_incident = an_incident_created_for(conn, _an_alert())

        Scenario() \
            .when(lambda: references.claim(
                conn, some_incident, _a_reference(SOME_KIND, "k-1")
            )) \
            .then(_it_wrote(True))


@pytest.mark.integration
def test_a_name_claimed_again_says_it_wrote_nothing() -> None:
    # A message the chat platform delivers twice is one message, and the second
    # delivery must know it is the second - or a person's words are read, and
    # offered back to them, twice.
    some_name = _a_reference(SOME_KIND, "k-1")

    with connect_from_env() as conn:
        some_incident = an_incident_created_for(conn, _an_alert())

        Scenario() \
            .given(calling(lambda: references.claim(conn, some_incident, some_name))) \
            .when(lambda: references.claim(conn, some_incident, some_name)) \
            .then(_it_wrote(False))


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


def _it_wrote(expected: bool) -> Assertion[bool]:
    def assertion(wrote: bool) -> bool:
        if wrote != expected:
            raise AssertionError(
                f"Expected the claim to report that it {'wrote' if expected else 'wrote nothing'}, "
                f"got {wrote}."
            )

        return True

    return assertion


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


def _the_incident_found_is(expected: str | None) -> Assertion[str | None]:
    def assertion(found: str | None) -> bool:
        if found != expected:
            raise AssertionError(
                f"Expected the name to find the incident [{expected}], got "
                f"[{found}]."
            )

        return True

    return assertion
