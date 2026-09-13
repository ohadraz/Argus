from __future__ import annotations

from typing import Any

import httpx
import pytest
from agent_communicator.slack import Posted, a_slack_client, post_message
from argus_testkit import Assertion, Scenario, all_of

"""What Argus says in Slack, said through the real adapter.

The double stands where Slack does, so what is exercised here is the client the
demo builds, the arguments the SDK encodes and the answer it parses - not a
mock of any of them. A test double for the *SDK* would assert that Argus calls
a method, which is the one thing that was never in doubt.

The channel is arbitrary in every case. What is not arbitrary is that the
message arrives where it was addressed and says what it was given: a message
delivered to the wrong channel is indistinguishable, from inside Argus, from
one delivered correctly.
"""


@pytest.mark.component
def test_a_message_arrives_with_the_channel_and_text_it_was_given(slack: str) -> None:
    some_channel = "C-war-room"
    some_text = "Argus picked up kuki-123: HighErrorRate on io-shop"

    Scenario() \
        .given(
            a_client_pointed_at_the_double := a_slack_client(base_url=slack)
        ) \
        .when(
            lambda: post_message(some_channel, some_text, slack=a_client_pointed_at_the_double)
        ) \
        .then(
            all_of(
                _slack_holds_one_message(slack),
                _that_message_went_to(slack, some_channel),
                _that_message_said(slack, some_text)
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
            a_client_pointed_at_the_double := a_slack_client(base_url=slack)
        ) \
        .when(
            lambda: post_message(
                dont_care_channel, "dont care", slack=a_client_pointed_at_the_double
            )
        ) \
        .then(
            _it_is_the_id_of_the_message_slack_holds(slack)
        )


def _posted(base_url: str) -> list[dict[str, Any]]:
    """Every message the double accepted, read back through its control seam."""
    answered: dict[str, Any] = httpx.get(f"{base_url}/double-control/posted").json()
    held: list[dict[str, Any]] = answered["posted"]

    return held


def _slack_holds_one_message(base_url: str) -> Assertion[Any]:
    def assertion(_result: Any) -> bool:
        held = _posted(base_url)
        if len(held) != 1:
            raise AssertionError(f"Expected one message in Slack, got {len(held)}: {held}.")

        return True

    return assertion


def _that_message_went_to(base_url: str, channel: str) -> Assertion[Any]:
    def assertion(_result: Any) -> bool:
        addressed = [message["channel"] for message in _posted(base_url)]
        if addressed != [channel]:
            raise AssertionError(f"Expected it addressed to [{channel}], got {addressed}.")

        return True

    return assertion


def _that_message_said(base_url: str, text: str) -> Assertion[Any]:
    def assertion(_result: Any) -> bool:
        said = [message["text"] for message in _posted(base_url)]
        if said != [text]:
            raise AssertionError(f"Expected it to say [{text}], got {said}.")

        return True

    return assertion


def _it_is_the_id_of_the_message_slack_holds(base_url: str) -> Assertion[Posted]:
    def assertion(answered: Posted) -> bool:
        held = _posted(base_url)
        if not held:
            raise AssertionError("Expected a message in Slack to compare the id against.")

        if answered.ts != held[0]["ts"]:
            raise AssertionError(
                f"Expected the id [{held[0]['ts']}] Slack gave the message, got [{answered.ts}]."
            )

        return True

    return assertion
