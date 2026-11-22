"""What a person meant, as the model classifies it - asked once, and once more.

An answer that cannot be used - prose instead of a call, a call naming
something other than the five meanings, or no answer at all - is asked for
once more, and after that the message is left unclassified. Never more than
twice: the intent reader takes every message in order, and a message that is
never classified holds up every message behind it.

What an unclassified message counts as, and who is told, is `understanding`'s
to say: only it knows which incident and which message it was.
"""

from __future__ import annotations

from typing import Final

from core.llm import LLMClient, ModelDidNotAnswer, the_call
from core.models import Meaning, Turn

from message_intent.prompting import (
    MEANING_FIELD,
    SUBMIT_MEANING,
    SUBMIT_TOOL_NAME,
    opening_ask,
)

# How many times the model is asked about one message.
_ATTEMPTS: Final = 2


def classify(words: str, llm: LLMClient, *, platform: str) -> Meaning | None:
    """What the person meant by `words`, written on `platform` - the chat
    platform's name, as its adapter gives it - or `None` where the model gave no
    usable answer twice."""
    for _ in range(_ATTEMPTS):
        try:
            meaning = _the_meaning_in(llm.converse(opening_ask(words, platform),
                                                   [SUBMIT_MEANING]))
        except ModelDidNotAnswer:
            meaning = None

        if meaning is not None:
            return meaning

    return None


def _the_meaning_in(turn: Turn) -> Meaning | None:
    """The meaning the turn submitted, or `None` where it submitted none of the
    five."""
    submitting = the_call(turn, SUBMIT_TOOL_NAME)
    if submitting is None:
        return None

    submitted = submitting.arguments.get(MEANING_FIELD)

    return Meaning(submitted) if submitted in set(Meaning) else None
