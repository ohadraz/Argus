"""Slack as the chat platform: built only where a deployment has a workspace,
reading deliveries under its secret at the moment its clock says, and naming
the people who write.

Naming is this module's one call to Slack, and the one place the port promises
never to raise: the name is read when Argus offers a person the chance to
confirm a resolution, and a workspace that cannot say who someone is must not
cost them the offer.

What is injected is the client factory and the clock, so the SDK's request path
stays real and only its answers are written. Whether that path reaches Slack
correctly is the Slack contract suite's to prove.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from unittest.mock import Mock

import pytest
from argus_core.models import ReportChannel
from argus_testkit import (
    Assertion,
    Kept,
    Scenario,
    a_factory_that_must_not_be_called,
    all_of,
    nothing_was_collected,
    one_record_was_logged,
)
from chat_platform.platform import Handshake
from chat_platform.slack import (
    DISPLAY_NAME,
    PROFILE,
    REAL_NAME,
    USER,
    ChatSettings,
    Slack,
    slack_from,
)
from chat_platform.slack_deliveries import (
    CHALLENGE,
    SIGNATURE_HEADER,
    SIGNATURE_VERSION,
    TIMESTAMP_HEADER,
    TYPE,
    URL_VERIFICATION,
)
from slack_sdk.errors import SlackApiError

SOME_PERSON = "U-some-person"
SOME_MOMENT = datetime(2026, 10, 10, 3, 30, tzinfo=UTC)


@pytest.mark.unit
def test_without_a_bot_token_there_is_no_platform() -> None:
    # Slack is optional. A deployment holding no token has no chat platform at
    # all - which is how "nothing to hear" reaches the web endpoints - and
    # builds no client on the way to saying so.
    a_client_was_asked_for: Kept[bool] = Kept()

    Scenario() \
        .when(lambda: slack_from(_settings_with(bot_token=""),
                                 client_of=a_factory_that_must_not_be_called(
                                     a_client_was_asked_for))) \
        .then(all_of(_it_answers(None), nothing_was_collected(a_client_was_asked_for)))


@pytest.mark.unit
def test_a_report_through_slack_reached_argus_through_slack() -> None:
    Scenario() \
        .when(lambda: slack_from(_settings_with(bot_token="dont care"))) \
        .then(_its_channel_is(ReportChannel.SLACK))


@pytest.mark.unit
def test_the_platform_reads_a_delivery_under_its_secret_at_the_moment_its_clock_says() -> None:
    # A delivery is believed only within five minutes of its signing, so which
    # clock the platform reads "now" off is part of what it is built with.
    some_secret = "some-signing-secret"
    some_challenge = "some-challenge"
    some_delivery = json.dumps({TYPE: URL_VERIFICATION, CHALLENGE: some_challenge}).encode()

    Scenario() \
        .given(platform := _a_platform(signing_secret=some_secret,
                                       clock=lambda: SOME_MOMENT)) \
        .when(lambda: platform.parse_delivery(some_delivery,
                                             _signed_by(some_secret, SOME_MOMENT, some_delivery))) \
        .then(_it_answers(Handshake(challenge=some_challenge)))


@pytest.mark.unit
def test_a_person_is_named_by_their_real_name() -> None:
    # The name somebody would recognise them by in a postmortem. A display name
    # is what they chose to be called in the channel, and is the second choice.
    Scenario() \
        .given(platform := _a_platform(client_of=_a_workspace_answering(
            {USER: {REAL_NAME: "Some Person", PROFILE: {DISPLAY_NAME: "some.person"}}}
        ))) \
        .when(lambda: platform.person_named(SOME_PERSON)) \
        .then(_it_answers("Some Person"))


@pytest.mark.unit
def test_a_person_with_no_real_name_is_named_by_their_display_name() -> None:
    # Slack says a field nobody supplied may be absent, null or empty - so all
    # three are the same answer.
    Scenario() \
        .given(platform := _a_platform(client_of=_a_workspace_answering(
            {USER: {REAL_NAME: "", PROFILE: {DISPLAY_NAME: "some.person"}}}
        ))) \
        .when(lambda: platform.person_named(SOME_PERSON)) \
        .then(_it_answers("some.person"))


@pytest.mark.unit
def test_a_person_slack_does_not_know_is_not_named() -> None:
    # The offer still stands, made to whoever wrote it. A refusal raised here
    # would cost the person the offer for a name.
    Scenario() \
        .given(platform := _a_platform(client_of=_a_workspace_refusing("user_not_found"))) \
        .when(lambda: platform.person_named(SOME_PERSON)) \
        .then(_it_answers(None))


@pytest.mark.unit
def test_a_workspace_that_cannot_be_reached_names_nobody_and_says_so(
        caplog: pytest.LogCaptureFixture) -> None:
    # Nothing is raised, so the log is the one place an operator learns that
    # every offer this hour went out unnamed because Slack was down - with who
    # it was about, and what failed.
    Scenario() \
        .given(platform := _a_platform(client_of=_a_workspace_unreachable())) \
        .when(lambda: platform.person_named(SOME_PERSON)) \
        .then(all_of(_it_answers(None),
                     one_record_was_logged(caplog, "chat_platform.slack", logging.WARNING,
                                           "person unnamed",
                                           values={"person_id": SOME_PERSON},
                                           failure=OSError)))


def _a_platform(signing_secret: str = "dont care",
                clock: Any = lambda: SOME_MOMENT,
                client_of: Any = None) -> Slack:
    dont_care_workspace = _a_workspace_answering({USER: {}})
    platform = slack_from(_settings_with(bot_token="dont care", signing_secret=signing_secret),
                          client_of=client_of or dont_care_workspace,
                          clock=clock)

    if platform is None:
        raise AssertionError("Expected a platform to be built for a deployment holding a token.")

    return platform


def _settings_with(bot_token: str, signing_secret: str = "dont care") -> ChatSettings:
    """The slice this adapter runs under. The client is injected, so no address
    is ever dialled."""
    dont_care_base_url = ""

    return ChatSettings(slack_bot_token=bot_token,
                        slack_base_url=dont_care_base_url,
                        slack_signing_secret=signing_secret)


def _signed_by(secret: str, at: datetime, body: bytes) -> dict[str, str]:
    timestamp = str(int(at.timestamp()))
    signed = f"{SIGNATURE_VERSION}:{timestamp}:".encode() + body
    digest = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()

    return {SIGNATURE_HEADER: f"{SIGNATURE_VERSION}={digest}", TIMESTAMP_HEADER: timestamp}


def _a_workspace_answering(user: Mapping[str, Any]) -> Any:
    client = Mock(users_info=Mock(return_value=user))

    return lambda *dont_care_args, **dont_care_kwargs: client


def _a_workspace_refusing(error: str) -> Any:
    """Slack's own refusal, as the SDK raises it for a response that is not ok."""
    client = Mock(users_info=Mock(side_effect=_Refused(error)))

    return lambda *dont_care_args, **dont_care_kwargs: client


