"""What Argus says in Slack, said through the real adapter.

The double stands where Slack does, so what is exercised here is the client the
adapter builds, the arguments the SDK encodes and the answer it parses - not a
mock of any of them. A test double for the *SDK* would assert that Argus calls
a method, which is the one thing that was never in doubt.

The channel is arbitrary in every case. What is not arbitrary is that the
message arrives where it was addressed and says what it was given: a message
delivered to the wrong channel is indistinguishable, from inside Argus, from
one delivered correctly.
"""

from __future__ import annotations

from typing import Any

import pytest
from argus_core import utc_now
from argus_testkit import Assertion, Scenario, all_of
from chat_platform import Line, Posted
from chat_platform.slack import ChatSettings, Slack
from slack_sdk import WebClient

from chat_platform_test.framework.slack import messages_posted_to

DONT_CARE_LINE = Line(who="dont care", text="dont care")


@pytest.mark.component
def test_a_message_arrives_with_the_channel_and_text_it_was_given(slack: str) -> None:
    some_channel = "C-war-room"
    some_line = Line(who="Investigator Agent",
                     text="Picked up kuki-123: HighErrorRate on io-shop")

    Scenario() \
        .given(
            a_platform_pointed_at_the_double := _slack_at(slack)
        ) \
        .when(
            lambda: a_platform_pointed_at_the_double.post(some_channel, some_line)
        ) \
        .then(
            all_of(
                _slack_holds_one_message(slack),
                _that_message_went_to(slack, some_channel),
                _that_message_said(slack, f"{some_line.who}: {some_line.text}")
            )
        )


@pytest.mark.component
def test_a_delivered_message_answers_with_the_id_slack_gave_it(slack: str) -> None:
    # The id is the whole reason this returns anything. An incident's war room
    # is a thread, and a thread is named by its parent's id - so a post whose
    # answer was discarded is a war room nothing can reply into.
    dont_care_channel = "C-war-room"

    Scenario() \
        .given(
            a_platform_pointed_at_the_double := _slack_at(slack)
        ) \
        .when(
            lambda: a_platform_pointed_at_the_double.post(dont_care_channel, DONT_CARE_LINE)
        ) \
        .then(
            _it_is_the_id_of_the_message_slack_holds(slack)
        )


def _slack_at(base_url: str) -> Slack:
    """The adapter, aimed at `base_url` as a deployment would aim it.

    A token because a workspace without one builds no platform, and an empty
    signing secret because nothing here reads a delivery.
    """
    return Slack(
        ChatSettings(slack_bot_token="xoxb-dont-care",
                     slack_base_url=base_url,
                     slack_signing_secret=""),
        client_of=WebClient,
        clock=utc_now
    )


def _slack_holds_one_message(base_url: str) -> Assertion[Any]:
    def assertion(_result: Any) -> bool:
        held = messages_posted_to(base_url)
        if len(held) != 1:
            raise AssertionError(f"Expected one message in Slack, got {len(held)}: {held}.")

        return True

    return assertion


def _that_message_went_to(base_url: str, channel: str) -> Assertion[Any]:
    def assertion(_result: Any) -> bool:
        addressed = [message["channel"] for message in messages_posted_to(base_url)]
        if addressed != [channel]:
            raise AssertionError(f"Expected it addressed to [{channel}], got {addressed}.")

        return True

    return assertion


def _that_message_said(base_url: str, text: str) -> Assertion[Any]:
    def assertion(_result: Any) -> bool:
        said = [message["text"] for message in messages_posted_to(base_url)]
        if said != [text]:
            raise AssertionError(f"Expected it to say [{text}], got {said}.")

        return True

    return assertion


def _it_is_the_id_of_the_message_slack_holds(base_url: str) -> Assertion[Posted]:
    def assertion(answered: Posted) -> bool:
        held = messages_posted_to(base_url)
        if not held:
            raise AssertionError("Expected a message in Slack to compare the id against.")

        if answered.message != held[0]["ts"]:
            raise AssertionError(
                f"Expected the id [{held[0]['ts']}] Slack gave the message, got "
                f"[{answered.message}]."
            )

        return True

    return assertion
