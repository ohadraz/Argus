"""The chat platform's ports, as every adapter of them answers.

What the ports promise, asked of each adapter over one seed: the Slack adapter
against `slack_double`, served on loopback for this suite by the conftest and
emptied after each case, and the in-memory double (`chat_platform_double`). A
promise one keeps and the other does not fails here, so the double cannot drift
from the ports, and the ports name nothing only Slack's wire could answer.

The promises and nothing beyond them. Slack's markup, blocks and buttons, its
error names and `Retry-After`, the SDK's address and timeout, which of Slack's
events are irrelevant, real names before display names, header casing and what
is logged are the wire suites' (`test_slack.py`, `test_slack_deliveries.py`,
`test_slack_posting.py`).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

import httpx2
import pytest
from argus_testkit import Assertion, Scenario, an_error_was_raised, attempting, the_answer_was
from chat_platform import (
    ChatDeliveryUnreadable,
    ChatDeliveryUnverified,
    ChatPlatformReads,
    ChatPlatformWrites,
    Delivery,
    Handshake,
    Irrelevant,
    Line,
    Offer,
    Posted,
    Pressed,
    Written,
)
from chat_platform.slack import Slack, SlackSettings
from chat_platform_double import (
    ChatState,
    InMemoryChat,
    Person,
    Refusal,
    a_delivery_of,
    headers_signing,
)
from core.models import a_chat_message, a_chat_thread
from slack_sdk import WebClient

from chat_platform_test.framework.slack_deliveries import as_slack_sends, slack_signed

THE_SECRET = "the-signing-secret"
SOME_OTHER_SECRET = "some-other-secret"
NO_SECRET = ""
NOW = datetime(2026, 11, 28, 9, 30, tzinfo=UTC)
LONGER_THAN_A_DELIVERY_IS_BELIEVED = timedelta(minutes=6)

SOME_CHANNEL = "C0SOMECHANNEL"
SOME_THREAD = "1789000001.000001"
SOME_REPLY = "1789000002.000002"
SOME_PERSON = "U0SOMEPERSON"
SOME_NAME = "Some Person"
SOMEBODY_NAMELESS = "U0NAMELESS"
SOMEBODY_NOT_HELD = "U0NOBODY"
SOME_LINE = Line(who="some-agent", text="some line")
SOME_OTHER_LINE = Line(who="some-agent", text="some other line")

# Where nothing listens, by address rather than by name, for the platform
# nothing reaches; and how long a client aimed there waits before it gives up.
A_PORT_NOTHING_LISTENS_ON = "http://127.0.0.1:9"
NOT_LONG = 1


class _BothPorts(ChatPlatformReads, ChatPlatformWrites, Protocol):
    """What every adapter here answers: both ports, as one object."""


@dataclass(frozen=True)
class _Platform:
    """One row: an adapter answering both ports, how a delivery is written and
    signed as its platform sends it, and how any bytes are signed as it signs
    them - under a secret, at a moment."""

    answers: _BothPorts
    sends: Callable[..., tuple[bytes, dict[str, str]]]
    signs: Callable[[bytes, str, datetime], dict[str, str]]


class _StandsUp(Protocol):
    def __call__(self,
                 state: ChatState,
                 slack: str,
                 *,
                 secret: str = ...,
                 unreachable: bool = ...) -> _Platform:
        ...


def _in_memory(state: ChatState,
               slack: str,
               *,
               secret: str = THE_SECRET,
               unreachable: bool = False) -> _Platform:
    return _Platform(InMemoryChat(state, secret=secret, clock=lambda: NOW,
                                  unreachable=unreachable),
                     a_delivery_of,
                     headers_signing)


def _slack(state: ChatState,
           slack: str,
           *,
           secret: str = THE_SECRET,
           unreachable: bool = False) -> _Platform:
    """Slack over the double, with the seed's people and refusals staged on it
    through its control seam - and the seed's name being Slack's own, which
    the adapter gives and nobody stages."""
    for person in state.people:
        httpx2.post(f"{slack}/double-control/user",
                    json={"id": person.id, "real_name": person.name}).raise_for_status()

    for refusal in state.refusals:
        httpx2.post(f"{slack}/double-control/seed",
                    json={"error": "rate_limited" if refusal.worth_another_go
                          else refusal.why}).raise_for_status()

    def a_client_that_gives_up_soon(**given: Any) -> WebClient:
        return WebClient(**{**given, "timeout": NOT_LONG})

    return _Platform(
        Slack(SlackSettings(slack_bot_token="xoxb-dont-care",
                            slack_base_url=A_PORT_NOTHING_LISTENS_ON if unreachable else slack,
                            slack_signing_secret=secret),
              client_of=a_client_that_gives_up_soon,
              clock=lambda: NOW),
        as_slack_sends,
        lambda body, signed_with, at: slack_signed(body, secret=signed_with, at=at)
    )


EVERY_ADAPTER = pytest.mark.parametrize("stand_up", [
    pytest.param(_in_memory, id="in-memory"),
    pytest.param(_slack, id="slack")
])

# The seed's name, as each row's platform gives it: the double is told it,
# and Slack is Slack.
THE_NAME = "Slack"


def _a_platform() -> ChatState:
    return ChatState(name=THE_NAME)


def _what_each_delivery_says() -> list[Any]:
    """Every kind of delivery a platform reads, in Argus's own terms, filed
    under the platform's name."""
    thread = a_chat_thread(THE_NAME, SOME_CHANNEL, SOME_THREAD)
    message = a_chat_message(THE_NAME, SOME_CHANNEL, SOME_REPLY)

    return [
        pytest.param(Written(thread=thread, message=message, person_id=SOME_PERSON,
                             text="some words"), id="a-person-writing-in-a-thread"),
        pytest.param(Pressed(thread=thread, person_id=SOME_PERSON, message=message),
                     id="a-person-pressing-an-offer"),
        pytest.param(Handshake(challenge="some-challenge"), id="the-platform-checking-the-address")
    ]


