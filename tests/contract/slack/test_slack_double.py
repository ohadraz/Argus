"""Whether the double still answers as the workspace it stands in for.

Every other Slack suite in this repo posts at `slack_double` and believes what
it says back. That belief is what is checked here, and it can only be checked
the one way: make the same call twice, once at the double and once at a real
workspace, and require the two answers to be the same *as the adapter reads
them* - an id where a message landed, a named refusal where it did not, a name
where a person was found.

As the adapter reads them, rather than field by field. A real `ts` and the
double's counter will never be equal and nothing depends on their being equal;
what everything depends on is that a delivered message comes back with an id at
all, and that a refusal comes back named and marked as one no retry will fix.

These post real messages into a real channel, which is why they are behind
the free contract session (`nox -s contract`) and their own credential. Naming a
person needs the bot's `users:read` scope; a workspace without it fails that
case with `missing_scope`, which is the scope Argus needs and does not have.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import httpx2
import pytest
from argus_core import get_settings
from argus_core.models import ReportChannel, a_chat_message
from argus_testkit import Assertion, Scenario, all_of
from chat_platform import Line, Offer, Posted
from chat_platform.slack import ChatSettings, Slack
from slack_double.server import DEFAULT_BASE_URL
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

# Enough to tell a reader of the war room why a message they did not expect is
# there, and enough that two runs never look like one message posted twice.
A_CONTRACT_CHECK = f"Argus contract check - ignore ({uuid4().hex[:8]})"

# What the check says once it has been rewritten, as an offer is when the
# incident it asked about is over.
A_CONTRACT_CHECK_REWRITTEN = f"{A_CONTRACT_CHECK} - rewritten"

# A channel id shaped like Slack's own and belonging to nobody. Not a name: a
# name that happens to exist in the workspace somebody runs this in would turn
# the refusal being checked into a delivered message, in their channel.
NO_SUCH_CHANNEL = "C00000000000"

# A message id shaped like Slack's own that no channel ever held - the offer a
# person deleted, as the relay meets it when the incident ends.
NO_SUCH_MESSAGE = "1000000000.000001"

# A user id shaped like Slack's own and belonging to nobody, for the reason the
# channel above is not a name.
NO_SUCH_PERSON = "U00000000000"

# Somebody the double is told about, standing where a real member of the
# workspace stands in the real half.
SOME_PERSON = "U-some-person"

# What Slack calls a channel it cannot find. The one refusal worth checking,
# because it is the one the relay reads as "this line will never be said" - a
# misreading here is an incident that goes quiet rather than one that retries.
CHANNEL_NOT_FOUND = "channel_not_found"

# What Slack calls a message it does not hold, and a person it does not know.
MESSAGE_NOT_FOUND = "message_not_found"
USER_NOT_FOUND = "user_not_found"

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
        .when(lambda: _at_the_workspace().post(the_war_room, _said(A_CONTRACT_CHECK))) \
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
        .when(lambda: _at_the_workspace().post(NO_SUCH_CHANNEL, _said(A_CONTRACT_CHECK))) \
        .then(all_of(
            _it_was_refused_for(CHANNEL_NOT_FOUND),
            _it_is_not_worth_another_go(),
            _it_reads_as(_the_double_refusing_the_same_way())
        ))


@pytest.mark.contract
@needs_a_real_workspace
def test_an_offer_and_its_button_are_accepted_by_the_workspace() -> None:
    # The double keeps whatever blocks it is handed and has no opinion about
    # Block Kit; the workspace has one, and answers a block it cannot draw with
    # `invalid_blocks`. Every suite reading a button back off the double is
    # trusting that the workspace would have drawn it.
    Scenario() \
        .given(the_war_room := get_settings().slack_war_room_channel) \
        .when(lambda: _at_the_workspace().post(the_war_room, _said(A_CONTRACT_CHECK),
                                               offer=_an_offer())) \
        .then(all_of(_it_landed(), _it_reads_as(_the_double_given_the_button_too())))


@pytest.mark.contract
@needs_a_real_workspace
def test_an_offer_can_be_rewritten_with_its_button_taken_away() -> None:
    # What the relay does to every offer when the incident is over. A message
    # the bot posted is one it may rewrite, and the rewrite comes back with the
    # message's id as a post does.
    the_war_room = get_settings().slack_war_room_channel

    Scenario() \
        .given(
            the_offer := _at_the_workspace().post(the_war_room, _said(A_CONTRACT_CHECK),
                                                  offer=_an_offer())
        ) \
        .when(lambda: _at_the_workspace().rewrite(the_war_room, str(the_offer.message),
                                                  _said(A_CONTRACT_CHECK_REWRITTEN))) \
        .then(all_of(_it_landed(), _it_reads_as(_the_double_rewriting_the_same_way())))


@pytest.mark.contract
@needs_a_real_workspace
def test_a_message_the_workspace_does_not_hold_cannot_be_rewritten() -> None:
    # The offer somebody deleted before the incident ended. The relay writes
    # this down and carries on, and every suite that checks it does so against
    # the double's word for it - which has to be the workspace's word.
    the_war_room = get_settings().slack_war_room_channel

    Scenario() \
        .given(NO_SUCH_MESSAGE) \
        .when(lambda: _at_the_workspace().rewrite(the_war_room, NO_SUCH_MESSAGE,
                                                  _said(A_CONTRACT_CHECK_REWRITTEN))) \
        .then(all_of(
            _it_was_refused_for(MESSAGE_NOT_FOUND),
            _it_is_not_worth_another_go(),
            _it_reads_as(_the_double_asked_to_rewrite_nothing())
        ))


@pytest.mark.contract
@needs_a_real_workspace
def test_a_person_the_workspace_knows_is_named() -> None:
    # What an offer is addressed to. The bot itself is the one member every
    # workspace running this is sure to have, so it is the person asked about;
    # the double is told about somebody, which is the only way it knows anyone.
    Scenario() \
        .given(the_bot := _who_the_bot_is()) \
        .when(lambda: _the_platform_at(get_settings().slack_bot_token, "").person_named(the_bot)) \
        .then(all_of(_somebody_was_named(), _named_as(_the_double_naming_somebody())))


@pytest.mark.contract
@needs_a_real_workspace
def test_a_person_the_workspace_does_not_know_is_refused_by_name() -> None:
    # Asked of the client rather than of the adapter, which reads every refusal
    # as "unnamed" and so could not tell this refusal from any other. What the
    # double claims is Slack's own word for it.
    Scenario() \
        .given(NO_SUCH_PERSON) \
        .when(lambda: _the_refusal_to_name(NO_SUCH_PERSON, _a_client_at_the_workspace())) \
        .then(_it_was_refused_as(USER_NOT_FOUND,
                                 _the_refusal_to_name(NO_SUCH_PERSON, _a_client_at_the_double())))


def _at_the_workspace() -> Slack:
    """The adapter pointed at the real workspace, built the way the demo builds
    it."""
    return _the_platform_at(get_settings().slack_bot_token, "")


def _at_the_double() -> Slack:
    """The adapter pointed at the double, built the way the demo builds it."""
    return _the_platform_at("xoxb-the-double-never-reads-this", DEFAULT_BASE_URL)


def _said(text: str) -> Line:
    """The check as Argus hands a line to the platform: said by nobody in
    particular, with nothing set apart."""
    return Line(who="Argus", text=text)


def _an_offer() -> Offer:
    """An offer about a message no channel holds: the button is what is
    checked, not what pressing it would find."""
    return Offer(about=a_chat_message(ReportChannel.SLACK, "C-war-room", NO_SUCH_MESSAGE),
                 label="Mark resolved")


def _the_double_asked_the_same_way() -> Posted:
    """The same call, at the stand-in."""
    return _at_the_double().post("C-war-room", _said(A_CONTRACT_CHECK))


def _the_double_given_the_button_too() -> Posted:
    return _at_the_double().post("C-war-room", _said(A_CONTRACT_CHECK), offer=_an_offer())


def _the_double_rewriting_the_same_way() -> Posted:
    posted = _the_double_given_the_button_too()

    return _at_the_double().rewrite("C-war-room", str(posted.message),
                                    _said(A_CONTRACT_CHECK_REWRITTEN))


def _the_double_asked_to_rewrite_nothing() -> Posted:
    return _at_the_double().rewrite("C-war-room", NO_SUCH_MESSAGE,
                                    _said(A_CONTRACT_CHECK_REWRITTEN))


def _the_double_refusing_the_same_way() -> Posted:
    """The same call at the stand-in, with the refusal Slack gave queued on it.

    Seeded rather than provoked: the double accepts any channel, so the only
    way to ask it the question the real workspace was asked is to tell it what
    the answer was. That is the comparison - not that the double invents the
    refusal, but that it says it the way the workspace said it.
    """
    httpx2.post(
        f"{DEFAULT_BASE_URL}/double-control/seed",
        json={"error": CHANNEL_NOT_FOUND},
        timeout=10.0
    ).raise_for_status()

    return _at_the_double().post(NO_SUCH_CHANNEL, _said(A_CONTRACT_CHECK))


def _the_double_naming_somebody() -> str | None:
    """The double asked about a person it was told about, with a real name as a
    workspace member has one."""
    httpx2.post(f"{DEFAULT_BASE_URL}/double-control/user",
                json={"id": SOME_PERSON, "real_name": "Some Person"},
                timeout=10.0).raise_for_status()

    return _the_platform_at("xoxb-the-double-never-reads-this",
                            DEFAULT_BASE_URL).person_named(SOME_PERSON)


def _the_platform_at(token: str, base_url: str) -> Slack:
    return Slack(ChatSettings(slack_bot_token=token, slack_base_url=base_url,
                              slack_signing_secret=""),
                 client_of=WebClient, clock=lambda: datetime.now(UTC))


def _who_the_bot_is() -> str:
    """The bot's own member id, as the workspace knows it."""
    return str(_a_client_at_the_workspace().auth_test()["user_id"])


