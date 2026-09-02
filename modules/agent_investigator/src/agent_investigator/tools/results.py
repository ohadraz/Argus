"""How a channel answers the call it was made for - served, or not.

Two functions rather than a `ToolResult` built at each channel, because the
one thing every result must carry is the id of the call it answers: a result
sent without it, or with the wrong one, answers nothing and leaves the model
waiting for a reply it will never recognise. Attaching it in one place is what
stops a new channel from forgetting.

Each answer carries the reading it made, or none. The dispatcher keeps those,
and a channel that computed its own window - which is every channel, since the
defaults live with them - is the only thing that knows what was actually read.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import NamedTuple

from argus_core.models.reading import Reading
from argus_core.models.transcript import ToolResult
from argus_core.models.turn import ToolCall


class Served(NamedTuple):
    """What one call produced: the model's answer, and what it cost to read.

    `reading` is `None` whenever nothing was retrieved - a window that could
    not be read, a tool that does not exist, a repeat that was refused. A
    reading recorded for a call that read nothing would tell a later round it
    already has evidence nobody ever fetched.
    """

    result: ToolResult
    reading: Reading | None


def served(call: ToolCall, content: str, reading: Reading) -> Served:
    """What the call asked for, as evidence about the incident."""
    return Served(ToolResult(call_id=call.id, content=content), reading)


def could_not_serve(call: ToolCall, why: str) -> Served:
    """A call that was not served, answered anyway.

    `failed` is what tells the model this is something to recover from rather
    than evidence about the incident - without it, "there is no tool called
    that" reads as a finding about the service.

    A result rather than an exception because the investigation has already
    paid for everything it read before this call, and an inverted window is the
    model's mistake to correct on its next turn, not the end of the
    investigation.
    """
    return Served(ToolResult(call_id=call.id, content=why, failed=True), reading=None)


def was_already_read(reading: Reading, readings: Sequence[Reading]) -> bool:
    """Whether this exact retrieval has been served in this investigation.

    Exact, and deliberately not "overlapping". A window that merely overlaps
    one already read still contains minutes the model has not seen, and
    refusing it would be the loop deciding what is worth reading again - which
    is the decision this whole change hands to the model.
    """
    return reading in readings
