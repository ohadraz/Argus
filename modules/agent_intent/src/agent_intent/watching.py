"""The process that understands what people wrote in incidents' threads.

It does one thing in a loop: ask the incident record for the messages nobody has
understood yet, understand each, oldest first, and ask again. Nothing calls it
and it calls nothing in the walk - the two share a table and no code, as the
relay and the walk do.

It finds its work on the record rather than by following the event log: a
message is the agent's to understand until the record says what it meant, and
an account that could decide what is done would be a participant
(`argus_core.events`).

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
from argus_core.llm import build_llm_client
from argus_core.models import (
    IncidentStatus,
    Meaning,
    ModelPolicy,
    OfferedEnding,
    Reference,
    ThreadMessage,
)
from argus_core.replay import Replay
from argus_incidents import calls_into, events_into
from argus_incidents.repository import conversation, events, incidents
from argus_narration import build_narration
from argus_telemetry import start_telemetry
from chat_platform.slack import ChatSettings, slack_from

from agent_intent.answering import answer
from agent_intent.classifying import classify
from agent_intent.understanding import AnswerOf, MeaningOf, understand

logger = logging.getLogger(__name__)

# What this process is called in its telemetry.
_SERVICE: Final = "argus-intent"

# How many messages one look asks for: a few looks to catch up after a
# restart, never an hour of messages in memory at once.
_A_BATCH: Final = 100

# Up to so many messages nobody has understood, oldest first.
type NotUnderstood = Callable[[int], list[ThreadMessage]]
# Understanding one message a person wrote: classifying it, and offering what
# it calls for.
type Understand = Callable[[ThreadMessage], None]


def watch_once(not_understood: NotUnderstood,
               understand_one: Understand,
               batch: int = _A_BATCH) -> int:
    """One look: understands every message nobody has understood yet, oldest
    first, and says how many it understood.

    Which is what the process waits on. A message that could not be understood
    stops the look where it is: the next look finds it again, because a
    person's words skipped are words Argus never took in, and the messages
    behind it wait rather than being understood out of order. It is not
    counted, so a look that only failed waits before trying again rather than
    spinning on it.
    """
    understood = 0

    for written in not_understood(batch):
        try:
            understand_one(written)
        except Exception:
            # Anything at all, deliberately: the model unreachable and the
            # database gone are both reasons to try again, and the next
            # look does. A failure that keeps happening keeps being said.
            logger.warning("message not understood", exc_info=True,
                           extra={"incident_id": written.incident_id,
                                  "chat_message": written.message.value})

            break

        understood += 1

    return understood


def watch_forever(not_understood: NotUnderstood,
                  understand_one: Understand,
                  pause: float) -> None:
    """Understands what is new for as long as the process lives.

    Looks again immediately after a look that understood anything, and waits
    only when it understood nothing.
    """
    while True:
        if not watch_once(not_understood, understand_one):
            time.sleep(pause)


class _TheRecord:
    """The incident record's conversation, as understanding a message writes to
    it, over the connections this process holds."""

    def __init__(self, connections: Connections) -> None:
        self._connections = connections

    def understood(self, message: Reference, meaning: Meaning) -> None:
        with self._connections() as conn:
            conversation.understood(conn, message, meaning)

    def named(self, message: Reference, person_name: str | None) -> None:
        with self._connections() as conn:
            conversation.named(conn, message, person_name)

    def offered(self, message: Reference, ending: OfferedEnding) -> None:
        with self._connections() as conn:
            conversation.offered(conn, message, ending)


def _not_understood(connections: Connections) -> NotUnderstood:
    """What a look asks, wired to the record."""
    def not_understood(limit: int) -> list[ThreadMessage]:
        with connections() as conn:
            return conversation.get_not_understood(conn, limit)

    return not_understood


def _understanding(connections: Connections,
                   policy: ModelPolicy,
                   person_named: Callable[[str], str | None]) -> Understand:
    """What understanding one message is, wired to the database, the model and
    the chat platform this process holds."""
    recorder = calls_into(connections)
    publisher = events_into(connections)
    record = _TheRecord(connections)

    def meaning_of(incident_id: str) -> MeaningOf:
        # A client per message, recording into that incident's replay log, as
        # the postmortem's is built per incident.
        return partial(classify,
                       llm=build_llm_client(Replay(incident_id, recorder), policy=policy))

    def answer_of(incident_id: str) -> AnswerOf:
        # The incident's timeline as it stands when the question is answered,
        # read only for a question - the one meaning that needs it.
        def answered(question: str) -> str | None:
            with connections() as conn:
                story = build_narration(events.get_by_incident(conn, incident_id))

            return answer(question, story,
                          build_llm_client(Replay(incident_id, recorder), policy=policy))

        return answered

    def status_of(incident_id: str) -> IncidentStatus | None:
        with connections() as conn:
            incident = incidents.get(conn, incident_id)

        return incident.status if incident is not None else None

    def understand_one(written: ThreadMessage) -> None:
        understand(written,
                   meaning_of=meaning_of(written.incident_id),
                   answer_of=answer_of(written.incident_id),
                   status_of=status_of,
                   person_named=person_named,
                   record=record,
                   publisher=publisher)

    return understand_one


def main() -> None:
    """The process itself: a pool, a model, a chat platform, then watch
    until killed.

    An intent agent with no chat platform is not started at all: nothing would
    ever be written for it to understand, and a process idling on a record it
    can never act on is a process somebody has to wonder about.
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
                _not_understood(connections),
                _understanding(connections,
                               ModelPolicy(model=settings.intent_model,
                                           effort=settings.intent_effort),
                               platform.person_named),
                pause=settings.intent_poll_seconds
            )


if __name__ == "__main__":
    main()