def _a_client_at_the_workspace() -> WebClient:
    return WebClient(token=get_settings().slack_bot_token)


def _a_client_at_the_double() -> WebClient:
    return WebClient(token="xoxb-the-double-never-reads-this", base_url=f"{DEFAULT_BASE_URL}/api/")


def _the_refusal_to_name(person_id: str, client: WebClient) -> str:
    """Slack's own word for why it would not say who somebody is, or empty
    where it said."""
    try:
        client.users_info(user=person_id)
    except SlackApiError as refused:
        return str(refused.response.get("error") or "")

    return ""


def _it_landed() -> Assertion[Posted]:
    def assertion(posted: Posted) -> bool:
        if not posted.message:
            raise AssertionError(
                f"Expected the workspace to answer with an id, it refused: [{posted.refusal}]."
            )

        return True

    return assertion


def _it_was_refused_for(reason: str) -> Assertion[Posted]:
    def assertion(posted: Posted) -> bool:
        if posted.message is not None:
            raise AssertionError(f"Expected a refusal, the message landed as [{posted.message}].")

        if reason not in posted.refusal:
            raise AssertionError(
                f"Expected the refusal to name [{reason}], it said [{posted.refusal}]."
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
                f"Expected [{posted.refusal}] read as final, it was read as worth retrying."
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
        real = (from_the_workspace.message is not None,
                from_the_workspace.refusal,
                from_the_workspace.worth_another_go)
        stood_in = (at_the_double.message is not None,
                    at_the_double.refusal,
                    at_the_double.worth_another_go)

        if real != stood_in:
            raise AssertionError(
                f"Expected the double to answer as the workspace did {real}, it answered {stood_in}"
            )

        return True

    return assertion


def _somebody_was_named() -> Assertion[str | None]:
    def assertion(named: str | None) -> bool:
        if not named:
            raise AssertionError(
                "Expected the workspace to name its own bot, the adapter read nobody - "
                "check the bot has the `users:read` scope."
            )

        return True

    return assertion


def _named_as(at_the_double: str | None) -> Assertion[str | None]:
    """Both named, or both not. The names themselves are each side's own and
    nothing compares them."""
    def assertion(from_the_workspace: str | None) -> bool:
        if (from_the_workspace is None) != (at_the_double is None):
            raise AssertionError(
                f"Expected the double to name somebody as the workspace did "
                f"[{from_the_workspace}], it answered [{at_the_double}]."
            )

        return True

    return assertion


def _it_was_refused_as(reason: str, at_the_double: str) -> Assertion[str]:
    def assertion(from_the_workspace: str) -> bool:
        if (from_the_workspace, at_the_double) != (reason, reason):
            raise AssertionError(
                f"Expected both to refuse with [{reason}], the workspace said "
                f"[{from_the_workspace}] and the double [{at_the_double}]."
            )

        return True

    return assertion

