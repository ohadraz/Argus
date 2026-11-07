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

from collections.abc import Collection
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from argus_core.models.change_event import ChangeKind


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


# Said in place of the log messages, by what came of reading them.
_NO_LOG_MESSAGES: Final[dict[ChannelReading, str]] = {
    ChannelReading.READ: "Read; none came back.",
    ChannelReading.ONLY_SINCE_ARGUS_ACTED: "Read; none came back.",
    ChannelReading.NOT_ASKED: "Not read.",
    ChannelReading.UNANSWERED: "Asked for; no answer came back."
}

# What came of reading one kind of change, as a clause after its name.
_HOW_A_KIND_WAS_READ: Final[dict[ChannelReading, str]] = {
    ChannelReading.READ: "read, none came back",
    ChannelReading.ONLY_SINCE_ARGUS_ACTED:
        "read, only changes made since Argus first acted came back",
    ChannelReading.NOT_ASKED: "not read",
    ChannelReading.UNANSWERED: "asked for, no answer came back"
}


def changes_not_listed(deploys: ChannelReading,
                       flags: ChannelReading,
                       listed: Collection[ChangeKind]) -> str | None:
    """What is said of each kind of change with no row listed: what came of
    reading it. Nothing where both kinds have rows.

    Each kind said apart, because the walk reads the flags every time and the
    deploys only when the investigation asks, so one word for both would say
    the deploys were read whenever the flags were. And said whatever the other
    kind holds, because a list of flag toggles says nothing of the deploys, and
    its reader takes them as read and ruled out when nobody asked for them.

    Here rather than with whoever shows it, because the page and the brief the
    model writes from both say it, and two spellings of one fact read as two
    facts.
    """
    unlisted = [f"{name} {_HOW_A_KIND_WAS_READ[reading]}"
                for kind, name, reading in ((ChangeKind.DEPLOY, "deploys", deploys),
                                            (ChangeKind.FLAG_TOGGLE, "flags", flags))
                if kind not in listed]
    if not unlisted:
        return None

    said = "; ".join(unlisted)
    return f"{said[0].upper()}{said[1:]}."


def no_logs_listed(reading: ChannelReading) -> str:
    """What is said where no log message is listed: what came of reading the
    logs - here for the reason `changes_not_listed` is."""
    return _NO_LOG_MESSAGES[reading]


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
