"""A person's question, answered from the incident's record - asked once, and
once more.

The model is given the question exactly as written and the incident's timeline,
one line per event, as the page and the thread say it, and nothing else. It is
held to that: an answer the record does not support is worse than none,
because the person reading it has no way to tell. Saying the record is silent
is an answer.

The answer is the one field of a tool the model must call, so a reply is never
parsed out of prose. An answer that cannot be used - prose, a blank, no answer
at all - is asked for once more, and after that there is none, for
`classifying`'s reason: the intent agent takes every message in order. What the
person is then told is `understanding`'s to say.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from argus_core import to_iso
from argus_core.llm import LLMClient, ModelDidNotAnswer
from argus_core.models import Ask, ToolDefinition, Transcript, Turn
from argus_narration import NarrationLine

# The tool's name and its one field, named once: the definition offered to the
# model and the reading of its call both use them.
ANSWER_TOOL_NAME: Final = "submit_answer"
ANSWER_FIELD: Final = "answer"

SUBMIT_ANSWER = ToolDefinition(
    name=ANSWER_TOOL_NAME,
    description="Submit your answer to the person's question about the incident.",
    properties={
        ANSWER_FIELD: {
            "type": "string",
            "description": (
                "The answer, as it will be posted in the thread: a few plain "
                "sentences, addressed to the person who asked."
            )
        }
    },
    required=[ANSWER_FIELD]
)

# How many times the model is asked about one question.
_ATTEMPTS: Final = 2


def answer(question: str, story: Sequence[NarrationLine], llm: LLMClient) -> str | None:
    """The answer to `question` from the incident's timeline, or `None` where
    the model gave no usable answer twice."""
    for _ in range(_ATTEMPTS):
        try:
            answered = _the_answer_in(llm.converse(_the_opening(question, story),
                                                   [SUBMIT_ANSWER]))
        except ModelDidNotAnswer:
            answered = None

        if answered is not None:
            return answered

    return None


def _the_opening(question: str, story: Sequence[NarrationLine]) -> Transcript:
    """The question, the timeline, and what the answer may rest on, in one
    message."""
    return [Ask(text="\n".join([
        "A person asked this in the Slack thread of an incident Argus is "
        "responding to:",
        "",
        question,
        "",
        "This is everything Argus has recorded about the incident, oldest first:",
        "",
        *(f"- {to_iso(line.at)} {line.who}: {line.text}" for line in story),
        "",
        "Answer only from these lines. Where they do not hold the answer, say "
        "that the record does not say, rather than guessing. Do not say Argus "
        "will do anything; answer what happened.",
        "",
        f"Call {ANSWER_TOOL_NAME} with your answer."
    ]))]


def _the_answer_in(turn: Turn) -> str | None:
    """The answer the turn submitted, or `None` where it submitted none, or
    one with nothing in it."""
    for call in turn.tool_calls:
        if call.name == ANSWER_TOOL_NAME:
            submitted = call.arguments.get(ANSWER_FIELD)

            return submitted.strip() if isinstance(submitted, str) and submitted.strip() else None

    return None