@pytest.mark.component
@EVERY_ADAPTER
def test_the_platform_is_named_as_its_references_are_filed(stand_up: _StandsUp,
                                                           slack: str) -> None:
    # What every delivery below is expected to file its references under, so a
    # name that said anything else would leave those references orphaned.
    Scenario() \
        .given(platform := stand_up(_a_platform(), slack)) \
        .when(lambda: platform.answers.name) \
        .then(the_answer_was(THE_NAME))


@pytest.mark.component
@EVERY_ADAPTER
@pytest.mark.parametrize("said", _what_each_delivery_says())
def test_a_delivery_signed_just_now_is_what_it_says(stand_up: _StandsUp,
                                                    slack: str,
                                                    said: Delivery) -> None:
    Scenario() \
        .given(platform := stand_up(_a_platform(), slack),
               delivery := platform.sends(said, signed_with=THE_SECRET, at=NOW)) \
        .when(lambda: platform.answers.parse_delivery(*delivery)) \
        .then(the_answer_was(said))


@pytest.mark.component
@EVERY_ADAPTER
def test_a_delivery_of_something_argus_does_not_act_on_is_irrelevant(stand_up: _StandsUp,
                                                                     slack: str) -> None:
    # Which things those are is each platform's own; that they are read as
    # nothing to act on is the ports'.
    Scenario() \
        .given(platform := stand_up(_a_platform(), slack),
               delivery := platform.sends(Irrelevant(why="dont-care"), signed_with=THE_SECRET,
                                          at=NOW)) \
        .when(lambda: platform.answers.parse_delivery(*delivery)) \
        .then(_it_is_irrelevant())


@pytest.mark.component
@EVERY_ADAPTER
@pytest.mark.parametrize(("signed_with", "at", "altered"), [
    pytest.param(SOME_OTHER_SECRET, NOW, False, id="signed-with-another-secret"),
    pytest.param(THE_SECRET, NOW, True, id="altered-after-it-was-signed"),
    pytest.param(THE_SECRET, NOW - LONGER_THAN_A_DELIVERY_IS_BELIEVED, False,
                 id="signed-too-long-ago"),
    pytest.param(THE_SECRET, NOW + LONGER_THAN_A_DELIVERY_IS_BELIEVED, False,
                 id="signed-too-far-ahead")
])
def test_a_delivery_the_platform_did_not_sign_just_now_as_it_arrived_is_unverified(
    stand_up: _StandsUp, slack: str, signed_with: str, at: datetime, altered: bool
) -> None:
    # What a forged or replayed "this person pressed resolve" looks like.
    # Believed, it would end an incident nobody ended.
    Scenario() \
        .given(platform := stand_up(_a_platform(), slack),
               delivery := platform.sends(Handshake(challenge="dont-care"),
                                          signed_with=signed_with, at=at)) \
        .when(attempting(lambda: platform.answers.parse_delivery(
            delivery[0] + b" " if altered else delivery[0], delivery[1]
        ))) \
        .then(an_error_was_raised(ChatDeliveryUnverified))


