"""What Argus says in Slack: a message, a reply in a thread, a rewrite of one.

The other direction to `slack_deliveries`, and pure in the same way: each call
takes the client it goes through, so the adapter composes these and nothing
here decides which workspace answers. A client aimed at the real workspace and
one aimed at `slack_double` are the same request path.

Nothing here raises. A refusal or an unreachable workspace is reported back as
"no message" and the caller carries on, because communication is how an
incident is reported and not how it is resolved - an incident that escalated
because Slack rate-limited it would be a worse outcome than one nobody saw.
"""

from __future__ import annotations

import logging
from typing import Any, Final

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from chat_platform.platform import Line, Posted
from chat_platform.slack_deliveries import ACTION_ID, VALUE

logger = logging.getLogger(__name__)

# How Slack's `mrkdwn` marks a word, and draws a link: a word between two
# asterisks is bold, and `<url|label>` is a link that reads as its label
# (docs.slack.dev, "Formatting text for app surfaces").
_BOLD: Final = "*"
_LINK: Final = "<{url}|{label}>"

# The field Slack answers a delivered message with - its id, and the name of
# the thread any reply to it belongs to. The arguments going the other way are
# the SDK's own keywords rather than strings this module writes.
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

# Block Kit, as far as a line with a button needs it: a section that says the
# line, and an actions block holding the one button (docs.slack.dev, "Block
# Kit"). Public where a reader of a posted message reads it in these words. The
# button's `action_id` and `value` are the fields a press carries back, so they
# are named once, where the press is read.
BLOCK_TYPE: Final = "type"
SECTION_BLOCK: Final = "section"
ACTIONS_BLOCK: Final = "actions"
ELEMENTS: Final = "elements"
BUTTON_ELEMENT: Final = "button"
TEXT_FIELD: Final = "text"
_MARKDOWN_TEXT: Final = "mrkdwn"
_PLAIN_TEXT: Final = "plain_text"
_STYLE_FIELD: Final = "style"
_PRIMARY_STYLE: Final = "primary"


def as_slack_says_it(line: Line) -> str:
    """One line, in Slack's own markup.

    Named, because "what did Argus do" is really "which of its agents did
    what": a channel where every sentence has the same silent subject reads as
    one program doing everything, which is the opposite of what Argus is.

    The marked word is marked from the split the line already carries rather
    than by searching the sentence for it, so a word that happens to appear
    twice is not marked in the wrong place. A link goes on a line of its own
    under the sentence, where it reads as somewhere to go rather than as part of
    what was said.
    """
    said = (f"{line.before_emphasis}{_BOLD}{line.emphasis}{_BOLD}{line.after_emphasis}"
            if line.emphasis else line.text)
    linked = (f"\n{_LINK.format(url=line.link.url, label=line.link.label)}"
              if line.link is not None else "")

    return f"{line.who}: {said}{linked}"


def a_line_with_a_button(said: str,
                         label: str,
                         action_id: str,
                         value: str) -> list[dict[str, Any]]:
    """A message's blocks: the line as said, and one button under it.

    The line is in the blocks as well as in the text, because a message with
    blocks shows the blocks and keeps the text for notifications and for
    clients that draw none - the same sentence twice, by Slack's own rule.
    """
    return [
        {BLOCK_TYPE: SECTION_BLOCK,
         TEXT_FIELD: {BLOCK_TYPE: _MARKDOWN_TEXT, TEXT_FIELD: said}},
        {BLOCK_TYPE: ACTIONS_BLOCK,
         ELEMENTS: [{BLOCK_TYPE: BUTTON_ELEMENT,
                     TEXT_FIELD: {BLOCK_TYPE: _PLAIN_TEXT, TEXT_FIELD: label},
                     _STYLE_FIELD: _PRIMARY_STYLE,
                     ACTION_ID: action_id,
                     VALUE: value}]}
    ]


def post_message(channel: str,
                 text: str,
                 thread_ts: str | None = None,
                 blocks: list[dict[str, Any]] | None = None,
                 *,
                 slack: WebClient) -> Posted:
    """Posts one message, answering with what came of it.

    The id is what makes an incident's war room a thread: a reply names its
    parent, and a post whose answer was discarded is a war room nothing can
    reply into. No id says the message did not arrive, and the rest of the
    answer says whether that is worth anything on a later pass.

    `thread_ts` absent posts to the channel itself, which is a different act
    rather than a lesser one: a channel message reaches the channel, and a
    reply reaches the people following that thread.

    `blocks` absent is a message that is only its text, which is every message
    but one that asks for a press.
    """
    try:
        # `thread_ts=None` is not the same as a thread of `None`: the SDK drops
        # an argument that is None rather than sending it, so this is the call
        # that posts to the channel. Spelled as one call rather than two, since
        # branching here would put the channel-or-thread decision in the one
        # place that has no opinion about it.
        answered = slack.chat_postMessage(channel=channel, text=text, thread_ts=thread_ts,
                                          blocks=blocks)
    except SlackApiError as refused:
        # A no Slack understood and answered with. Whether it is worth another
        # go is the one thing the caller cannot work out for itself, so it is
        # worked out here, where Slack's own answer is still in hand.
        return _the_refusal_in(refused, channel)
    except OSError as unreachable:
        # Nothing answered at all - the transport's own error, for a workspace
        # never reached. It says nothing about the message, so the message is
        # worth sending again.
        logger.warning("slack could not be reached", exc_info=True, extra={"channel": channel})

        return Posted(None, refusal=str(unreachable), worth_another_go=True)

    said: str | None = answered.get(_TS_FIELD)

    return Posted(said)


def update_message(channel: str,
                   ts: str,
                   text: str,
                   *,
                   slack: WebClient) -> Posted:
    """Rewrites a message Argus posted to say only `text`, answering as a post
    does.

    No blocks rather than the old ones: an update is a message's new body, and
    what this is for is taking a button away. Said with an empty list, because
    Slack keeps a message's blocks through an update that names none of its
    own only where the text is left out too - and an argument the SDK drops for
    being `None` would rely on that rule rather than say what is meant.
    """
    try:
        answered = slack.chat_update(channel=channel, ts=ts, text=text, blocks=[])
    except SlackApiError as refused:
        return _the_refusal_in(refused, channel)
    except OSError as unreachable:
        logger.warning("slack could not be reached", exc_info=True, extra={"channel": channel})

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

    logger.warning("slack refused the message",
                   extra={"channel": channel, "refusal": said, "status": status})

    return Posted(
        None,
        refusal=said,
        worth_another_go=status == _THROTTLED_STATUS or status >= _SLACK_HAVING_TROUBLE
    )
