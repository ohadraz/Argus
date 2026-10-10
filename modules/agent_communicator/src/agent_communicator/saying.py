"""How a register becomes a message: the channel itself, or a reply in a thread.

The only module that knows what "loudly" means in a chat. A message in the
channel reaches everyone in it; a reply reaches whoever is following that
thread - so the register decides which of the two a line is, and nothing else
here has an opinion about it. How the platform marks a word, draws a link or a
button is the platform adapter's; this hands it a line in its parts.

An incident's thread is whatever the platform called its first message. That is
remembered against the incident, because the line said twenty minutes later is
said by another pass and usually another process, and a conversation nobody can
find again is a channel of loose sentences.
"""

from __future__ import annotations

import logging
from typing import Final

from argus_core import Connections
from argus_core.events import CommunicationFailed
from argus_core.models import (
    CHAT_RESOLUTION_OFFER,
    CHAT_THREAD,
    CHAT_WITHDRAWAL_OFFER,
    IncidentStatus,
    a_chat_resolution_offer,
    a_chat_thread,
    a_chat_withdrawal_offer,
    the_place_of,
)
from argus_incidents.repository import events, references
from argus_narration import NarrationLine
from chat_platform import ChatPlatformWrites, Line, Link, Offer

from agent_communicator.policy import Register
from agent_communicator.relaying import Destination, Outcome

# What the button on an offer says, by the ending its press brings about. The
# question is the line above it, so the button is the answer, in the words of
# the act it performs.
_CONFIRMING: Final = {
    IncidentStatus.RESOLVED: "Mark resolved",
    IncidentStatus.WITHDRAWN: "Stand Argus down"
}

# How a posted offer is remembered, by the ending it offers - apart, because
# the incident's endings retire the two differently.
_REMEMBERED_AS: Final = {
    IncidentStatus.RESOLVED: a_chat_resolution_offer,
    IncidentStatus.WITHDRAWN: a_chat_withdrawal_offer
}

# What the link to a write-up says: under the write-up's own summary, and under
# the war room's line saying where it was filed.
_READ_THE_POSTMORTEM: Final = "Read the postmortem"

logger = logging.getLogger(__name__)


