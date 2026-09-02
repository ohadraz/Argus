from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from argus_core.llm.client import LLMClient
from argus_core.models.tool_definition import ToolDefinition
from argus_core.models.transcript import Transcript
from argus_core.models.turn import Turn
from argus_core.replay import CallType, Replay

"""An `LLMClient` that keeps a receipt for every call it passes on.

A decorator rather than instrumentation inside the adapter, for two reasons.
The adapter's job is talking to Anthropic, and a second job in it would be a
second reason to change it. And wrapping the `LLMClient` *Protocol* rather than
the Anthropic class records whatever client this deployment is configured with,
including one that does not exist yet.

What it writes down is Argus's own shapes - a transcript in, a turn out - and
not the wire's. That is the level a replay is wanted at: an eval re-reads what
the model was asked and what it answered, and the JSON the SDK happened to
serialise is neither more truthful nor more useful for that. It is also the
only level available here, which is the same fact from the other side: this
wraps a Protocol, and the Protocol deals in `Transcript` and `Turn`.

Nothing about the call changes. The answer is handed back as it arrived, a
failure is re-raised as it was thrown, and a recorder having a bad day is
invisible to everyone above - `Replay` swallows that, as narration does.
"""

# Reading the clock, so a test can hand over one that does not tick. A
# `Callable` rather than a Protocol because it takes no arguments: there are no
# keywords to name and nothing for `create_autospec` to get wrong.
Clock = Callable[[], float]

_MILLISECONDS_PER_SECOND = 1000


class RecordedLLMClient:
    """Wraps an `LLMClient`, writing down what passed through it.

    `target` is supplied rather than asked of the client, because the Protocol
    has no model to ask for - and it should not grow one. What Argus is
    configured to call is deployment knowledge, held where the client is built.

    A monotonic clock by default, not a wall clock: what is being measured is a
    duration, and a wall clock can step sideways mid-call and record a model
    that answered before it was asked.
    """

    def __init__(self,
                 client: LLMClient,
                 replay: Replay,
                 target: str,
                 clock: Clock = time.monotonic) -> None:
        self._client = client
        self._replay = replay
        self._target = target
        self._clock = clock

    def converse(self,
                 transcript: Transcript,
                 tools: list[ToolDefinition],
                 max_tokens: int = 16000) -> Turn:
        """Takes one turn through the wrapped client, and writes down the turn.

        The transcript is recorded as it stood when the call was made, tools
        included. Both are needed to stand in for the call: a turn read back
        without the conversation that produced it is an answer to a question
        nobody kept, and without the tools it is an answer whose options are
        unknown.
        """
        started_at = self._clock()
        asked = {
            "transcript": [exchange.model_dump(mode="json") for exchange in transcript],
            "tools": [tool.model_dump(mode="json") for tool in tools],
            "max_tokens": max_tokens
        }

        try:
            turn = self._client.converse(transcript, tools, max_tokens)
        except Exception as error:
            self._record(request=asked, response=_what_went_wrong(error), since=started_at)
            raise

        self._record(request=asked, response=turn.model_dump(mode="json"), since=started_at)

        return turn

    def _record(self,
                request: dict[str, Any],
                response: dict[str, Any],
                since: float) -> None:
        """Writes one call down, timed from `since` to now.

        The duration is computed here rather than at each call site so that
        every entry measures the same span - the whole call, including whatever
        the adapter did around it, which is what a later reader comparing two
        runs is entitled to assume.
        """
        self._replay.record(
            call_type=CallType.LLM,
            target=self._target,
            request=request,
            response=response,
            latency_ms=int((self._clock() - since) * _MILLISECONDS_PER_SECOND)
        )


def _what_went_wrong(error: Exception) -> dict[str, Any]:
    """A call that produced no answer, as the record of it.

    The type is named rather than only the message. Which of the ways a model
    can fail to answer this was is what a reader acts on - a refusal and a
    truncated turn call for different things - and the wording belongs to
    whoever raised it and may be reworded tomorrow.

    Recorded at all, rather than skipped, because these are the calls most
    worth a receipt: a refusal is charged for and a truncation spends the wall
    clock for nothing, and a log holding only the answers that arrived leaves
    exactly the expensive runs unexplained.
    """
    return {"error": type(error).__name__, "detail": str(error)}
