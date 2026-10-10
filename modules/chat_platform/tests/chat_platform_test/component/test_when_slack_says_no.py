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

from __future__ import annotations

import logging
from typing import Any

import httpx2
import pytest
from argus_core import utc_now
from argus_testkit import (
    Assertion,
    Scenario,
    all_of,
    attempting,
    one_record_was_logged,
)
from chat_platform import Line, Posted
from chat_platform.slack import ChatSettings, Slack
from slack_sdk import WebClient

# By address rather than by name: `localhost` resolves to IPv6 first and waits
# out a refusal on each of the two, which doubles what this costs for nothing.
A_PORT_NOTHING_LISTENS_ON = "http://127.0.0.1:9"

# How long a client aimed at nothing waits before giving up. Shorter than the
# adapter's own, because nothing is ever going to answer and a refused connect
# on some platforms is retried for seconds before the transport says so.
NOT_LONG = 1

DONT_CARE_LINE = Line(who="dont care", text="dont care")


@pytest.mark.component
def test_a_refusal_is_survived_and_nothing_is_delivered(slack: str) -> None:
    some_refusal = "channel_not_found"

    Scenario() \
        .given(
            _slack_will_answer(slack, error=some_refusal),
            a_platform_pointed_at_the_double := _slack_at(slack)
        ) \
        .when(
            attempting(
                lambda: a_platform_pointed_at_the_double.post("C-renamed-yesterday", DONT_CARE_LINE)
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
            a_platform_pointed_at_the_double := _slack_at(slack)
        ) \
        .when(
            attempting(
                lambda: a_platform_pointed_at_the_double.post("C-war-room", DONT_CARE_LINE)
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
    # reach, so the platform here is aimed at nothing on purpose.
    Scenario() \
        .given(
            a_platform_aimed_at_nothing := _slack_at(A_PORT_NOTHING_LISTENS_ON)
        ) \
        .when(
            attempting(
                lambda: a_platform_aimed_at_nothing.post("C-war-room", DONT_CARE_LINE)
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
            a_platform_pointed_at_the_double := _slack_at(slack)
        ) \
        .when(
            lambda: a_platform_pointed_at_the_double.post("C-renamed-yesterday", DONT_CARE_LINE)
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
            a_platform_pointed_at_the_double := _slack_at(slack)
        ) \
        .when(
            lambda: a_platform_pointed_at_the_double.post("C-war-room", DONT_CARE_LINE)
        ) \
        .then(
            _it_is_worth_another_go(True)
        )


@pytest.mark.component
def test_a_workspace_that_cannot_be_reached_is_worth_another_go() -> None:
    # Nothing answered at all, which says nothing about Slack's opinion of the
    # message - only that the network was in the way this second.
    Scenario() \
        .given(
            a_platform_aimed_at_nothing := _slack_at(A_PORT_NOTHING_LISTENS_ON)
        ) \
        .when(
            lambda: a_platform_aimed_at_nothing.post("C-war-room", DONT_CARE_LINE)
        ) \
        .then(
            _it_is_worth_another_go(True)
        )


@pytest.mark.component
def test_a_refusal_is_logged_as_a_warning_naming_the_channel(
    slack: str, caplog: pytest.LogCaptureFixture
) -> None:
    # A renamed channel and a revoked token look the same from inside Argus,
    # so the line names the channel as well as Slack's word for it.
    some_channel = "C-renamed-yesterday"
    some_refusal = "channel_not_found"

    Scenario() \
        .given(
            _slack_will_answer(slack, error=some_refusal),
            a_platform_pointed_at_the_double := _slack_at(slack)
        ) \
        .when(
            lambda: a_platform_pointed_at_the_double.post(some_channel, DONT_CARE_LINE)
        ) \
        .then(
            one_record_was_logged(caplog, "chat_platform.slack_posting", logging.WARNING,
                                  "slack refused the message",
                                  values={"channel": some_channel,
                                          "refusal": some_refusal})
        )


@pytest.mark.component
def test_a_workspace_that_cannot_be_reached_is_logged_as_a_warning(
    caplog: pytest.LogCaptureFixture
) -> None:
    some_channel = "C-war-room"

    Scenario() \
        .given(
            a_platform_aimed_at_nothing := _slack_at(A_PORT_NOTHING_LISTENS_ON)
        ) \
        .when(
            lambda: a_platform_aimed_at_nothing.post(some_channel, DONT_CARE_LINE)
        ) \
        .then(
            one_record_was_logged(caplog, "chat_platform.slack_posting", logging.WARNING,
                                  "slack could not be reached",
                                  values={"channel": some_channel}, failure=OSError)
        )


def _slack_at(base_url: str) -> Slack:
    """The adapter, aimed at `base_url`, giving up after `NOT_LONG`.

    The client factory is the adapter's own seam, and the timeout is the one
    thing overridden through it: the request path stays the SDK's.
    """
    def a_client_that_gives_up_soon(**given: Any) -> WebClient:
        return WebClient(**{**given, "timeout": NOT_LONG})

    return Slack(
        ChatSettings(slack_bot_token="xoxb-dont-care",
                     slack_base_url=base_url,
                     slack_signing_secret=""),
        client_of=a_client_that_gives_up_soon,
        clock=utc_now
    )


def _slack_will_answer(base_url: str, error: str, retry_after: int | None = None) -> str:
    """Queues the refusal the next post is met with."""
    seeded: dict[str, Any] = {"error": error}
    if retry_after is not None:
        seeded["retry_after"] = retry_after

    httpx2.post(f"{base_url}/double-control/seed", json=seeded).raise_for_status()

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
                f"Expected the failure to be survived, got [{type(raised).__name__}]: {raised}"
            )

        return True

    return assertion


def _slack_holds_nothing(base_url: str) -> Assertion[Any]:
    def assertion(_result: Any) -> bool:
        held = httpx2.get(f"{base_url}/double-control/posted").json()["posted"]
        if held:
            raise AssertionError(f"Expected nothing delivered, got {held}")

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
                f"Expected the refusal to name [{reason}], got [{answered.refusal}]."
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
                f"Expected worth_another_go={expected}, got {answered.worth_another_go}"
            )

        return True

    return assertion
