"""Asking a model something, and the ways that can fail to be an answer.

One client interface, one port a process hands its chosen provider through,
and a set of failures named separately because they are not the same event: a
model that refused, one that was cut off mid-answer, and one that never spoke
each leave the caller somewhere different, and a single exception would make
every caller guess which had happened.

The vendor lives outside the kernel, in `llm_anthropic`. What a caller names is
`LLMClient`, and what a composition root hands out is a `ModelProvider`;
which SDK answers is decided by whoever builds that provider, in a process's
root (`apps`) and nowhere else.
"""

from core.llm.building import build_llm_client
from core.llm.client import (
    AnswerTruncated,
    ClientFor,
    Conversation,
    LLMClient,
    ModelDidNotAnswer,
    ModelProvider,
    ModelRefused,
    ModelUnavailable,
    RequestRejected,
    TurnPaused,
)
from core.llm.conversing import Conversations, conversations_through
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
    "ModelProvider",
    "ModelRefused",
    "ModelUnavailable",
    "RecordedLLMClient",
    "RequestRejected",
    "TracedLLMClient",
    "TurnPaused",
    "build_llm_client",
    "conversations_through",
    "on_one_line",
    "with_escapes_resolved"
]
