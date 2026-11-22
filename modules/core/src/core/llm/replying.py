"""What a model driving a loop is told before its next turn.

The results of what it asked for, with anything due riding on the last of them
- news from the thread, a warning that this is its last turn - since that is
the condition the whole reply is to be read under, not a thing apart. A turn
that asked for nothing still has to be answered, or the conversation holds two
turns from the model in a row and no thread to continue; the agent says in
words of its own what such a turn is told, and the postscript rides on that.
"""

from __future__ import annotations

from core.models.transcript import Ask, Exchange, ToolResult, ToolResults


def told_next(results: list[ToolResult], postscript: str, /, *, nothing_asked: str) -> Exchange:
    """`results` with `postscript` on the last of them - or, where the turn
    asked for nothing, `nothing_asked` with `postscript` on it."""
    if not results:
        return Ask(text=nothing_asked + postscript)

    last = results[-1]

    return ToolResults(results=[
        *results[:-1],
        ToolResult(call_id=last.call_id, content=last.content + postscript, failed=last.failed)
    ])