def a_destination_per_register(conversation: Destination,
                               archive: Destination,
                               argus_at: str = "",
                               filed_in: str = "") -> Destination:
    """Two destinations made into one, chosen by how a line is to be said.

    The relay has one destination and no opinion about channels; the policy
    says which register a line belongs to and has no opinion about where that
    is. This is the join between them, and the only place that knows a team
    might keep its write-ups somewhere other than where it works incidents.

    Two destinations rather than two channel names, so that "the archive" can
    be the war room - a team that configured no separate channel gets its
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

    def say(incident_id: str,
            line: NarrationLine,
            register: Register,
            link: Link | None = None) -> Outcome:
        if register is not Register.FILED:
            return conversation(incident_id, line, register, link)

        its_page = _the_postmortem_page(argus_at, incident_id)
        outcome = archive(incident_id, line, register, its_page)

        # Only once the write-up is somewhere. Pointing at an archive that
        # refused the message would send a reader to an empty channel, which
        # is worse than the silence it was meant to fix.
        if outcome is Outcome.SAID and filed_in:
            conversation(incident_id,
                         _where_to_read_it(line, filed_in),
                         Register.ANNOUNCED,
                         its_page)

        return outcome

    return say


def _the_postmortem_page(argus_at: str, incident_id: str) -> Link | None:
    """Where the whole write-up is, for a reader who wants more than a summary,
    or `None` where Argus was given no address of its own."""
    if not argus_at:
        return None

    return Link(url=f"{argus_at.rstrip('/')}/incidents/{incident_id}/postmortem",
                label=_READ_THE_POSTMORTEM)


def _where_to_read_it(line: NarrationLine, filed_in: str) -> NarrationLine:
    """The war room's one line about a write-up that went somewhere else.

    Where to look, not what it says. The postmortem is long, it is already in
    the archive, and repeating it here would make the archive pointless.
    """
    return line.model_copy(update={
        "text": f"Postmortem filed in {filed_in}",
        "emphasis": "",
        "before_emphasis": "",
        "after_emphasis": ""
    })


def a_chat_destination(connections: Connections,
                       channel: str,
                       chat: ChatPlatformWrites) -> Destination:
    """A destination: one channel of the chat platform, and a thread per
    incident inside it.

    The channel is given rather than read here, so that the war room and the
    postmortem channel are the same code twice rather than a branch - and so a
    test can point one at a scratch channel without a configured workspace.
    """

    def say(incident_id: str,
            line: NarrationLine,
            register: Register,
            link: Link | None = None) -> Outcome:
        thread = _the_thread_of(connections, incident_id, channel)
        # An announcement goes to the channel even where a thread exists: how
        # an incident ended is addressed to everyone, including the people who
        # never opened it. A line to be followed goes into the thread when
        # there is one, and to the channel when there is not - the opening
        # message may have been refused, or this relay may have arrived
        # mid-incident, and a line in the wrong shape is worth more than
        # silence about an incident being worked.
        replying_to = thread if register is Register.FOLLOWED else None
        said = _the_chat_line(line, link)
        about = line.asks_to_confirm
        ending = line.offers_to_end_as
        offer = (Offer(about=about, label=_CONFIRMING[ending])
                 if about is not None and ending is not None else None)

        posted = chat.post(channel, said, replying_to, offer)

        if posted.message is None:
            # The platform's own answer, read for the only thing the relay can
            # act on. A throttle passes and the line waits where it is; anything
            # else is the end of this line, and what became of it is written
            # down here rather than carried back up - this is where the reason
            # still is, and the relay has no use for it.
            if posted.worth_another_go:
                return Outcome.NOT_NOW

            logger.error("line will never be said",
                         extra={"channel": channel, "refusal": posted.refusal})
            _write_the_gap_down(connections, incident_id, channel, line, posted.refusal)

            return Outcome.NEVER

        # Per message, so DEBUG: what someone tracing one conversation turns on.
        # Everything Argus says is said by another process than the one walking
        # the incident, so short of this the evidence a message was said is the
        # thread it left among the incident's references.
        logger.debug("line said",
                     extra={"channel": channel, "in_thread": replying_to is not None})

        if thread is None:
            # Whatever the platform called the first message is this incident's
            # conversation from now on, however loudly that message was said.
            _remember_the_thread(connections, incident_id, chat, channel, posted.message)

        if offer is not None and ending is not None:
            # A button outlives the question it asked: the incident may end by
            # another channel while it is still on screen, and whoever ends it
            # has to find this message again to take the button away.
            _remember_the_offer(connections, incident_id, chat, channel, posted.message,
                                ending)

        # Once the ending - or Argus carrying on without an answer - has been
        # said, not before: a line held back by a throttle comes round again,
        # and its offers are retired then.
        for kind in _the_offers_retired_by(line):
            _retire_the_offers(connections, incident_id, channel, kind, line, said, chat)

        return Outcome.SAID

    return say


def _the_chat_line(line: NarrationLine, link: Link | None) -> Line:
    """One line of the account, as the chat platform is handed it: who said
    it, what they said, the word set apart, and where to read more.

    The split is the narration's, made once for every view, so that the page
    and the chat mark the same word.
    """
    return Line(who=line.who,
                text=line.text,
                emphasis=line.emphasis,
                before_emphasis=line.before_emphasis,
                after_emphasis=line.after_emphasis,
                link=link)


def _the_offers_retired_by(line: NarrationLine) -> list[str]:
    """Which kinds of offer this line takes the button off.

    An expiry takes every one: Argus carried on without an answer to any of
    them. An ending takes each kind it leaves impossible - a resolution's at
    `resolved`, `withdrawn` and `disproven`, a withdrawal's at those and at
    every other ending too, `mitigated` among them.
    """
    retired = []

    if line.leaves_nothing_to_resolve or line.expires_the_offers:
        retired.append(CHAT_RESOLUTION_OFFER)

    if line.leaves_nothing_to_withdraw or line.expires_the_offers:
        retired.append(CHAT_WITHDRAWAL_OFFER)

    return retired


def _retire_the_offers(connections: Connections,
                       incident_id: str,
                       channel: str,
                       kind: str,
                       line: NarrationLine,
                       said: Line,
                       chat: ChatPlatformWrites) -> None:
    """Rewrites every offer of `kind` this incident has in this channel to say
    how it ended, with nothing left to press.

    In the ending's own words, because they are the ones that say who ended it
    and through what - or, where Argus ended it, what status it ended in - and
    a sentence written here for the purpose would be the same fact told twice.

    One refusal costs one offer and nothing else. The incident is over either
    way, and a press on the button left behind changes nothing; what is lost is
    a message that still asks, which is written down where a reader will find
    it, as a line that could not be said is.
    """
    for offer in _the_messages_of(connections, incident_id, kind, channel):
        rewritten = chat.rewrite(channel, offer, said)

        if rewritten.message is None:
            logger.warning("offer keeps its button",
                           extra={"channel": channel, "refusal": rewritten.refusal})
            _write_the_gap_down(connections, incident_id, channel, line, rewritten.refusal)


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
    """The thread the incident is told in in this channel, as the platform
    named its first message - one of the incident's references, found again in
    another pass, another process, another day."""
    return next(iter(_the_messages_of(connections, incident_id, CHAT_THREAD, channel)), None)


def _the_messages_of(connections: Connections,
                     incident_id: str,
                     kind: str,
                     channel: str) -> list[str]:
    """Every message of one kind the incident remembers in this channel, as the
    platform named each - the thread it is told in, or the offers it made."""
    with connections() as conn:
        values = references.get_values_for(conn, incident_id, kind)

    places = (the_place_of(value) for value in values)

    return [message for in_channel, message in places if in_channel == channel]


def _remember_the_thread(connections: Connections,
                         incident_id: str,
                         chat: ChatPlatformWrites,
                         channel: str,
                         message: str) -> None:
    """Records the conversation an incident was opened in, once and for good.

    A second opening message - two relays at once, a pass repeated after a
    crash - writes nothing and leaves the first thread standing, because the
    incident record holds one thread per incident per channel. The duplicate
    message is the price of at-least-once delivery; scattering the rest of the
    incident into a conversation nobody is reading is not.
    """
    with connections() as conn:
        references.add(conn, incident_id, [a_chat_thread(chat.channel, channel, message)])


def _remember_the_offer(connections: Connections,
                        incident_id: str,
                        chat: ChatPlatformWrites,
                        channel: str,
                        message: str,
                        ending: IncidentStatus) -> None:
    """Records an offer Argus posted, as the kind of offer it is, so that the
    incident's endings can find its button again."""
    with connections() as conn:
        references.add(conn, incident_id, [_REMEMBERED_AS[ending](chat.channel, channel, message)])
