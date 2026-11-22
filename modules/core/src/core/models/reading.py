"""What an investigation retrieved, as a fact it can hand on - and the channels
it could have retrieved it from.

The channel lives here rather than with the events because it is a domain value
before it is anything a publisher says: a reading is a channel and a window, and
an enum defined in the event vocabulary would make every model that names one
import the event stream to do it.

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
from enum import StrEnum


class RetrievalChannel(StrEnum):
    """The three ways Argus learns anything about the service (spec §16).

    Named on the request so a reader can see what was asked for even where the
    answer never arrived - a channel that failed is a fact about the
    investigation, and one that is silent in the account looks like a channel
    nobody thought to try.
    """

    METRICS = "metrics"
    LOGS = "logs"
    CHANGES = "changes"


class ChannelReading(StrEnum):
    """What came of reading one channel over a whole incident - said where it
    left nothing to show, since an empty list cannot say which of these it is.

    Asked for with no answer, rather than refused: a request with no reading
    after it is a source that failed or a walk stopped mid-read, and the record
    does not say which. Only changes made since Argus first acted is the flag
    history's alone - a second attempt reads back the toggle the first one made,
    and nothing from once the walk acted is listed, so the read found something
    and shows nothing. Said by when, not by whom: the cut is by time, and a
    person's toggle in those minutes is cut with Argus's.
    """

    READ = "read"
    ONLY_SINCE_ARGUS_ACTED = "only_since_argus_acted"
    NOT_ASKED = "not_asked"
    UNANSWERED = "unanswered"


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