@pytest.mark.component
@EVERY_ADAPTER
def test_a_delivery_carrying_no_signature_is_unverified(stand_up: _StandsUp, slack: str) -> None:
    Scenario() \
        .given(platform := stand_up(_a_platform(), slack),
               delivery := platform.sends(Handshake(challenge="dont-care"),
                                          signed_with=THE_SECRET, at=NOW)) \
        .when(attempting(lambda: platform.answers.parse_delivery(delivery[0], {}))) \
        .then(an_error_was_raised(ChatDeliveryUnverified))


@pytest.mark.component
@EVERY_ADAPTER
def test_a_platform_holding_no_secret_refuses_even_a_delivery_signed_with_none(
    stand_up: _StandsUp, slack: str
) -> None:
    # A signature under an empty key is one anybody can make, so a deployment
    # that set no secret trusts nothing rather than everything.
    Scenario() \
        .given(platform := stand_up(_a_platform(), slack, secret=NO_SECRET),
               delivery := platform.sends(Handshake(challenge="dont-care"),
                                          signed_with=NO_SECRET, at=NOW)) \
        .when(attempting(lambda: platform.answers.parse_delivery(*delivery))) \
        .then(an_error_was_raised(ChatDeliveryUnverified))


@pytest.mark.component
@EVERY_ADAPTER
@pytest.mark.parametrize("body", [
    # A lead byte with no continuation: no UTF-8, and no byte-order mark that
    # would have it read as another encoding.
    pytest.param(b"\xc3\x28", id="not-text"),
    pytest.param(b"not json", id="not-json"),
    pytest.param(b'["some", "list"]', id="a-list"),
    pytest.param(b'"some string"', id="a-string")
])
def test_a_delivery_signed_just_now_in_none_of_the_platforms_shapes_is_unreadable(
    stand_up: _StandsUp, slack: str, body: bytes
) -> None:
    # Apart from unverified: that one is about who sent it, this one about what
    # they sent - and a reader of it is told which, rather than failing.
    Scenario() \
        .given(platform := stand_up(_a_platform(), slack),
               headers := platform.signs(body, THE_SECRET, NOW)) \
        .when(attempting(lambda: platform.answers.parse_delivery(body, headers))) \
        .then(an_error_was_raised(ChatDeliveryUnreadable))


@pytest.mark.component
@EVERY_ADAPTER
@pytest.mark.parametrize(("person_id", "named"), [
    pytest.param(SOME_PERSON, SOME_NAME, id="held-and-named"),
    pytest.param(SOMEBODY_NAMELESS, None, id="held-with-no-name"),
    pytest.param(SOMEBODY_NOT_HELD, None, id="not-held")
])
def test_a_person_is_named_as_the_platform_names_them(stand_up: _StandsUp,
                                                      slack: str,
                                                      person_id: str,
                                                      named: str | None) -> None:
    Scenario() \
        .given(platform := stand_up(ChatState(name=THE_NAME, people=(
            Person(id=SOME_PERSON, name=SOME_NAME),
            Person(id=SOMEBODY_NAMELESS, name=None)
        )), slack)) \
        .when(lambda: platform.answers.person_named(person_id)) \
        .then(the_answer_was(named))


@pytest.mark.component
@EVERY_ADAPTER
def test_nobody_is_named_by_a_platform_nothing_reaches(stand_up: _StandsUp, slack: str) -> None:
    # `None` rather than a failure: a workspace that cannot say who somebody is
    # must not cost them an offer to confirm.
    Scenario() \
        .given(platform := stand_up(
            ChatState(name=THE_NAME, people=(Person(id=SOME_PERSON, name=SOME_NAME),)),
            slack, unreachable=True
        )) \
        .when(lambda: platform.answers.person_named(SOME_PERSON)) \
        .then(the_answer_was(None))


@pytest.mark.component
@EVERY_ADAPTER
@pytest.mark.parametrize(("thread", "offer"), [
    pytest.param(None, None, id="to-the-channel"),
    pytest.param(SOME_THREAD, None, id="a-reply-in-a-thread"),
    pytest.param(SOME_THREAD,
                 Offer(about=a_chat_message(THE_NAME, SOME_CHANNEL, SOME_REPLY),
                       label="some label"),
                 id="carrying-an-offer")
])
def test_a_post_lands_and_is_answered_with_its_message(stand_up: _StandsUp,
                                                       slack: str,
                                                       thread: str | None,
                                                       offer: Offer | None) -> None:
    Scenario() \
        .given(platform := stand_up(_a_platform(), slack)) \
        .when(lambda: platform.answers.post(SOME_CHANNEL, SOME_LINE, thread, offer)) \
        .then(_it_landed())


