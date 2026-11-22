"""A stand-in for the asking, and the turns and model it is used with.

Both of the intent reader's questions are asked through `core.llm`'s
`ask_until_answered`, handed in as a seam. What each suite holds is what it
hands the asking - the model, the question, the tool, the reader and how many
times - so the stand-in keeps exactly that, and answers as the case says.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import NamedTuple

from argus_testkit import Kept
from core.llm import AsksUntilAnswered, LLMClient
from core.models import ToolDefinition, Transcript, Turn


class Asked[T](NamedTuple):
    """What the asking was handed."""

    llm: LLMClient
    transcript: Transcript
    tools: list[ToolDefinition]
    read: Callable[[Turn], T | None]
    attempts: int


def an_asking[T](*, answering: T | None,
                 keeping: Kept[Asked[T]] | None = None) -> AsksUntilAnswered[T]:
    """An asking that keeps what it was handed and answers `answering`."""
    def ask(llm: LLMClient, transcript: Transcript, tools: list[ToolDefinition],
            read: Callable[[Turn], T | None], /, *, attempts: int) -> T | None:
        if keeping is not None:
            keeping.take(Asked(llm, transcript, tools, read, attempts))

        return answering

    return ask


def a_model_never_asked() -> LLMClient:
    """The model handed to the asking, which the code under test must never
    ask itself."""
    class NeverAsked:
        def converse(self,
                     transcript: Transcript,
                     tools: list[ToolDefinition],
                     max_tokens: int | None = None) -> Turn:
            raise AssertionError("The model is asked through the asking, never directly.")

    return NeverAsked()


def a_reply_in_prose() -> Turn:
    """A turn that answered in words and called nothing."""
    dont_care_prose = "dont-care prose"
    dont_care_tokens = 0

    return Turn(text=dont_care_prose, tool_calls=[], input_tokens=dont_care_tokens,
                output_tokens=dont_care_tokens)
