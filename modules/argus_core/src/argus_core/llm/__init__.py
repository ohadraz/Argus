"""Asking a model something, and the ways that can fail to be an answer.

One client interface, one place to choose which implementation stands behind it,
and a set of failures named separately because they are not the same event: a
model that refused, one that was cut off mid-answer, and one that never spoke
each leave the caller somewhere different, and a single exception would make
every caller guess which had happened.

The vendor lives behind `adapters/` and is not exported. What a caller names is
`LLMClient`; which SDK answers it is the composition root's business.
"""

from argus_core.llm.building import build_llm_client
from argus_core.llm.client import (
    AnswerTruncated,
    ClientFor,
    LLMClient,
    ModelDidNotAnswer,
    ModelRefused,
    TurnPaused,
)
from argus_core.llm.escapes import with_escapes_resolved
from argus_core.llm.line_breaks import on_one_line
from argus_core.llm.recorded_client import RecordedLLMClient

__all__ = [
    "AnswerTruncated",
    "ClientFor",
    "LLMClient",
    "ModelDidNotAnswer",
    "ModelRefused",
    "RecordedLLMClient",
    "TurnPaused",
    "build_llm_client",
    "on_one_line",
    "with_escapes_resolved"
]
