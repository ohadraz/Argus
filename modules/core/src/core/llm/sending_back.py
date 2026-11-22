"""A submission sent back through its own call's result.

A model that answered with a tool call is answered by that call's result, so an
answer sent back goes there: the model sees what it submitted and why it came
back. It is also the only shape a provider takes after a call - one result for
every call the turn made, together - so a turn that submitted twice is sent
back for both. The words are the caller's; the shape is said once here.
"""

from __future__ import annotations

from core.models.transcript import ToolResult, ToolResults, Transcript
from core.models.turn import Turn


def sent_back(asked: Transcript, submitted: Turn, why: str, /) -> Transcript:
    """The conversation so far, the turn that submitted, and `why` as the
    failed result of every call it made."""
    return [
        *asked,
        submitted,
        ToolResults(results=[ToolResult(call_id=call.id, content=why, failed=True)
                             for call in submitted.tool_calls])
    ]
