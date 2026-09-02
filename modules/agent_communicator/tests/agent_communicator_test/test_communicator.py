from __future__ import annotations

from collections.abc import Callable

import pytest
from agent_communicator import post_update, raise_page
from argus_testkit.assertions import Assertion, all_of
from argus_testkit.scenario import Scenario

"""Telling a human, in the two registers Argus has.

An update is written into the incident's war room while Argus still has moves:
it is read by whoever is watching, and it wakes nobody. A page is the one
message that says autonomy is spent and a person is now required.

Two functions rather than one with a severity argument, because the caller has
to choose anyway and this way the choice is visible at the call site - a page
cannot be produced by wording an update differently.
"""


@pytest.mark.unit
def test_an_update_names_the_incident_and_what_happened() -> None:
    Scenario() \
        .given(
            some_incident_id := "kuki-123",
            some_message := "reverted monthly-spend-feature, no recovery",
            notifications := _a_notification_log(),
        ) \
        .when(
            _posting_an_update(some_incident_id, some_message, into=notifications)
        ) \
        .then(
            all_of(
                _the_notification_names(some_incident_id),
                _the_notification_names(some_message),
            )
        )


@pytest.mark.unit
def test_a_page_names_the_incident_and_why_it_is_being_raised() -> None:
    Scenario() \
        .given(
            some_incident_id := "kuki-123",
            some_message := "every explanation was tried and refuted",
            notifications := _a_notification_log(),
        ) \
        .when(
            _raising_a_page(some_incident_id, some_message, into=notifications)
        ) \
        .then(
            all_of(
                _the_notification_names(some_incident_id),
                _the_notification_names(some_message),
            )
        )


@pytest.mark.unit
def test_a_page_does_not_read_like_an_update() -> None:
    # The distinction has to survive the trip to whoever is reading. Two
    # messages that differ only in which function produced them would leave a
    # human unable to tell the walk carrying on from the walk being over -
    # which is the whole of what these two say.
    dont_care_incident_id = "kuki-123"
    same_message = "monthly-spend-feature was reverted"
    an_update_log = _a_notification_log()
    a_page_log = _a_notification_log()

    post_update(dont_care_incident_id, same_message, emit=an_update_log.append)
    raise_page(dont_care_incident_id, same_message, emit=a_page_log.append)

    assert an_update_log[0] != a_page_log[0]


@pytest.mark.unit
def test_neither_raises_on_the_escalation_path() -> None:
    # These are stubs, but they must be *working* stubs: escalation routes
    # through the Communicator, so a stub that raises turns "Argus could not
    # determine the cause" into a crash.
    dont_care_incident_id = "kuki-123"

    post_update(dont_care_incident_id, "still trying")
    raise_page(dont_care_incident_id, "escalating")


def _a_notification_log() -> list[str]:
    return []


def _posting_an_update(
    incident_id: str, message: str, into: list[str]
) -> Callable[[], list[str]]:
    """Emits the update and yields what was recorded.

    The call returns nothing - what the test is about is the side effect, so
    the step hands the log to `then` rather than the call's `None`.
    """
    def emit_the_notification() -> list[str]:
        post_update(incident_id, message, emit=into.append)
        return into

    return emit_the_notification


def _raising_a_page(
    incident_id: str, message: str, into: list[str]
) -> Callable[[], list[str]]:
    def emit_the_notification() -> list[str]:
        raise_page(incident_id, message, emit=into.append)
        return into

    return emit_the_notification


def _the_notification_names(expected: str) -> Assertion[list[str]]:
    def assertion(notifications: list[str]) -> bool:
        assert notifications, f"Expected a notification naming [{expected}], got none."
        assert expected in notifications[0], (
            f"Expected [{expected}] in the notification, got [{notifications[0]}]."
        )
        return True

    return assertion
