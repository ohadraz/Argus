from __future__ import annotations

import logging
import time

from argus_core.config import get_settings
from argus_core.db import Connections, open_pool

from agent_communicator.delivering import a_destination_per_register, a_slack_delivery
from agent_communicator.following import events_since, place_for
from agent_communicator.relaying import SLACK_RELAY, Backlog, Delivery, Place, relay_once

"""The process that watches the event log and keeps Slack up to date.

It does one thing in a loop: look at the log, say what is new, move on. Nothing
calls it and it calls nothing in the walk - the two share a table and no code,
which is what lets an incident be reported by a process that was restarted
halfway through it.

A process of its own rather than a thread inside the worker: a worker walking
an incident is busy for minutes at a time, and a relay sharing that process
would go quiet exactly while an incident was most worth hearing about.
"""

logger = logging.getLogger(__name__)


def watch_forever(backlog: Backlog,
                  place: Place,
                  deliver: Delivery,
                  pause: float) -> None:
    """Says what is new for as long as the process lives.

    Looks again immediately after saying anything and waits only when it found
    nothing: the pause is the delay between something happening and a person
    hearing about it, and paying it between two lines that were already waiting
    would add it to every one of them.

    Nothing here catches anything. A pass that fails on the database fails the
    process, and the place it kept is what makes that harmless - a relay
    restarted carries on from the last line anybody saw, saying at worst one
    line twice.
    """
    while True:
        if not relay_once(backlog, place, deliver):
            time.sleep(pause)


def main() -> None:
    """The process itself: a pool, a destination, then watch until killed.

    Where everything this process needs is built, and the only place that knows
    a pool exists. A `main` rather than bare module-level code, so that
    importing this module starts nothing and opens nothing.

    A relay with nowhere to post is not started at all. Posting to a channel
    nobody named would be refused by Slack on every pass for as long as the
    process ran, which is a log full of failures saying only that the stack was
    never configured.
    """
    logging.basicConfig(level=logging.INFO)
    settings = get_settings()

    if not settings.slack_war_room_channel:
        logger.warning("no war-room channel configured, so nothing is relayed to Slack")
        return

    with open_pool() as pool:
        connections: Connections = pool.connection

        logger.info("relaying to %s", settings.slack_war_room_channel)

        # Where write-ups go, which is the war room unless a team said
        # otherwise. Falling back rather than going silent: a postmortem
        # nobody was told about is the one thing worse than one in the wrong
        # channel, and leaving the setting empty is not a decision to say
        # nothing.
        war_room = settings.slack_war_room_channel
        archive = settings.slack_postmortem_channel or war_room

        watch_forever(
            events_since(connections),
            place_for(connections, SLACK_RELAY),
            a_destination_per_register(
                a_slack_delivery(connections, channel=war_room),
                a_slack_delivery(connections, channel=archive),
                argus_at=settings.argus_base_url,
                # Named only where it is somewhere else. Where the two are the
                # same channel the write-up is simply the next message, and a
                # line saying where to find it would point at itself.
                filed_in=archive if archive != war_room else ""
            ),
            pause=settings.slack_relay_poll_seconds
        )


if __name__ == "__main__":
    main()
