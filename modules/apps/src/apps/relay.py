"""The relay's root: what keeps the chat up to date (spec §7.5).

`python -m apps.relay`. What is said, where and how loudly is
`communication`'s; this decides what it is said through - the pool, the chat
platform's adapter, the channels - and starts the loop.
"""

from __future__ import annotations

import logging
from typing import Final

from chat_platform.slack import ChatSettings, slack_from
from communication.relaying import CHAT_RELAY
from communication.saying import (
    a_briefing,
    a_chat_destination,
    a_destination_per_register,
)
from communication.watching import watch_forever
from core import (
    Connections,
    DatabaseSettings,
    TelemetrySettings,
    get_settings,
    open_pool,
)
from incident_record import events_since, place_for
from telemetry import start_telemetry

logger = logging.getLogger(__name__)

# What this process is called in its telemetry, and the directory its runs are
# written under.
_SERVICE: Final = "argus-relay"


def main() -> None:
    """The process itself: a pool, a destination, then watch until killed.

    Where everything this process needs is built, and the only place that knows
    a pool exists. A `main` rather than bare module-level code, so that
    importing this module starts nothing and opens nothing.

    A relay with nowhere to post is not started at all - no channel, or no
    workspace to post it in. Posting where nobody configured would be refused
    on every pass for as long as the process ran, which is a log full of
    failures saying only that the stack was never configured.

    Telemetry is started before that is decided, so the warning saying so is in
    this run's logs as well as on the console.
    """
    settings = get_settings()

    with start_telemetry(TelemetrySettings.of(settings), _SERVICE):
        if not settings.slack_war_room_channel:
            logger.warning("no war-room channel configured")
            return

        # The chat platform's adapter, built here and nowhere else in this
        # process: one client for the whole relay, built where the process
        # starts, and everything below it holds only the port.
        chat = slack_from(ChatSettings.of(settings))

        if chat is None:
            logger.warning("no chat platform configured")
            return

        with open_pool(DatabaseSettings.of(settings)) as pool:
            connections: Connections = pool.connection

            logger.info("relay started", extra={"channel": settings.slack_war_room_channel})

            # Where write-ups go, which is the war room unless a team said
            # otherwise. Falling back rather than going silent: a postmortem
            # nobody was told about is the one thing worse than one in the
            # wrong channel, and leaving the setting empty is not a decision
            # to say nothing.
            war_room = settings.slack_war_room_channel
            archive = settings.slack_postmortem_channel or war_room

            watch_forever(
                events_since(connections),
                place_for(connections, CHAT_RELAY),
                a_destination_per_register(
                    a_chat_destination(connections, channel=war_room, chat=chat),
                    a_chat_destination(connections, channel=archive, chat=chat),
                    a_briefing(connections,
                               sent_to=settings.executive_synopsis_slack_to,
                               chat=chat,
                               argus_at=settings.argus_base_url),
                    argus_at=settings.argus_base_url,
                    # Named only where it is somewhere else. Where the two are
                    # the same channel the write-up is simply the next message,
                    # and a line saying where to find it would point at itself.
                    filed_in=archive if archive != war_room else ""
                ),
                pause=settings.slack_relay_poll_seconds
            )


if __name__ == "__main__":
    main()
