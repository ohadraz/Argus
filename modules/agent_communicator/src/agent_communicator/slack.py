"""Where a message actually goes: a Slack workspace, through Slack's own SDK.

The one place in Argus that knows Slack exists. Everything above it hands down
a channel and a sentence and is told nothing about how they are delivered -
which is what lets the destination change without the relay changing.

The SDK is built against a base URL rather than branched on. Empty means the
real workspace, and pointing it at `slack_double` is the whole of what selects
the double: no `if testing` anywhere, and the client, the argument encoding and
the response parsing exercised by a suite are the ones the demo runs.

Nothing here raises. A refusal or an unreachable workspace is reported back as
"no message" and the caller carries on, because communication is how an
incident is reported and not how it is resolved - an incident that escalated
because Slack rate-limited it would be a worse outcome than one nobody saw.
"""

from __future__ import annotations

import logging
from typing import Final, NamedTuple

from argus_core.config import Settings, get_settings
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

logger = logging.getLogger(__name__)

# The field Slack answers a delivered message with - its id, and the name of
# the thread any reply to it belongs to. Named here because this is the module
# that reads Slack's payloads; the arguments going the other way are the SDK's
# own keywords rather than strings this module writes.
_TS_FIELD: Final = "ts"

# The field a refusal Slack understood carries its own word for it in, beside
# an `ok: false`.
_ERROR_FIELD: Final = "error"

# Too many messages too quickly. Slack answers this one with a status rather
# than with a payload, which is why the status is what this module reads.
_THROTTLED_STATUS: Final = 429

# Where Slack's own trouble starts. Anything from here up is a workspace having
# a bad minute rather than an opinion about the message.
_SLACK_HAVING_TROUBLE: Final = 500

# How long one post may take before it is given up on. Well under the SDK's own
# thirty seconds, because the cost here is not the call - it is the walk behind
# it. A Slack that refuses says so at once; a Slack that accepts the connection
# and then goes quiet would otherwise hold up a mitigation for half a minute
# per message, and an incident slowed down by its own commentary is the thing
# every decision in this module is arranged to avoid.
_LONG_ENOUGH_TO_REACH_SLACK: Final = 5


def a_slack_client(base_url: str | None = None,
                   token: str | None = None,
                   timeout: int = _LONG_ENOUGH_TO_REACH_SLACK,
                   settings: Settings | None = None) -> WebClient:
    """The client every post goes through, built from what was configured.

    Each argument overrides the configured value rather than replacing the
    lookup, so a caller that wants to name only the workspace - a test pointing
    at the double, a script pointing at a scratch channel - does not have to
    supply a credential it has no opinion about.

    The SDK wants no trailing slash and appends `/api/...` itself, so a base
    URL given with one is trimmed rather than refused: it is the same
    workspace, spelled the way a person writes a URL.
    """
    resolved = settings if settings is not None else get_settings()
    where = base_url if base_url is not None else resolved.slack_base_url

    return WebClient(
        token=token if token is not None else resolved.slack_bot_token,
        base_url=f"{where.rstrip('/')}/api/" if where else WebClient.BASE_URL,
        timeout=timeout
    )


class Posted(NamedTuple):
    """What came of one post: the id if it landed, and why not if it did not.

    Three answers in two fields, because the caller has three things to do with
    them. A message with an id is the incident's thread from then on; a refusal
    worth another go keeps its place in the relay and is tried again; a refusal
    that is not is the end of that line, and the reason is what reaches the
    incident's timeline in its stead.
    """

    ts: str | None
    # Slack's own word for the refusal, or the transport's. Empty for a message
    # that arrived, because there is nothing to explain about one.
    refusal: str = ""
    # Whether trying the same message again could end differently. A throttle
    # and a workspace that did not answer say nothing about the message; every
    # other refusal is as true on the next pass as on this one.
    worth_another_go: bool = False


def post_message(channel: str,
                 text: str,
                 thread_ts: str | None = None,
                 slack: WebClient | None = None) -> Posted:
    """Posts one message, answering with what came of it.

    The id is what makes an incident's war room a thread: a reply names its
    parent, and a post whose answer was discarded is a war room nothing can
    reply into. No id says the message did not arrive, and the rest of the
    answer says whether that is worth anything on a later pass.

    `thread_ts` absent posts to the channel itself, which is a different act
    rather than a lesser one: a channel message reaches the channel, and a
    reply reaches the people following that thread. Which of the two a message
    is decides whether it interrupts anybody, and nothing else does.
    """
    posting = slack if slack is not None else a_slack_client()

    try:
        # `thread_ts=None` is not the same as a thread of `None`: the SDK drops
        # an argument that is None rather than sending it, so this is the call
        # that posts to the channel. Spelled as one call rather than two, since
        # branching here would put the channel-or-thread decision in the one
        # place that has no opinion about it.
        answered = posting.chat_postMessage(channel=channel, text=text, thread_ts=thread_ts)
    except SlackApiError as refused:
        # A no Slack understood and answered with. Whether it is worth another
        # go is the one thing the caller cannot work out for itself, so it is
        # worked out here, where Slack's own answer is still in hand.
        return _the_refusal_in(refused, channel)
    except OSError as unreachable:
        # Nothing answered at all - the transport's own error, for a workspace
        # never reached. It says nothing about the message, so the message is
        # worth sending again.
        logger.warning("slack could not be reached for %s: %s", channel, unreachable)

        return Posted(None, refusal=str(unreachable), worth_another_go=True)

    said: str | None = answered.get(_TS_FIELD)

    return Posted(said)


def _the_refusal_in(refused: SlackApiError, channel: str) -> Posted:
    """A refusal read for the one thing the relay has to decide: again, or not.

    On the status rather than on Slack's word for it. A throttle is a 429 and a
    workspace in trouble is a 5xx whichever of them it is called, while every
    refusal about the message itself - a channel renamed, a token revoked, a
    bot never invited - arrives as a 200 carrying `ok: false` and is as true on
    the next pass as on this one.

    Survived is not the same as unnoticed. Nothing downstream is told until a
    failure reaches the incident's own timeline, so this line names the channel
    too: a workspace where one channel was renamed looks, from inside Argus,
    exactly like one where the token expired.
    """
    answered = refused.response
    status: int = answered.status_code
    said = str(answered.get(_ERROR_FIELD) or f"HTTP {status}")

    logger.warning("slack would not take the message for %s: %s", channel, said)

    return Posted(
        None,
        refusal=said,
        worth_another_go=status == _THROTTLED_STATUS or status >= _SLACK_HAVING_TROUBLE
    )
