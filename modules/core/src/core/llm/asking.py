"""One question put to a model until it gives a usable answer, or a set number
of times.

What counts as usable is the caller's - it is handed in as `read` - and so are
the question and the tools. What is said once here is the loop: the same
question each time, word for word, since a retry that changed the asking would
be a different question; a turn with no answer in it (a refusal, a truncated
answer, a paused turn) asked again as an unusable one; and a provider that
could not be reached, or a request it would not take, let through, since
neither is an answer to anything.
"""

from __future__ import annotations

from collections.abc import Callable

from core.llm.client import LLMClient, ModelDidNotAnswer
from core.models.tool_definition import ToolDefinition
from core.models.transcript import Transcript
from core.models.turn import Turn


def ask_until_answered[T](llm: LLMClient,
                          transcript: Transcript,
                          tools: list[ToolDefinition],
                          read: Callable[[Turn], T | None],
                          /,
                          *,
                          attempts: int) -> T | None:
    """The first usable answer `read` finds in the model's turn, asking
    `transcript` with `tools` up to `attempts` times - or `None` where no
    attempt gave one."""
    for _ in range(attempts):
        try:
            answered = read(llm.converse(transcript, tools))
        except ModelDidNotAnswer:
            answered = None

        if answered is not None:
            return answered

    return None
