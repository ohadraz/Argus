"""One look at the messages nobody has understood, from the intent agent's side.

The intent agent finds its work on the incident record rather than in the event
log: a message is the agent's to understand until the record says what it
meant, so the record is what it asks. Each look takes the oldest first, because
a message understood out of order can be offered after a later one that changed
it.

A message that could not be understood - the model unreachable, the database
gone - stops the look where it is. The next look finds it again, because a
person's words skipped are words Argus never took in, and the messages behind
it wait rather than being understood out of order.

The record is stood in for: it is `argus_incidents`' and tested there.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime

import pytest
from agent_intent.watching import watch_once
from argus_core import new_id
from argus_core.models import ReportChannel, ThreadMessage, a_chat_message
from argus_testkit import Assertion, Scenario, all_of, one_record_was_logged

SOME_INCIDENT = new_id()
SOME_TIME = datetime(2026, 10, 11, 1, 0, tzinfo=UTC)


@pytest.mark.unit
def test_each_message_nobody_has_understood_is_understood_in_the_order_found() -> None:
    first, second = _a_person_writing("first"), _a_person_writing("second")
    understood: list[ThreadMessage] = []

    Scenario() \
        .when(lambda: watch_once(_not_understood(first, second), understood.append)) \
        .then(_it_understood(understood, [first, second]))


@pytest.mark.unit
def test_a_message_that_could_not_be_understood_stops_the_look_in_front_of_it(
        caplog: pytest.LogCaptureFixture) -> None:
    first, second = _a_person_writing("first"), _a_person_writing("second")
    tried: list[ThreadMessage] = []

    def understanding_fails(written: ThreadMessage) -> None:
        tried.append(written)
        raise ConnectionError("the model could not be reached")

    Scenario() \
        .when(lambda: watch_once(_not_understood(first, second), understanding_fails)) \
        .then(all_of(
            _it_understood(tried, [first]),
            one_record_was_logged(caplog, "agent_intent.watching", logging.WARNING,
                                  "message not understood", failure=ConnectionError)
        ))


@pytest.mark.unit
@pytest.mark.parametrize(("waiting", "understood"), [(0, 0), (3, 3)])
def test_a_look_says_how_many_messages_it_understood(waiting: int, understood: int) -> None:
    # What the process waits on: a look that found nothing waits before the
    # next, and one that found something looks again at once.
    some_messages = [_a_person_writing(f"message {n}") for n in range(waiting)]

    Scenario() \
        .when(lambda: watch_once(_not_understood(*some_messages), lambda _: None)) \
        .then(_it_answers(understood))


@pytest.mark.unit
def test_a_message_that_could_not_be_understood_is_not_counted() -> None:
    # A look whose only message failed found nothing it could do, and waits
    # before trying it again rather than spinning on it.
    def understanding_fails(_written: ThreadMessage) -> None:
        raise ConnectionError("the model could not be reached")

    Scenario() \
        .when(lambda: watch_once(_not_understood(_a_person_writing("first")),
                                 understanding_fails)) \
        .then(_it_answers(0))


@pytest.mark.unit
def test_a_look_asks_for_no_more_than_a_batch() -> None:
    # A few looks to catch up after a restart, never an hour of messages in
    # memory at once.
    asked_for: list[int] = []
    some_batch = 7

    def not_understood(limit: int) -> list[ThreadMessage]:
        asked_for.append(limit)
        return []

    Scenario() \
        .when(lambda: watch_once(not_understood, lambda _: None, batch=some_batch)) \
        .then(_it_asked_for(asked_for, [some_batch]))


def _a_person_writing(words: str) -> ThreadMessage:
    return ThreadMessage(incident_id=SOME_INCIDENT,
                         message=a_chat_message(ReportChannel.SLACK, "C-some-channel", words),
                         person_id="U-some-person",
                         text=words,
                         written_at=SOME_TIME)


def _not_understood(*messages: ThreadMessage) -> Callable[[int], list[ThreadMessage]]:
    def not_understood(limit: int) -> list[ThreadMessage]:
        return list(messages)[:limit]

    return not_understood


def _it_understood(understood: list[ThreadMessage],
                   expected: list[ThreadMessage]) -> Assertion[object]:
    def assertion(_: object) -> bool:
        if understood != expected:
            raise AssertionError(
                f"Expected to understand {[w.text for w in expected]}, "
                f"understood {[w.text for w in understood]}."
            )

        return True

    return assertion


def _it_answers(expected: int) -> Assertion[int]:
    def assertion(looked_at: int) -> bool:
        if looked_at != expected:
            raise AssertionError(f"Expected {expected} messages understood, got {looked_at}.")

        return True

    return assertion


def _it_asked_for(asked_for: list[int], expected: list[int]) -> Assertion[object]:
    def assertion(_: object) -> bool:
        if asked_for != expected:
            raise AssertionError(f"Expected the look to ask for {expected}, got {asked_for}.")

        return True

    return assertion
