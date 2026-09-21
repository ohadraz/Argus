"""What stops an agent loop the model would happily continue.

In the kernel rather than beside either loop that keeps one. Two agents run a
conversation the model drives - the investigator choosing what to read, and
Code-Fix reading source until it can write a patch - and both need the same
three bounds for the same reasons. It was the investigator's alone while it
was the only one of the two that had any, and Code-Fix was bounded on turns
and nothing else: cheap in calls and ruinous in tokens is exactly the shape of
an agent whose answers are whole files.

A type two modules both name is a contract, and a contract kept inside one of
the parties is one the other has to reach into - which the layering forbids
outright, since no agent may know another. What stays behind is
`InvestigationSettings`: the numbers are each agent's own, and only the
arithmetic over them is shared.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from enum import StrEnum

from argus_core.models import Turn


class Bound(StrEnum):
    """One of the three ways an agent loop can run out.

    A closed set, and each member is reported to a human: "I ran out of time"
    and "I read everything I was allowed to and still could not tell" are
    different accounts of the same escalation, and an operator does different
    things about them.
    """

    TOOL_CALLS = "tool calls"
    TOKENS = "tokens"
    TIME = "time"


class Budget:
    """What stops an agent loop the model would happily continue.

    Three bounds, because they fail differently and none implies the others.
    A model reading three-hour windows is cheap in calls and ruinous in
    tokens; one looping on a narrow window is the reverse; and one that is
    frugal in both can still leave a human waiting past the point the answer
    was worth having. Bounding only the tool calls - the tempting single knob -
    bounds the least expensive of the three.

    Nothing here is expressed to the model. A bound it could ask to extend is
    not a bound, so every one of these is arithmetic the loop does on its own,
    between turns, whatever the model would prefer.

    `now` is a seam rather than a call to `time.monotonic` inside, because a
    test of the time bound would otherwise have to sleep for the duration it
    is checking. Monotonic rather than wall-clock: this measures an elapsed
    duration, and a clock adjustment mid-incident is not extra budget.
    """

    def __init__(self,
                 max_tool_calls: int,
                 max_tokens: int,
                 max_seconds: float,
                 now: Callable[[], float] = time.monotonic) -> None:
        self._max_tool_calls = max_tool_calls
        self._max_tokens = max_tokens
        self._max_seconds = max_seconds
        self._now = now
        self._started_at = now()
        self._tool_calls = 0
        self._tokens = 0

    def record(self, turn: Turn) -> None:
        """Charges one turn against the budget.

        Calls are counted rather than turns. A model may ask for several
        channels at once, so a budget counting turns would let it read twice
        what it was allowed and still look healthy.

        Tokens are counted in both directions. What the model was *sent* is
        most of the spend, because every turn resends the whole transcript -
        counting only what it wrote would under-report the expensive half.

        All four counts, not two. With caching on, `input_tokens` is only the
        uncached remainder and the rest of the prompt arrives as a cache read
        or a cache write, so a sum of the two plain counts charges a fraction
        of what was sent - measured against the recordings, between a sixth
        and an eighteenth of it - and understates it most where the caching
        worked best. This is the same arithmetic `get_tokens_spent` reports
        afterwards, and deliberately: a bound that stopped a run at one figure
        while a human was shown another would be two answers to what the
        incident cost.

        Counted rather than priced, which is why the cached counts are not
        discounted to what they bill. A rate is the vendor's to change and
        weighting by one would put today's prices in the enforcement path;
        worse, a weighting that discounted the cache but left the output
        counts alone would be wrong by the largest factor in the table while
        looking precise. What this bounds is how much the model read and
        wrote, and every one of these four is some of that.
        """
        self._tool_calls += len(turn.tool_calls)
        self._tokens += (
            turn.input_tokens
            + turn.output_tokens
            + turn.cache_read_tokens
            + turn.cache_write_tokens
        )

    def tokens_spent(self) -> int:
        """Every token charged so far, as a figure rather than as a verdict.

        The same arithmetic `get_tokens_spent` reports from the other side of
        the system, over the same four counts, and said here so that the two
        can be compared. A total readable only by moving a bound until it
        binds is a total nothing can be checked against - and the one thing
        this number has to be is in agreement with the one a human is shown.

        Separate from `bounds_reached` because the question differs. That asks
        whether to carry on, which is all a loop needs; this asks what has
        been spent, which is what a reader of the incident needs.
        """
        return self._tokens

    def bounds_reached(self) -> list[Bound]:
        """Every bound that has run out, in the order `Bound` declares them.

        All of them rather than the first noticed. Two bounds running out
        together is a different account of an incident than one, and a single
        winner would make what a human is told depend on the order these
        checks happen to be written in - which is not a fact about the run.

        Empty means the loop may carry on, which is the only thing it has to
        ask.
        """
        reached = []

        if self._tool_calls >= self._max_tool_calls:
            reached.append(Bound.TOOL_CALLS)

        if self._tokens >= self._max_tokens:
            reached.append(Bound.TOKENS)

        if self._elapsed() >= self._max_seconds:
            reached.append(Bound.TIME)

        return reached

    def is_on_its_last_call(self) -> bool:
        """Whether one more call is all that is left - so the model can be told.

        The warning is what lets a model spend what it has left answering from
        what it has already read, instead of asking for evidence it will never
        be shown. Without it, everything the run read is thrown away - as
        "no cause determined" by the investigator, and as "no fix proposed"
        by Code-Fix, which reads as a verdict on code nobody finished.

        Calls rather than turns, and named for what it measures. It is the one
        bound whose remaining room is *known*: how many tokens the next turn
        will cost, and how long it will take, are not knowable until it
        happens. A warning guessed from those would fire early or not at all,
        and a warning that fires every turn teaches the model to ignore it.

        What each agent calls it when it says it is each agent's own. A turn
        of an investigation is usually one call and is told it is on its last
        turn; Code-Fix reads several files in one and is told it is on its
        last call. Both are true of the same arithmetic.
        """
        return self._tool_calls >= self._max_tool_calls - 1

    def _elapsed(self) -> float:
        return self._now() - self._started_at
