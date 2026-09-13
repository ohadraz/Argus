from __future__ import annotations

from typing import Any

import httpx
import pytest
from agent_communicator.slack import Posted, a_slack_client, post_message
from argus_testkit import Assertion, Scenario, all_of, attempting

"""Every way Slack declines to carry a message, and what Argus does about it.

Nothing. That is the claim these make: a refusal, a throttle and a workspace
that cannot be reached all come back as "no message" and none of them escapes
the adapter. Communication is how an incident is reported, not how it is
resolved, and an incident that escalated because Slack rate-limited it would be
a worse outcome than one nobody saw.

Which refusal it is does not matter to the caller, which is why they are not
told apart here - only that each is survived and that nothing was delivered. A
call that answered an id after failing would be worse than one that raised: the
war room would hold a thread reference naming a message that does not exist.
"""

# By address rather than by name: `localhost` resolves to IPv6 first and waits
# out a refusal on each of the two, which doubles what this costs for nothing.
A_PORT_NOTHING_LISTENS_ON = "http://127.0.0.1:9"


@pytest.mark.component
def test_a_refusal_is_survived_and_nothing_is_delivered(slack: str) -> None:
    some_refusal = "channel_not_found"

    Scenario() \
        .given(
            _slack_will_answer(slack, error=some_refusal),
            a_client_pointed_at_the_double := a_slack_client(base_url=slack)
        ) \
        .when(
            attempting(
                lambda: post_message(
                    "C-renamed-yesterday", "dont care", slack=a_client_pointed_at_the_double
                )
            )
        ) \
        .then(
            all_of(_nothing_was_raised(), _slack_holds_nothing(slack))
        )


@pytest.mark.component
def test_a_throttled_call_is_survived_rather_than_retried(slack: str) -> None:
    # The one refusal Slack answers with a status rather than a payload, and
    # the one a caller might be tempted to retry. It is not retried: updates
    # are already sparse, and a walk that paused to wait out a rate limit would
    # be a walk slowed down by its own commentary.
    some_wait = 30

    Scenario() \
        .given(
            _slack_will_answer(slack, error="rate_limited", retry_after=some_wait),
            a_client_pointed_at_the_double := a_slack_client(base_url=slack)
        ) \
        .when(
            attempting(
                lambda: post_message(
                    "C-war-room", "dont care", slack=a_client_pointed_at_the_double
                )
            )
        ) \
        .then(
            all_of(_nothing_was_raised(), _slack_holds_nothing(slack))
        )


@pytest.mark.component
def test_a_workspace_that_cannot_be_reached_is_survived(slack: str) -> None:
    # Not a refusal at all: nothing answered. It arrives as the transport's own
    # error rather than Slack's, which is a different exception and the same
    # outcome - and the case a suite pointed at a healthy double would never
    # reach, so the client here is aimed at nothing on purpose.
    Scenario() \
        .given(
            a_client_aimed_at_nothing := a_slack_client(
                base_url=A_PORT_NOTHING_LISTENS_ON, timeout=1
            )
        ) \
        .when(
            attempting(
                lambda: post_message("C-war-room", "dont care", slack=a_client_aimed_at_nothing)
            )
        ) \
        .then(
            all_of(_nothing_was_raised(), _slack_holds_nothing(slack))
        )


@pytest.mark.component
def test_a_refusal_is_not_worth_another_go(slack: str) -> None:
    # Nothing about the next pass makes a renamed channel the right one, so a
    # relay that held its place for this would keep the incident's whole
    # account waiting on a channel that is not coming back.
    some_refusal = "channel_not_found"

    Scenario() \
        .given(
            _slack_will_answer(slack, error=some_refusal),
            a_client_pointed_at_the_double := a_slack_client(base_url=slack)
        ) \
        .when(
            lambda: post_message(
                "C-renamed-yesterday", "dont care", slack=a_client_pointed_at_the_double
            )
        ) \
        .then(
            all_of(_it_was_refused_for(some_refusal), _it_is_worth_another_go(False))
        )


@pytest.mark.component
def test_a_throttle_is_worth_another_go(slack: str) -> None:
    # The one refusal that says only "not now". The next pass is the retry, so
    # the line keeps its place and nothing is lost.
    dont_care_wait = 30

    Scenario() \
        .given(
            _slack_will_answer(slack, error="rate_limited", retry_after=dont_care_wait),
            a_client_pointed_at_the_double := a_slack_client(base_url=slack)
        ) \
        .when(
            lambda: post_message(
                "C-war-room", "dont care", slack=a_client_pointed_at_the_double
            )
        ) \
        .then(
            _it_is_worth_another_go(True)
        )


@pytest.mark.component
def test_a_workspace_that_cannot_be_reached_is_worth_another_go(slack: str) -> None:
    # Nothing answered at all, which says nothing about Slack's opinion of the
    # message - only that the network was in the way this second.
    Scenario() \
        .given(
            a_client_aimed_at_nothing := a_slack_client(
                base_url=A_PORT_NOTHING_LISTENS_ON, timeout=1
            )
        ) \
        .when(
            lambda: post_message(
                "C-war-room", "dont care", slack=a_client_aimed_at_nothing
            )
        ) \
        .then(
            _it_is_worth_another_go(True)
        )


def _slack_will_answer(base_url: str, error: str, retry_after: int | None = None) -> str:
    """Queues the refusal the next post is met with."""
    seeded: dict[str, Any] = {"error": error}
    if retry_after is not None:
        seeded["retry_after"] = retry_after

    httpx.post(f"{base_url}/double-control/seed", json=seeded).raise_for_status()

    return error


def _nothing_was_raised() -> Assertion[Exception | None]:
    """The whole point: the adapter answers rather than throwing.

    `None` from `attempting` means the call returned. What it returned is the
    other assertion's business - this one is only that the walk above it was
    never interrupted.
    """
    def assertion(raised: Exception | None) -> bool:
        if raised is not None:
            raise AssertionError(
                f"expected the failure to be survived, got [{type(raised).__name__}]: {raised}"
            )

        return True

    return assertion


def _slack_holds_nothing(base_url: str) -> Assertion[Any]:
    def assertion(_result: Any) -> bool:
        held = httpx.get(f"{base_url}/double-control/posted").json()["posted"]
        if held:
            raise AssertionError(f"expected nothing delivered, got {held}")

        return True

    return assertion




def _it_was_refused_for(reason: str) -> Assertion[Posted]:
    """Slack's own word for the refusal, carried back rather than swallowed.

    The reason is what reaches the incident's timeline, so a channel that was
    renamed and a token that was revoked read differently there - and a reader
    who can tell which it was is one who can fix it.
    """
    def assertion(answered: Posted) -> bool:
        if reason not in answered.refusal:
            raise AssertionError(
                f"expected the refusal to name [{reason}], got [{answered.refusal}]"
            )

        return True

    return assertion


def _it_is_worth_another_go(expected: bool) -> Assertion[Posted]:
    """Whether the relay should hold its place and try this line again.

    The decision this answer exists to carry. A throttle passes, and the line
    waits where it is; a refusal does not, and holding the place for one would
    keep Argus silent about everything behind it for good.
    """
    def assertion(answered: Posted) -> bool:
        if answered.worth_another_go != expected:
            raise AssertionError(
                f"expected worth_another_go={expected}, got {answered.worth_another_go}"
            )

        return True

    return assertion
