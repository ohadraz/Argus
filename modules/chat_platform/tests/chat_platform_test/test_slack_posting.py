"""What Argus says in Slack, in Slack's own markup, and the one request whose
arguments matter more than its outcome.

Most of posting is asserted through the real SDK against the double, in the
component suite. Two things cannot be. A line's markup is a pure function of
the line, and needs no workspace to say what it comes out as. And a rewrite
takes a message's blocks away by naming an empty list, where leaving them out
would have the same outcome only because the text is given too - Slack's rule,
which the double keeps, so nothing the double holds afterwards tells the two
apart. Only the arguments do, which is why the client is stood in for here.
"""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import create_autospec

import pytest
from argus_testkit import Assertion, Scenario, all_of, one_record_was_logged
from chat_platform import Line, Link, Posted
from chat_platform.slack_posting import as_slack_says_it, update_message
from slack_sdk import WebClient

SOME_AGENT = "Mitigation Agent"
SOME_CHANNEL = "C-war-room"
SOME_MESSAGE = "1760000300.000400"

DONT_CARE_TEXT = "dont care"


@pytest.mark.unit
def test_a_line_is_said_by_the_agent_saying_it() -> None:
    some_line = Line(who=SOME_AGENT, text="Rolled io-shop back to the previous release")

    Scenario() \
        .when(lambda: as_slack_says_it(some_line)) \
        .then(_it_says(f"{SOME_AGENT}: Rolled io-shop back to the previous release"))


@pytest.mark.unit
def test_the_emphasised_word_is_marked_where_the_line_splits_it() -> None:
    # The word is in the sentence twice. Marked by searching for it, the first
    # would be - and that is not the one the line set apart.
    some_line = Line(who=SOME_AGENT,
                     text="The flag that turned checkout off is now off",
                     before_emphasis="The flag that turned checkout off is now ",
                     emphasis="off")

    Scenario() \
        .when(lambda: as_slack_says_it(some_line)) \
        .then(_it_says(f"{SOME_AGENT}: The flag that turned checkout off is now *off*"))


@pytest.mark.unit
def test_a_link_goes_on_a_line_of_its_own_under_the_sentence() -> None:
    some_url = "http://argus.example/incidents/some-incident"
    some_label = "The incident in Argus"
    some_line = Line(who=SOME_AGENT, text="Escalated to a person",
                     link=Link(url=some_url, label=some_label))

    Scenario() \
        .when(lambda: as_slack_says_it(some_line)) \
        .then(_it_says(f"{SOME_AGENT}: Escalated to a person\n<{some_url}|{some_label}>"))


@pytest.mark.unit
def test_a_rewrite_takes_every_block_away_by_naming_none() -> None:
    # What a rewrite is for is taking a button away. Said with an empty list,
    # so it does not rest on the SDK dropping a `None` and on Slack then
    # clearing blocks because the text was given.
    slack = _a_client()

    Scenario() \
        .when(lambda: update_message(SOME_CHANNEL, SOME_MESSAGE, DONT_CARE_TEXT, slack=slack)) \
        .then(_it_was_rewritten_with_no_blocks(slack))


@pytest.mark.unit
def test_a_rewrite_to_a_workspace_that_cannot_be_reached_is_survived_and_worth_another_go(
        caplog: pytest.LogCaptureFixture) -> None:
    # Nothing answered, which says nothing about the rewrite - so the button
    # it was taking away is worth taking away on a later pass.
    some_failure = "connection refused"
    slack = _a_client(failing_with=OSError(some_failure))

    Scenario() \
        .when(lambda: update_message(SOME_CHANNEL, SOME_MESSAGE, DONT_CARE_TEXT, slack=slack)) \
        .then(all_of(
            _it_answered(Posted(None, refusal=some_failure, worth_another_go=True)),
            one_record_was_logged(caplog, "chat_platform.slack_posting", logging.WARNING,
                                  "slack could not be reached",
                                  values={"channel": SOME_CHANNEL}, failure=OSError)
        ))


def _a_client(failing_with: Exception | None = None) -> Any:
    """A Slack client whose rewrite answers with the message's id, or fails."""
    slack = create_autospec(WebClient, instance=True)
    slack.chat_update.return_value = {"ts": SOME_MESSAGE}
    slack.chat_update.side_effect = failing_with

    return slack


def _it_says(expected: str) -> Assertion[str]:
    def assertion(said: str) -> bool:
        if said != expected:
            raise AssertionError(f"Expected the line said as [{expected!r}], got [{said!r}].")

        return True

    return assertion


def _it_was_rewritten_with_no_blocks(slack: Any) -> Assertion[object]:
    def assertion(_: object) -> bool:
        named = [call.kwargs.get("blocks", "<absent>")
                 for call in slack.chat_update.call_args_list]

        if named != [[]]:
            raise AssertionError(
                f"Expected one rewrite naming an empty list of blocks, got {named}."
            )

        return True

    return assertion


def _it_answered(expected: Posted) -> Assertion[Posted]:
    def assertion(answered: Posted) -> bool:
        if answered != expected:
            raise AssertionError(f"Expected {expected!r}, got {answered!r}.")

        return True

    return assertion
