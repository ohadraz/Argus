"""The process that understands what people wrote in incidents' threads.

It does one thing in a loop: ask the incident record for the messages nobody has
understood yet, understand each, oldest first, and ask again. Nothing calls it
and it calls nothing in the walk - the two share a table and no code, as the
relay and the walk do.

It finds its work on the record rather than by following the event log: a
message is the Intent Reader's to understand until the record says what it meant, and
an account that could decide what is done would be a participant
(`core.events`).

A process of its own rather than a part of the worker or the web: the worker
walks incidents for minutes at a time and a message is not a walk, and the web
answers the chat platform within three seconds, which a model does not.

The process - its pool, the model provider, the chat platform - is built by its
root, `apps.intent_reader`, and handed to `watch` as ports.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from functools import partial
from typing import Final

from core.llm import LLMClient
from core.models import (
    IncidentStatus,
    ThreadMessage,
)
from core.replay import Replay
from incident_record import (
    calls_into,
    events_into,
    incident_conversation_over,
    incident_reads_over,
)
from narration import build_narration
from postgres import Connections

from message_intent.answering import answer
from message_intent.classifying import classify
from message_intent.understanding import AnswerOf, MeaningOf, understand

logger = logging.getLogger(__name__)

# How many messages one look asks for: a few looks to catch up after a
# restart, never an hour of messages in memory at once.
_A_BATCH: Final = 100

# Up to so many messages nobody has understood, oldest first.
type NotUnderstood = Callable[[int], list[ThreadMessage]]
# Understanding one message a person wrote: classifying it, and offering what
# it calls for.
type Understand = Callable[[ThreadMessage], None]
# A client for one incident's calls, recording into that incident's replay log.
type ModelFor = Callable[[Replay], LLMClient]


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


def _not_understood(connections: Connections) -> NotUnderstood:
    """What a look asks, wired to the record."""
    return incident_conversation_over(connections).not_understood


def _understanding(connections: Connections,
                   model_for: ModelFor,
                   person_named: Callable[[str], str | None]) -> Understand:
    """What understanding one message is, wired to the database, the model and
    the chat platform this process holds."""
    recorder = calls_into(connections)
    publisher = events_into(connections)
    record = incident_conversation_over(connections)
    reads = incident_reads_over(connections)

    # Where a message was written is the platform its reference is filed under -
    # the name the chat platform's adapter gave it, which is the name a person
    # knows it by - so the model is told the platform the person used, as a
    # postmortem is told where a report came from, and nothing here names one.
    def meaning_of(incident_id: str, platform: str) -> MeaningOf:
        # A client per message, recording into that incident's replay log, as
        # the postmortem's is built per incident.
        return partial(classify,
                       llm=model_for(Replay(incident_id, recorder)),
                       platform=platform)

    def answer_of(incident_id: str, platform: str) -> AnswerOf:
        # The incident's timeline as it stands when the question is answered,
        # read only for a question - the one meaning that needs it.
        def answered(question: str) -> str | None:
            story = build_narration(reads.account(incident_id))

            return answer(question, story,
                          model_for(Replay(incident_id, recorder)),
                          platform=platform)

        return answered

    def status_of(incident_id: str) -> IncidentStatus | None:
        incident = reads.incident(incident_id)

        return incident.status if incident is not None else None

    def understand_one(written: ThreadMessage) -> None:
        understand(written,
                   meaning_of=meaning_of(written.incident_id, written.message.source),
                   answer_of=answer_of(written.incident_id, written.message.source),
                   status_of=status_of,
                   person_named=person_named,
                   record=record,
                   publisher=publisher)

    return understand_one


def watch(connections: Connections,
          model_for: ModelFor,
          person_named: Callable[[str], str | None],
          *,
          pause: float) -> None:
    """Understands what people write in incidents' threads for as long as the
    process lives, over the connections, the model and the chat platform its
    root holds.

    `model_for` is a client per incident over the process's provider, under
    the Intent Reader's own model and effort; `person_named` is the chat
    platform's answer to what a person is called.
    """
    watch_forever(_not_understood(connections),
                  _understanding(connections, model_for, person_named),
                  pause=pause)
