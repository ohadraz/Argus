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

from core.llm.asking import AsksUntilAnswered, ask_until_answered
from core.llm.building import build_llm_client
from core.llm.calls import the_call, the_calls
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
from core.llm.dispatching import served_by_name
from core.llm.escapes import with_escapes_resolved
from core.llm.line_breaks import on_one_line
from core.llm.recorded_client import RecordedLLMClient
from core.llm.replying import told_next
from core.llm.sending_back import sent_back
from core.llm.traced_client import TracedLLMClient
from core.llm.turns import Ended, TurnPolicy, converse_until

__all__ = [
    "AnswerTruncated",
    "AsksUntilAnswered",
    "ClientFor",
    "Conversation",
    "Conversations",
    "Ended",
    "LLMClient",
    "ModelDidNotAnswer",
    "ModelProvider",
    "ModelRefused",
    "ModelUnavailable",
    "RecordedLLMClient",
    "RequestRejected",
    "TracedLLMClient",
    "TurnPaused",
    "TurnPolicy",
    "ask_until_answered",
    "build_llm_client",
    "conversations_through",
    "converse_until",
    "on_one_line",
    "sent_back",
    "served_by_name",
    "the_call",
    "the_calls",
    "told_next",
    "with_escapes_resolved"
]