@pytest.mark.component
@EVERY_ADAPTER
def test_a_rewrite_of_a_message_posted_earlier_lands_as_that_message(stand_up: _StandsUp,
                                                                     slack: str) -> None:
    Scenario() \
        .given(platform := stand_up(_a_platform(), slack),
               message := _the_message_of(platform.answers.post(SOME_CHANNEL, SOME_LINE))) \
        .when(lambda: platform.answers.rewrite(SOME_CHANNEL, message, SOME_OTHER_LINE)) \
        .then(the_answer_was(Posted(message=message)))


@pytest.mark.component
@EVERY_ADAPTER
def test_a_rewrite_of_a_message_never_posted_is_refused_and_not_worth_another_go(
    stand_up: _StandsUp, slack: str
) -> None:
    Scenario() \
        .given(platform := stand_up(_a_platform(), slack)) \
        .when(lambda: platform.answers.rewrite(SOME_CHANNEL, SOME_REPLY, SOME_LINE)) \
        .then(_it_did_not_land(worth_another_go=False))


@pytest.mark.component
@EVERY_ADAPTER
@pytest.mark.parametrize("refusal", [
    pytest.param(Refusal(why="some_throttle", worth_another_go=True), id="a-throttle"),
    pytest.param(Refusal(why="channel_not_found", worth_another_go=False), id="a-refusal")
])
def test_a_refused_post_lands_nothing_and_says_whether_to_try_again(stand_up: _StandsUp,
                                                                   slack: str,
                                                                   refusal: Refusal) -> None:
    # Answered, never raised: communication is how an incident is reported,
    # not how it is resolved.
    Scenario() \
        .given(platform := stand_up(ChatState(name=THE_NAME, refusals=(refusal,)), slack)) \
        .when(lambda: platform.answers.post(SOME_CHANNEL, SOME_LINE)) \
        .then(_it_did_not_land(worth_another_go=refusal.worth_another_go))


# Each write, asked of a platform: a post to the channel, and a rewrite of a
# message - which, where nothing is reached, needs no message posted before it.
EVERY_WRITE = pytest.mark.parametrize("write", [
    pytest.param(lambda answers: answers.post(SOME_CHANNEL, SOME_LINE), id="a-post"),
    pytest.param(lambda answers: answers.rewrite(SOME_CHANNEL, SOME_REPLY, SOME_LINE),
                 id="a-rewrite")
])


@pytest.mark.component
@EVERY_ADAPTER
@EVERY_WRITE
def test_a_write_to_a_platform_nothing_reaches_lands_nothing_and_is_worth_another_go(
    stand_up: _StandsUp, slack: str, write: Callable[[_BothPorts], Posted]
) -> None:
    # An unreachable platform says nothing about the message, so the same write
    # later could land.
    Scenario() \
        .given(platform := stand_up(_a_platform(), slack, unreachable=True)) \
        .when(lambda: write(platform.answers)) \
        .then(_it_did_not_land(worth_another_go=True))


def _the_message_of(posted: Posted) -> str:
    """The message a post landed, for a case that goes on to use it - which
    cannot, where the post landed none."""
    if posted.message is None:
        raise AssertionError(f"Expected the post to land a message, got {posted}.")

    return posted.message


def _it_landed() -> Assertion[Posted]:
    def assertion(posted: Posted) -> bool:
        if not posted.message or posted.refusal or posted.worth_another_go:
            raise AssertionError(f"Expected the write to land with its message, got {posted}.")

        return True

    return assertion


def _it_did_not_land(*, worth_another_go: bool) -> Assertion[Posted]:
    def assertion(posted: Posted) -> bool:
        if posted.message is not None or not posted.refusal \
                or posted.worth_another_go is not worth_another_go:
            raise AssertionError(
                f"Expected no message, a refusal, and worth another go "
                f"[{worth_another_go}]; got {posted}."
            )

        return True

    return assertion


def _it_is_irrelevant() -> Assertion[Delivery]:
    def assertion(parsed: Delivery) -> bool:
        if not isinstance(parsed, Irrelevant):
            raise AssertionError(f"Expected the delivery to be irrelevant, got {parsed!r}.")

        return True

    return assertion