class _Refused(SlackApiError):
    """The vendor's own error, raised without its untyped constructor.

    The SDK's `SlackApiError.__init__` carries no annotations, so calling it
    from typed code is a mypy error rather than a style question. Subclassing
    and setting what the base sets keeps this a real Slack error - which is what
    the adapter catches - without the untyped call.
    """

    def __init__(self, error: str) -> None:
        self.response = {"ok": False, "error": error}
        Exception.__init__(self, error)


def _a_workspace_unreachable() -> Any:
    client = Mock(users_info=Mock(side_effect=OSError("connection refused")))

    return lambda *dont_care_args, **dont_care_kwargs: client


def _it_answers(expected: object) -> Assertion[object]:
    def assertion(answer: object) -> bool:
        if answer != expected:
            raise AssertionError(f"Expected [{expected!r}], got [{answer!r}].")

        return True

    return assertion


def _its_channel_is(expected: ReportChannel) -> Assertion[Slack | None]:
    def assertion(platform: Slack | None) -> bool:
        if platform is None:
            raise AssertionError("Expected a platform for a deployment holding a token, got none.")

        if platform.channel is not expected:
            raise AssertionError(
                f"Expected reports through it to have come through [{expected}], "
                f"got [{platform.channel}]."
            )

        return True

    return assertion
