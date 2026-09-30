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

from argus_core.models import Reading, ToolCall, ToolResult


class Unanswered(NamedTuple):
    """A channel that was asked and would not answer, said for the page.

    Carried beside the model's own text rather than derived from it, because the
    two are written for different readers and only one of them is short. The
    model is told what it now does not know and what to do about it; a person
    reading the incident wants the subject and the reason, and a line rendered
    out of the model's paragraph would put a tool's advice on the timeline.
    """

    what_was_asked: str
    because: str


class Served(NamedTuple):
    """What one call produced: the model's answer, and what it cost to read.

    `reading` is `None` whenever nothing was retrieved - a window that could
    not be read, a tool that does not exist, a repeat that was refused. A
    reading recorded for a call that read nothing would tell a later round it
    already has evidence nobody ever fetched.

    `unanswered` is set only where the channel itself would not answer, which is
    the one kind of failed call that is a gap in what Argus knows rather than
    something the model did. It is carried here rather than published where it
    happens so that one place decides - the dispatcher every call passes through
    - and a channel added later cannot arrive silent.
    """

    result: ToolResult
    reading: Reading | None
    unanswered: Unanswered | None = None


def served(call: ToolCall, content: str, reading: Reading) -> Served:
    """What the call asked for, as evidence about the incident."""
    return Served(ToolResult(call_id=call.id, content=content), reading)


def answered(call: ToolCall, content: str) -> Served:
    """What the call asked for, where what it asked for has no window.

    Beside `served` rather than folded into it with an optional reading, because
    the two are different claims and only one of them is about time. `served`
    says a stretch of minutes was read and records which; this says a question
    was answered that has no minutes to record - what a service calls is a fact
    about how it is built.

    An optional `reading` on `served` would make the windowless case look like a
    windowed one somebody forgot to fill in, and a channel that genuinely forgot
    would then be indistinguishable from this.
    """
    return Served(ToolResult(call_id=call.id, content=content), reading=None)


def could_not_serve(call: ToolCall, why: str) -> Served:
    """A call that was not served, answered anyway.

    `failed` is what tells the model this is something to recover from rather
    than evidence about the incident - without it, "there is no tool called
    that" reads as a finding about the service.

    A result rather than an exception because the investigation has already
    paid for everything it read before this call, and an inverted window is the
    model's mistake to correct on its next turn, not the end of the
    investigation.

    This one is for the calls that went wrong in the asking - a tool nobody
    offers, a window that ends before it starts, a window already read. Nothing
    was asked of any channel, so nothing is said about one: an account naming a
    channel that would not answer, where all that happened was a model
    misreading its own tool list, sends a person looking for an outage in
    Argus's plumbing. A channel that *was* asked and refused is
    `could_not_be_read`.
    """
    return Served(ToolResult(call_id=call.id, content=why, failed=True), reading=None)


def could_not_be_read(call: ToolCall,
                      why: str,
                      what_was_asked: str,
                      because: str) -> Served:
    """A channel that was asked and would not answer - told twice, to two readers.

    Beside `could_not_serve` rather than a flag on it, because the two are
    opposite claims that arrive identically. Both come back failed and both are
    something the model goes on from; only this one means the service could not
    be looked at, and a single constructor covering both would publish the
    model's own mistakes as gaps in the evidence.

    `why` is the model's text and says what it now does not know, at whatever
    length that takes. `what_was_asked` and `because` are the page's, and stay
    apart for the reason `RememberingFailed` keeps its refusal apart: a read that
    timed out and one that was refused are fixed by different people.
    """
    return Served(
        ToolResult(call_id=call.id, content=why, failed=True),
        reading=None,
        unanswered=Unanswered(what_was_asked, because)
    )


def was_already_read(reading: Reading, readings: Sequence[Reading]) -> bool:
    """Whether this exact retrieval has been served in this investigation.

    Exact, and deliberately not "overlapping". A window that merely overlaps
    one already read still contains minutes the model has not seen, and
    refusing it would be the loop deciding what is worth reading again - which
    is the decision this whole change hands to the model.
    """
    return reading in readings
