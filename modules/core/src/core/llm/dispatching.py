"""A tool call served by the handler its tool's name picks.

What a handler does with a call, and what a call to a tool nobody serves is
told, are the agent's: one answers a channel nobody has with the list of those
it has, another says only that there is no such tool. Picking the handler by
name is said once here.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

from core.models.turn import ToolCall


def served_by_name[R](call: ToolCall,
                      handlers: Mapping[str, Callable[[ToolCall], R]],
                      /,
                      *,
                      unknown: Callable[[ToolCall], R]) -> R:
    """What the handler named by the call's tool makes of it - or `unknown`'s
    answer, where no handler has that name."""
    handler = handlers.get(call.name)

    return unknown(call) if handler is None else handler(call)
