"""What an investigation retrieved, as a fact it can hand on.

One entry per channel-and-window actually served. Two things read it, and
neither is the model: the dispatcher, which refuses a window it has already
read, and a later round, which is told what the round before it saw so it does
not pay again for the same evidence.

It also keeps "never asked" distinguishable from "asked and came back empty".
Those look identical on an incident record that only carries what was found,
and they mean opposite things about the investigation.
"""

from __future__ import annotations

from dataclasses import dataclass

from argus_core.events import RetrievalChannel


@dataclass(frozen=True)
class Reading:
    """One retrieval that was served: which channel, over which window.

    Frozen, so that a record of what happened cannot be edited after the fact,
    and compared by value, which is what makes "have I read this already" a
    question the dispatcher can answer with `in`.

    Both bounds are optional because one channel has no window to name: the
    metrics span belongs to the metrics source, and what identifies that
    reading is the anchor it was taken around.
    """

    channel: RetrievalChannel
    window_start: str | None = None
    window_end: str | None = None

    def __str__(self) -> str:
        """How a reading is put to the model - as prose, not as a repr.

        It appears in the opening message of a later round, where everything
        else is written in sentences, and `Reading(channel=...)` in the middle
        of one would be Argus showing the model its own data structures.
        """
        if self.window_start is None and self.window_end is None:
            return f"{self.channel}"

        return (
            f"{self.channel} from {self.window_start or 'the start'} "
            f"to {self.window_end or 'the end'}"
        )
