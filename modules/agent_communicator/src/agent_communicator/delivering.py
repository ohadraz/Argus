from __future__ import annotations

import logging

from argus_core.db import Connections
from argus_core.events import CommunicationFailed
from argus_incidents.repository import events
from argus_narration import NarrationLine
from slack_sdk import WebClient

from agent_communicator.policy import Register
from agent_communicator.relaying import Delivery, Outcome
from agent_communicator.repository import threads
from agent_communicator.slack import post_message

"""How a register becomes a message: the channel itself, or a reply in a thread.

The only module that knows what "loudly" means in Slack. A message in the
channel reaches everyone in it; a reply reaches whoever is following that
thread - so the register decides which of the two a line is, and nothing else
here has an opinion about it.

An incident's thread is whatever Slack called its first message. That is
remembered against the incident, because the line delivered twenty minutes
later is delivered by another pass and usually another process, and a
conversation nobody can find again is a channel of loose sentences.
"""

# How Slack marks a word inside a message. The narration hands the page three
# strings - what comes before the word it sets apart, the word, and what comes
# after - so that a view can mark it without anybody rendering markup; this is
# the same split, said in Slack's punctuation.
_MARKED = "*"

logger = logging.getLogger(__name__)


def a_destination_per_register(conversation: Delivery,
                               archive: Delivery,
                               argus_at: str = "",
                               filed_in: str = "") -> Delivery:
    """Two destinations made into one, chosen by how a line is to be said.

    The relay has one destination and no opinion about channels; the policy
    says which register a line belongs to and has no opinion about where that
    is. This is the join between them, and the only place that knows a team
    might keep its write-ups somewhere other than where it works incidents.

    Two deliveries rather than two channel names, so that "the archive" can be
    the war room - a team that configured no separate channel gets its
    postmortems where everything else is, through the same code path rather
    than a special case.

    `argus_at` is where Argus answers, as somebody outside it reaches it. A
    process that never serves a request cannot learn that from one, and the
    address a request arrived on is not the address behind a proxy anyway - so
    it is configured, as it is for everything else that links into itself.
    Empty means no link, which is a demo running without one rather than a
    broken link in a channel.

    `filed_in` names the archive, and only where it is not the war room. A
    conversation that ends without mentioning the write-up leaves whoever
    followed the incident to guess that one exists; where both go to the same
    channel the write-up is the next message, and saying so twice is noise.
    """

    def deliver(incident_id: str, line: NarrationLine, register: Register) -> Outcome:
        if register is not Register.FILED:
            return conversation(incident_id, line, register)

        its_page = _the_postmortem_page(argus_at, incident_id)
        outcome = archive(incident_id, _pointing_at(line, its_page), register)

        # Only once the write-up is somewhere. Pointing at an archive that
        # refused the message would send a reader to an empty channel, which
        # is worse than the silence it was meant to fix.
        if outcome is Outcome.SAID and filed_in:
            conversation(incident_id,
                         _where_to_read_it(line, filed_in, its_page),
                         Register.ANNOUNCED)

        return outcome

    return deliver


def _the_postmortem_page(argus_at: str, incident_id: str) -> str:
    """Where the whole write-up is, for a reader who wants more than a summary."""
    return f"{argus_at.rstrip('/')}/incidents/{incident_id}/postmortem" if argus_at else ""


def _pointing_at(line: NarrationLine, its_page: str) -> NarrationLine:
    """The same line, ending in a link to the page that holds all of it.

    On the line rather than on the message, so that what is said and where it
    is said stay one thing: the delivery below formats a line and does not
    know a postmortem from a verdict.

    Both the plain text and the tail after the marked word, because those are
    two spellings of one sentence and the formatter picks whichever the line
    has a marked word for. A copy rather than an edit: the line came from the
    narration, which is the page's too.
    """
    if not its_page:
        return line

    read_it = f"\n<{its_page}|Read the postmortem>"

    return line.model_copy(update={
        "text": f"{line.text}{read_it}",
        "after_emphasis": f"{line.after_emphasis}{read_it}"
    })


