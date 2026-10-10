"""The process that follows the event log and understands what people wrote.

It does one thing in a loop: look at the log, understand every message a person
wrote since the last look, move on. Nothing calls it and it calls nothing in the
walk - the two share a table and no code, as the relay and the walk do.

A process of its own rather than a part of the worker or the web: the worker
walks incidents for minutes at a time and a message is not a walk, and the web
answers the chat platform within three seconds, which a model does not.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from functools import partial
from typing import Final

from argus_core import (
    Connections,
    DatabaseSettings,
    TelemetrySettings,
    get_settings,
    open_pool,
)
from argus_core.events import PersonWrote
from argus_core.llm import build_llm_client
from argus_core.models import IncidentStatus, ModelPolicy
from argus_core.replay import Replay
from argus_incidents import (
    Backlog,
    Place,
    calls_into,
    events_into,
    events_since,
    place_for,
)
from argus_incidents.repository import incidents
from argus_telemetry import start_telemetry
from chat_platform.slack import ChatSettings, slack_from

from agent_intent.classifying import classify
from agent_intent.understanding import MeaningOf, understand

logger = logging.getLogger(__name__)

# Which reader this is, in `event_cursor`: its own row, so it keeps its own
# pace whatever the relay is doing.
INTENT: Final = "intent"

# What this process is called in its telemetry.
_SERVICE: Final = "argus-intent"

# How much one look at the log reads, for the relay's reason: a few passes to
# catch up after a restart, never an hour of the log in memory at once.
_A_BATCH: Final = 100

# Understanding one message a person wrote: classifying it, and offering what
# it calls for.
type Understand = Callable[[PersonWrote], None]


def watch_once(backlog: Backlog,
               place: Place,
               understand_one: Understand,
               batch: int = _A_BATCH) -> int:
    """One look at the log: understands every message a person wrote since the
    last look, and moves on behind itself.

    Returns how many events it dealt with, understood or passed over, which is
    what the process waits on.

    Each message is understood before the place moves past it, so an
    intent agent killed between the two understands one message twice - which is
    the direction this is meant to fail in. A message that could not be
    understood stops the look where it is and keeps the place in front of it: a
    person's words skipped are words Argus never took in, and the messages
    behind wait rather than being understood out of order. Everything else is
    passed over, and the place moves past it.
    """
    dealt_with = 0

    for recorded in backlog(place.where(), batch):
        if isinstance(recorded.event, PersonWrote):
            try:
                understand_one(recorded.event)
            except Exception:
                # Anything at all, deliberately: the model unreachable and the
                # database gone are both reasons to try again, and the next
                # look does. A failure that keeps happening keeps being said.
                logger.warning("message not understood", exc_info=True,
                               extra={"seq": recorded.seq})

                break

        place.move_to(recorded.seq)
        dealt_with += 1

    return dealt_with


def watch_forever(backlog: Backlog,
                  place: Place,
                  understand_one: Understand,
                  pause: float) -> None:
    """Understands what is new for as long as the process lives.

    Looks again immediately after a look that found anything, and waits only
    when it found nothing.
    """
    while True:
        if not watch_once(backlog, place, understand_one):
            time.sleep(pause)


def _understanding(connections: Connections,
                   policy: ModelPolicy,
                   person_named: Callable[[str], str | None]) -> Understand:
    """What understanding one message is, wired to the database, the model and
    the chat platform this process holds."""
    recorder = calls_into(connections)
    publisher = events_into(connections)

    def meaning_of(incident_id: str) -> MeaningOf:
        # A client per message, recording into that incident's replay log, as
        # the postmortem's is built per incident.
        return partial(classify,
                       llm=build_llm_client(Replay(incident_id, recorder), policy=policy))

    def status_of(incident_id: str) -> IncidentStatus | None:
        with connections() as conn:
            incident = incidents.get(conn, incident_id)

        return incident.status if incident is not None else None

    def understand_one(written: PersonWrote) -> None:
        understand(written,
                   meaning_of=meaning_of(written.incident_id),
                   status_of=status_of,
                   person_named=person_named,
                   publisher=publisher)

    return understand_one


def main() -> None:
    """The process itself: a pool, a model, a chat platform, then watch
    until killed.

    An intent agent with no chat platform is not started at all: nothing would
    ever be written for it to understand, and a process idling on a log it can
    never act on is a process somebody has to wonder about.
    """
    settings = get_settings()

    with start_telemetry(TelemetrySettings.of(settings), _SERVICE):
        platform = slack_from(ChatSettings.of(settings))

        if platform is None:
            logger.warning("no chat platform configured")
            return

        with open_pool(DatabaseSettings.of(settings)) as pool:
            connections: Connections = pool.connection

            logger.info("intent agent started")

            watch_forever(
                events_since(connections),
                place_for(connections, INTENT),
                _understanding(connections,
                               ModelPolicy(model=settings.intent_model,
                                           effort=settings.intent_effort),
                               platform.person_named),
                pause=settings.intent_poll_seconds
            )


if __name__ == "__main__":
    main()
