"""Slack, as the chat platform an incident is talked about in.

Parses what Slack delivers under the app's signing secret, names a person
through `users.info`, and posts and rewrites what Argus says. Reached through
Slack's own SDK, aimed by configuration at whichever host is to answer - the
real workspace, or `slack_double` - so the request path is the same one either
way.

Nothing that reaches Slack raises. Naming is asked when Argus offers a person
the chance to confirm an ending, and a workspace that cannot say who
somebody is must not cost them the offer: the answer is `None`, and the log
says why. Posting answers a refusal as "no message", for `slack_posting`'s
reason.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any, Final

from core import AdapterSettings, utc_now
from core.models import the_place_of
from pydantic import Field
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from chat_platform.platform import Delivery, Line, Offer, Posted
from chat_platform.slack_deliveries import CONFIRM_ACTION, SLACK, parse_delivery
from chat_platform.slack_posting import (
    a_line_with_a_button,
    as_slack_says_it,
    post_message,
    update_message,
)

logger = logging.getLogger(__name__)

# `users.info`'s answer: the user, their real name, and the profile their
# display name is kept in (docs.slack.dev, "users.info"). Slack says a field
# nobody supplied may be absent, null or empty, and all three read alike here.
USER: Final = "user"
REAL_NAME: Final = "real_name"
PROFILE: Final = "profile"
DISPLAY_NAME: Final = "display_name"

# How long one call may take. Well under the SDK's own thirty seconds, because
# the cost is not the call but what waits behind it: a relay holding up every
# later line of an incident, or an intent reader holding up an offer. A Slack that
# refuses says so at once; one that accepts the connection and then goes quiet
# would otherwise cost half a minute a message.
_TIMEOUT_SECONDS: Final = 5

# How Slack names a channel it can be asked about: a public one's id begins with
# `C`, a private one's with `G`, and the rest is capitals and digits. Empty is
# allowed, and means no channel was configured.
_A_CHANNEL_ID: Final = r"^([CG][A-Z0-9]+)?$"

type ClientOf = Callable[..., Any]
type Clock = Callable[[], datetime]


class SlackSettings(AdapterSettings):
    """What it takes to talk to Slack, in both directions, and where to.

    An empty token is a deployment with no workspace, and builds no platform.
    An empty signing secret is a workspace whose deliveries are all refused.
    The channels and the synopsis's readers are Slack's ids, so they are Slack's
    settings too, read by the relay's root and handed to the Communicator as
    the places it posts.
    """

    # The bot the Communicator posts as. Empty by default, and empty means it
    # says nothing: a workspace nobody configured is not a workspace to guess
    # at, and an incident is reported through a channel somebody chose.
    slack_bot_token: str = Field(default="")

    # Where the SDK sends its requests. Empty means the real workspace, for the
    # reason the model provider's base URL works that way: pointing this at the
    # double is the only thing that selects it, so the real adapter, the real
    # client and the real argument encoding still run in every suite.
    slack_base_url: str = Field(default="")

    # What a delivery from Slack - a person writing in an incident's thread, a
    # button pressed - must be signed with to be believed. Empty refuses every
    # delivery rather than trusting one: what a delivery can say ends an
    # incident, and a secret nobody set is one anybody can sign under.
    slack_signing_secret: str = Field(default="")

    # Where an incident is reported and where its postmortem is delivered. Two
    # channels rather than one: an incident's traffic is for whoever is on, and
    # a postmortem is read afterwards by people who were not.
    #
    # By id (`C...`), never by name. Slack takes a name to post to and for
    # nothing else: an update needs the id, and every reply and press arrives
    # naming the id - so a war room configured by name is one whose threads no
    # reply is ever matched to. The double answers any channel it is given, so
    # only a real workspace would show it, and only by going quiet.
    slack_war_room_channel: str = Field(default="", pattern=_A_CHANNEL_ID)
    slack_postmortem_channel: str = Field(default="", pattern=_A_CHANNEL_ID)

    # Who is sent each incident's executive synopsis, as Slack ids separated by
    # commas: a member's (`U...`) is sent it as a direct message, a channel's
    # (`C...`) is posted it in that channel. One list for both, because
    # `chat.postMessage` takes either as where to post. Empty sends it nowhere -
    # it is still written, and nobody is told.
    #
    # The synopsis states what each title's time on the incident cost, so who
    # is here is who sees pay. Nothing checks that a member is not one of the
    # people priced, or that a channel is private: both are the configurer's.
    executive_synopsis_slack_to: str = Field(default="")

    # How long the relay waits after finding the log unchanged. Short, because
    # it is the delay between something happening and a person hearing about
    # it - and paid only when there is nothing to say, since a pass that
    # delivered anything looks again at once.
    slack_relay_poll_seconds: float = Field(default=2.0, gt=0.0)


class Slack:
    """The chat platform, as Slack answers it - what Argus reads from it and
    what Argus says in it."""

    def __init__(self, settings: SlackSettings, client_of: ClientOf, clock: Clock) -> None:
        self._secret = settings.slack_signing_secret
        self._clock = clock
        # The SDK wants no trailing slash and appends `/api/...` itself, so a
        # base URL given with one is trimmed rather than refused: it is the same
        # workspace, spelled the way a person writes a URL.
        where = settings.slack_base_url.rstrip("/")
        self._client = client_of(
            token=settings.slack_bot_token,
            base_url=f"{where}/api/" if where else WebClient.BASE_URL,
            timeout=_TIMEOUT_SECONDS
        )

    @property
    def name(self) -> str:
        """Slack, as people know it and as the incident's references file it."""
        return SLACK

    def parse_delivery(self, body: bytes, headers: Mapping[str, str]) -> Delivery:
        """What one delivery says, believed only under this workspace's secret
        and within five minutes of this platform's clock."""
        return parse_delivery(body, headers, self._secret, self._clock())

    def person_named(self, person_id: str) -> str | None:
        """What Slack calls this person: their real name, else their display
        name, else `None` - including when Slack refuses or cannot be reached."""
        try:
            user = self._client.users_info(user=person_id)[USER]
        except (SlackApiError, OSError):
            logger.warning("person unnamed", extra={"person_id": person_id}, exc_info=True)

            return None

        return (user.get(REAL_NAME)
                or (user.get(PROFILE) or {}).get(DISPLAY_NAME)
                or None)

    def post(self,
             channel: str,
             line: Line,
             thread: str | None = None,
             offer: Offer | None = None) -> Posted:
        """Posts `line`, as a reply where `thread` names one, with `offer`'s
        button under it where one is given."""
        said = as_slack_says_it(line)

        return post_message(channel, said, thread,
                            _the_button_for(offer, said) if offer is not None else None,
                            slack=self._client)

    def rewrite(self, channel: str, message: str, line: Line) -> Posted:
        """Rewrites a message Argus posted to say only `line`, with no button."""
        return update_message(channel, message, as_slack_says_it(line), slack=self._client)


def _the_button_for(offer: Offer, said: str) -> list[dict[str, Any]]:
    """The line, and the one button that confirms it, naming the message whose
    writer may press it.

    The message as Slack named it and nothing more: a press arrives with the
    channel it was made in, so the channel would be the same fact said twice.
    """
    _, written = the_place_of(offer.about.value)

    return a_line_with_a_button(said, offer.label, CONFIRM_ACTION, written)


def slack_from(settings: SlackSettings,
               client_of: ClientOf = WebClient,
               clock: Clock = utc_now) -> Slack | None:
    """Slack as the chat platform, or `None` where the deployment has none.

    Slack is optional, and a deployment holding no token has no chat platform
    at all. `None` is how that reaches every caller, and nothing is built on
    the way to saying it.
    """
    if not settings.slack_bot_token:
        return None

    return Slack(settings, client_of, clock)
