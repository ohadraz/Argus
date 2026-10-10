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

from argus_core import SettingsSlice, utc_now
from argus_core.models import ReportChannel, the_place_of
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from chat_platform.platform import Delivery, Line, Offer, Posted
from chat_platform.slack_deliveries import CONFIRM_ACTION, parse_delivery
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
# later line of an incident, or an intent agent holding up an offer. A Slack that
# refuses says so at once; one that accepts the connection and then goes quiet
# would otherwise cost half a minute a message.
_TIMEOUT_SECONDS: Final = 5

type ClientOf = Callable[..., Any]
type Clock = Callable[[], datetime]


class ChatSettings(SettingsSlice):
    """What it takes to talk to Slack, in both directions.

    An empty token is a deployment with no workspace, and builds no platform.
    An empty signing secret is a workspace whose deliveries are all refused.
    """

    slack_bot_token: str
    slack_base_url: str
    slack_signing_secret: str


class Slack:
    """The chat platform, as Slack answers it - what Argus reads from it and
    what Argus says in it."""

    def __init__(self, settings: ChatSettings, client_of: ClientOf, clock: Clock) -> None:
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
    def channel(self) -> ReportChannel:
        """Where a person's report through Slack reached Argus."""
        return ReportChannel.SLACK

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


def slack_from(settings: ChatSettings,
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
