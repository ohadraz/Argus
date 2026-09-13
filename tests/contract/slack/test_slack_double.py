from __future__ import annotations

from typing import Any
from uuid import uuid4

import httpx
import pytest
from agent_communicator.slack import Posted, a_slack_client, post_message
from argus_core.config import get_settings
from argus_testkit import Assertion, Scenario, all_of
from slack_double.server import DEFAULT_BASE_URL

"""Whether the double still answers as the workspace it stands in for.

Every other Slack suite in this repo posts at `slack_double` and believes what
it says back. That belief is what is checked here, and it can only be checked
the one way: make the same call twice, once at the double and once at a real
workspace, and require the two answers to be the same *as the adapter reads
them* - an id where a message landed, a named refusal where it did not.

As the adapter reads them, rather than field by field. A real `ts` and the
double's counter will never be equal and nothing depends on their being equal;
what everything depends on is that a delivered message comes back with an id at
all, and that a refusal comes back named and marked as one no retry will fix.

These post real messages into a real channel, which is why they are behind
their own session (`nox -s contract_slack`) and their own credential.
"""

# Enough to tell a reader of the war room why a message they did not expect is
# there, and enough that two runs never look like one message posted twice.
A_CONTRACT_CHECK = f"Argus contract check - ignore ({uuid4().hex[:8]})"

# A channel id shaped like Slack's own and belonging to nobody. Not a name: a
# name that happens to exist in the workspace somebody runs this in would turn
# the refusal being checked into a delivered message, in their channel.
NO_SUCH_CHANNEL = "C00000000000"

# What Slack calls a channel it cannot find. The one refusal worth checking,
# because it is the one the relay reads as "this line will never be said" - a
# misreading here is an incident that goes quiet rather than one that retries.
CHANNEL_NOT_FOUND = "channel_not_found"

needs_a_real_workspace = pytest.mark.skipif(
    not (get_settings().slack_bot_token and get_settings().slack_war_room_channel),
    reason="no SLACK_BOT_TOKEN or SLACK_WAR_ROOM_CHANNEL: "
           "the real half of the contract cannot be checked"
)


@pytest.mark.contract
@needs_a_real_workspace
def test_a_message_the_workspace_accepts_comes_back_with_an_id() -> None:
    # The whole of the happy path, and what a war room is: the id Slack answers
    # with is the thread every later line of that incident replies into. A
    # double that answered without one would leave every suite believing in
    # conversations that could not exist.
    Scenario() \
        .given(the_war_room := get_settings().slack_war_room_channel) \
        .when(lambda: post_message(
            the_war_room, A_CONTRACT_CHECK, slack=a_slack_client()
        )) \
        .then(all_of(_it_landed(), _it_reads_as(_the_double_asked_the_same_way())))


@pytest.mark.contract
@needs_a_real_workspace
def test_a_channel_the_workspace_cannot_find_is_refused_by_name() -> None:
    # The refusal the relay acts on. Slack answers it as a 200 whose payload
    # says no - not as an error status - so a double that got this shape wrong
    # would have every suite reading a refusal as a delivered message, or a
    # dead channel as something worth retrying for ever.
    Scenario() \
        .given(NO_SUCH_CHANNEL) \
        .when(lambda: post_message(
            NO_SUCH_CHANNEL, A_CONTRACT_CHECK, slack=a_slack_client()
        )) \
        .then(all_of(
            _it_was_refused_for(CHANNEL_NOT_FOUND),
            _it_is_not_worth_another_go(),
            _it_reads_as(_the_double_refusing_the_same_way())
        ))


def _at_the_double() -> Any:
    """A client pointed at the double, built the way the demo builds one."""
    return a_slack_client(base_url=DEFAULT_BASE_URL, token="xoxb-the-double-never-reads-this")


def _the_double_asked_the_same_way() -> Posted:
    """The same call, at the stand-in."""
    return post_message("C-war-room", A_CONTRACT_CHECK, slack=_at_the_double())


def _the_double_refusing_the_same_way() -> Posted:
    """The same call at the stand-in, with the refusal Slack gave queued on it.

    Seeded rather than provoked: the double accepts any channel, so the only
    way to ask it the question the real workspace was asked is to tell it what
    the answer was. That is the comparison - not that the double invents the
    refusal, but that it says it the way the workspace said it.
    """
    httpx.post(
        f"{DEFAULT_BASE_URL}/double-control/seed",
        json={"error": CHANNEL_NOT_FOUND},
        timeout=10.0
    ).raise_for_status()

    return post_message(NO_SUCH_CHANNEL, A_CONTRACT_CHECK, slack=_at_the_double())


def _it_landed() -> Assertion[Posted]:
    def assertion(posted: Posted) -> bool:
        if not posted.ts:
            raise AssertionError(
                f"expected the workspace to answer with an id, it refused: [{posted.refusal}]"
            )

        return True

    return assertion


def _it_was_refused_for(reason: str) -> Assertion[Posted]:
    def assertion(posted: Posted) -> bool:
        if posted.ts is not None:
            raise AssertionError(f"expected a refusal, the message landed as [{posted.ts}]")

        if reason not in posted.refusal:
            raise AssertionError(
                f"expected the refusal to name [{reason}], it said [{posted.refusal}]"
            )

        return True

    return assertion


def _it_is_not_worth_another_go() -> Assertion[Posted]:
    """A channel that is not there is not there on the next pass either.

    The half of the answer the relay acts on: read as worth retrying, this
    refusal would hold an incident's whole account behind a channel that is
    never coming back.
    """
    def assertion(posted: Posted) -> bool:
        if posted.worth_another_go:
            raise AssertionError(
                f"expected [{posted.refusal}] read as final, it was read as worth retrying"
            )

        return True

    return assertion


def _it_reads_as(at_the_double: Posted) -> Assertion[Posted]:
    """The two answers, as the adapter reads them.

    Not field by field: an id from a real workspace and an id from a counter
    are never the same string, and nothing in Argus compares them. What is
    compared is what every caller branches on - whether there is an id at all,
    what the refusal was called, and whether it is worth another go.
    """
    def assertion(from_the_workspace: Posted) -> bool:
        real = (from_the_workspace.ts is not None,
                from_the_workspace.refusal,
                from_the_workspace.worth_another_go)
        stood_in = (at_the_double.ts is not None,
                    at_the_double.refusal,
                    at_the_double.worth_another_go)

        if real != stood_in:
            raise AssertionError(
                f"expected the double to answer as the workspace did {real}, it answered {stood_in}"
            )

        return True

    return assertion
