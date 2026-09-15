"""How Code-Fix talks to the model.

The same seam the investigation has, for the same reasons: one call, so a test
can stand it in with a scripted conversation, and a real client built on first
use so a module that only ever injects a double pays for neither the vendor's
SDK nor the configuration it reads on the way up.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import lru_cache

from argus_core.llm import LLMClient
from argus_core.models import ToolDefinition, Transcript, Turn

Conversation = Callable[[Transcript, list[ToolDefinition]], Turn]


@lru_cache(maxsize=1)
def _llm_client() -> LLMClient:
    """The one client the whole process shares.

    Built on first use rather than at import, and the import deferred with it -
    building a client pulls in a vendor's SDK, and every unit test of the loop
    injects a conversation and never reaches here.
    """
    from argus_core.llm import build_llm_client

    return build_llm_client()


def converse(transcript: Transcript, tools: list[ToolDefinition]) -> Turn:
    """Hands the model the conversation so far and asks what it wants next.

    A module-level function rather than the client object, so the loop's seam
    is one call and a test can `create_autospec` it against a real public name.

    Usually the answer is not the answer: a turn is whatever the model wants
    next - a file to read, a remark, or the one call that ends the work - and
    which of those it is, is the loop's to read rather than this seam's to
    interpret.
    """
    return _llm_client().converse(transcript, tools)
