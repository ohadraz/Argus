from __future__ import annotations

from collections.abc import Callable

import pytest
from agent_communicator import notify
from argus_testkit.assertions import Assertion, all_of
from argus_testkit.scenario import Scenario


@pytest.mark.unit
def test_notify_emits_the_incident_and_the_message() -> None:
    Scenario() \
        .given(
            some_incident_id := "kuki-123",
            some_message := "escalating",
            notifications := _a_notification_log(),
        ) \
        .when(
            _notifying(some_incident_id, some_message, into=notifications)
        ) \
        .then(
            all_of(
                _the_notification_names(some_incident_id),
                _the_notification_names(some_message),
            )
        )


@pytest.mark.unit
def test_notify_does_not_raise_on_the_escalation_path() -> None:
    # This is a stub it must still be a *working* stub, or "Argus could not 
    # determine the cause" crashes the graph instead of reaching a human.
    notify("kuki-123", "escalating")


def _a_notification_log() -> list[str]:
    return []


def _notifying(incident_id: str, message: str, into: list[str]) -> Callable[[], list[str]]:
    """Emits the notification and yields what was recorded.

    `notify` returns nothing - what the test is about is the side effect, so
    the step hands the log to `then` rather than the call's `None`.
    """
    def emit_the_notification() -> list[str]:
        notify(incident_id, message, emit=into.append)
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
