"""One look at the messages nobody has understood, from the intent reader's side.

The intent reader finds its work on the incident record rather than in the event
log: a message is the agent's to understand until the record says what it
meant, so the record is what it asks. Each look takes the oldest first, because
a message understood out of order can be offered after a later one that changed
it.

A message that could not be understood - the model unreachable, the database
gone - stops the look where it is. The next look finds it again, because a
person's words skipped are words Argus never took in, and the messages behind
it wait rather than being understood out of order.

The record is stood in for: it is `incident_record`' and tested there.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import pytest
from argus_testkit import Assertion, Scenario, all_of, one_record_was_logged
from core import LLMSettings, Settings, get_settings, new_id
from core.llm.adapters.anthropic_adapter import AnthropicProvider
from core.models import ModelPolicy, Reasoning, ThreadMessage, a_chat_message
from message_intent.watching import the_model_for, watch_once

# The chat platform's name, as its adapter gives it - what a reader is
# told a report came from, and what its references are filed under.
THE_CHAT_PLATFORM = "Slack"

SOME_INCIDENT = new_id()
SOME_TIME = datetime(2026, 10, 11, 1, 0, tzinfo=UTC)

# Where this process's model is reached, and which model and effort the Intent
# Reader asks - none of them the defaults, so a binding that ignored the
# settings could not pass by agreeing with them.
SOME_ADDRESS = "http://intent-reader.invalid"
SOME_MODEL = "claude-haiku-4-5"
SOME_EFFORT = Reasoning.LOW


@pytest.mark.unit
def test_the_model_is_reached_where_the_settings_say_under_the_intent_readers_policy() -> None:
    # The one place this process chooses who answers. Read off the binding,
    # because that is the only place it can be seen: a client built from the
    # wrong address or under the wrong model answers in the same shape.
    some_settings = LLMSettings(anthropic_api_key="", anthropic_base_url=SOME_ADDRESS)

    Scenario() \
        .given(
            the_process_settings := _settings_reaching(some_settings)
        ) \
        .when(lambda: the_model_for(the_process_settings)) \
        .then(_built_over(AnthropicProvider(some_settings),
                          ModelPolicy(model=SOME_MODEL, effort=SOME_EFFORT)))


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
            one_record_was_logged(caplog, "message_intent.watching", logging.WARNING,
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
                         message=a_chat_message(THE_CHAT_PLATFORM, "C-some-channel", words),
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


def _settings_reaching(reached_by: LLMSettings) -> Settings:
    """The process's settings, reaching the model where `reached_by` says, under
    this file's model and effort for the Intent Reader."""
    return get_settings().model_copy(update={
        "anthropic_api_key": reached_by.anthropic_api_key,
        "anthropic_base_url": reached_by.anthropic_base_url,
        "intent_model": SOME_MODEL,
        "intent_effort": SOME_EFFORT
    })


def _built_over(provider: AnthropicProvider, policy: ModelPolicy) -> Assertion[Any]:
    """That the binding builds each client over `provider`, under `policy`."""
    def assertion(binding: Any) -> bool:
        reached = next(iter(getattr(binding, "args", ())), None)
        asked_under = getattr(binding, "keywords", {}).get("policy")

        if reached != provider or asked_under != policy:
            # By address alone: the settings carry the key.
            raise AssertionError(
                f"Expected clients built over the provider at "
                f"[{provider.settings.anthropic_base_url}] under [{policy}], got one at "
                f"[{getattr(getattr(reached, 'settings', None), 'anthropic_base_url', None)}] "
                f"under [{asked_under}]."
            )

        return True

    return assertion
