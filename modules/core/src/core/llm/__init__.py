"""Asking a model something, and the ways that can fail to be an answer.

One client interface, one place to choose which implementation stands behind it,
and a set of failures named separately because they are not the same event: a
model that refused, one that was cut off mid-answer, and one that never spoke
each leave the caller somewhere different, and a single exception would make
every caller guess which had happened.

The vendor lives behind `adapters/` and is not exported. What a caller names is
`LLMClient`; which SDK answers it is the composition root's business.
"""

from core.llm.building import build_llm_client
from core.llm.client import (
    AnswerTruncated,
    ClientFor,
    Conversation,
    LLMClient,
    ModelDidNotAnswer,
    ModelRefused,
    ModelUnavailable,
    RequestRejected,
    TurnPaused,
)
from core.llm.conversing import Conversations, a_conversation_recorded_for
from core.llm.escapes import with_escapes_resolved
from core.llm.line_breaks import on_one_line
from core.llm.recorded_client import RecordedLLMClient
from core.llm.traced_client import TracedLLMClient

__all__ = [
    "AnswerTruncated",
    "ClientFor",
    "Conversation",
    "Conversations",
    "LLMClient",
    "ModelDidNotAnswer",
    "ModelRefused",
    "ModelUnavailable",
    "RecordedLLMClient",
    "RequestRejected",
    "TracedLLMClient",
    "TurnPaused",
    "a_conversation_recorded_for",
    "build_llm_client",
    "on_one_line",
    "with_escapes_resolved"
]
