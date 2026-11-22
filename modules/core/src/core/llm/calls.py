"""The calls a turn made to one tool, found by the tool's name.

Every loop that drives a model reads its turn this way - did it call the tool
that answers, and with what - and each used to spell the lookup itself. Said
once here, so a caller says which tool it wants and nothing about how a turn
holds its calls.
"""

from __future__ import annotations

from core.models.turn import ToolCall, Turn


def the_call(turn: Turn, name: str, /) -> ToolCall | None:
    """The first call the turn made to the tool named, or `None` where it
    made none.

    The first, because that is the one every caller already read. Two calls
    to one tool do not say which is the answer, so a caller for whom that
    matters refuses the turn, as the postmortem's checks do.
    """
    return next((call for call in turn.tool_calls if call.name == name), None)


def the_calls(turn: Turn, name: str, /) -> list[ToolCall]:
    """Every call the turn made to the tool named, in the order it made them."""
    return [call for call in turn.tool_calls if call.name == name]