def _where_to_read_it(line: NarrationLine,
                      filed_in: str,
                      its_page: str) -> NarrationLine:
    """The war room's one line about a write-up that went somewhere else.

    Where to look, not what it says. The postmortem is long, it is already in
    the archive, and repeating it here would make the archive pointless.
    """
    linked = f" - <{its_page}|read it>" if its_page else ""

    return line.model_copy(update={
        "text": f"Postmortem filed in {filed_in}{linked}",
        "emphasis": "",
        "before_emphasis": "",
        "after_emphasis": ""
    })


def a_slack_delivery(connections: Connections,
                     channel: str,
                     slack: WebClient | None = None) -> Delivery:
    """A destination: one Slack channel, and a thread per incident inside it.

    The channel is given rather than read here, so that the war room and the
    postmortem channel are the same code twice rather than a branch - and so a
    test can point one at a scratch channel without a configured workspace.
    """

    def deliver(incident_id: str, line: NarrationLine, register: Register) -> Outcome:
        thread = _the_thread_of(connections, incident_id, channel)
        # An announcement goes to the channel even where a thread exists: how
        # an incident ended is addressed to everyone, including the people who
        # never opened it. A line to be followed goes into the thread when
        # there is one, and to the channel when there is not - the opening
        # message may have been refused, or this relay may have arrived
        # mid-incident, and a line in the wrong shape is worth more than
        # silence about an incident being worked.
        replying_to = thread if register is Register.FOLLOWED else None

        posted = post_message(channel, _as_slack_says_it(line), replying_to, slack)

        if posted.ts is None:
            # Slack's own answer, read for the only thing the relay can act on.
            # A throttle passes and the line waits where it is; anything else
            # is the end of this line, and what became of it is written down
            # here rather than carried back up - this is where the reason still
            # is, and the relay has no use for it.
            if posted.worth_another_go:
                return Outcome.NOT_NOW

            _write_the_gap_down(connections, incident_id, channel, line, posted.refusal)

            return Outcome.NEVER

        # What a demo has to go on. Everything Argus says is said by another
        # process than the one walking the incident, so without this the only
        # evidence a message was ever delivered is a row in `slack_thread`.
        logger.info(
            "said %s in %s for incident %s",
            "in the thread" if replying_to else "in the channel",
            channel,
            incident_id
        )

        if thread is None:
            # Whatever Slack called the first message is this incident's
            # conversation from now on, however loudly that message was said.
            _remember_the_thread(connections, incident_id, channel, posted.ts)

        return Outcome.SAID

    return deliver


def _as_slack_says_it(line: NarrationLine) -> str:
    """One line of the account, in Slack's own emphasis.

    Named, because "what did Argus do" is really "which of its agents did
    what": a channel where every sentence has the same silent subject reads as
    one program doing everything, which is the opposite of what this system is.

    The marked word is the flag, the status, the verdict - the one thing
    somebody scanning a channel should find without reading the line. It is
    marked from the split the narration already made rather than by searching
    the sentence for it, so a word that happens to appear twice is not marked
    in the wrong place.
    """
    if not line.emphasis:
        return f"{line.who}: {line.text}"

    marked = f"{_MARKED}{line.emphasis}{_MARKED}"

    return f"{line.who}: {line.before_emphasis}{marked}{line.after_emphasis}"


def _write_the_gap_down(connections: Connections,
                        incident_id: str,
                        channel: str,
                        line: NarrationLine,
                        refusal: str) -> None:
    """Records on the incident that one line of its account never arrived.

    On its own connection rather than beside a decision, because there is no
    decision here to join: nothing about the incident happened, and what is
    being written down is that something failed to be said about it.
    """
    with connections() as conn:
        events.record(conn, CommunicationFailed(
            incident_id=incident_id,
            channel=channel,
            refusal=refusal,
            about_kind=line.kind
        ))


def _the_thread_of(connections: Connections,
                   incident_id: str,
                   channel: str) -> str | None:
    with connections() as conn:
        return threads.get(conn, incident_id, channel)


def _remember_the_thread(connections: Connections,
                         incident_id: str,
                         channel: str,
                         ts: str) -> None:
    with connections() as conn:
        threads.remember(conn, incident_id, channel, ts)
