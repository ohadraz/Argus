"""The loop an agent drives a model in, until its policy says it has ended.

The mechanism is said here once: whether to go on, whether the incident is
still wanted, asking the model, the two ways a turn can fail to arrive,
charging the turn and keeping it, and putting what the model is told next
after it. Everything else - what a turn means, what the model is told, the
tools it is offered, and every way the loop ends - is the agent's, in the
policy it hands in.

Whether to go on is asked before whether the incident is still wanted, so an
agent out of room and no longer wanted at once ends as out of room.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from core.budget import StillWanted
from core.llm.client import AnswerTruncated, Conversation, ModelRefused
from core.models.tool_definition import ToolDefinition
from core.models.transcript import Exchange
from core.models.turn import Turn


@dataclass(frozen=True)
class Ended[T]:
    """What a loop ends with, told apart from the next thing the model is
    told.

    A dataclass rather than a NamedTuple: a generic NamedTuple narrowed by
    `isinstance` comes back as `Ended[Any]`, and its value as `Any`."""

    value: T


class TurnPolicy[T](Protocol):
    """What one agent does at each point of the loop. An ending may be
    returned or raised: an agent whose endings are failures raises them."""

    def goes_on(self) -> bool:
        """Whether there is another turn to take, asked before each."""
        ...

    def stopped(self) -> T:
        """The ending where the incident is no longer wanted."""
        ...

    def tools(self) -> list[ToolDefinition]:
        """What the model is offered this turn."""
        ...

    def cut_short(self, cut_short: AnswerTruncated, /) -> T:
        """The ending where the model ran out of room for its answer."""
        ...

    def declined(self, declined: ModelRefused, /) -> T:
        """The ending where the model declined to answer."""
        ...

    def on_turn(self, turn: Turn, /) -> Ended[T] | Exchange:
        """The turn read: an ending, or what the model is told next."""
        ...

    def ran_out(self) -> T:
        """The ending where `goes_on` said there was no other turn."""
        ...


def converse_until[T](policy: TurnPolicy[T],
                      /,
                      *,
                      converse: Conversation,
                      transcript: list[Exchange],
                      record: Callable[[Turn], None],
                      still_wanted: StillWanted) -> T:
    """Drives the model through `policy` until one of its endings.

    `transcript` is the conversation so far, and is added to as it goes: each
    turn, then what the model is told next. `record` charges each turn, before
    the policy reads it. A turn that never arrived is charged nothing here:
    what a truncation was billed (`AnswerTruncated.billed`) is the policy's to
    charge, in its `cut_short`, or not.
    """
    while policy.goes_on():
        if not still_wanted():
            return policy.stopped()

        try:
            turn = converse(transcript, policy.tools())
        except AnswerTruncated as cut_short:
            return policy.cut_short(cut_short)
        except ModelRefused as declined:
            return policy.declined(declined)

        record(turn)
        transcript.append(turn)

        told = policy.on_turn(turn)
        if isinstance(told, Ended):
            return told.value

        transcript.append(told)

    return policy.ran_out()
