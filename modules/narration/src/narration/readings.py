"""What came of reading a channel that left nothing to list, in the words every
place showing it uses."""

from __future__ import annotations

from collections.abc import Collection
from typing import Final

from core.models import ChangeKind, ChannelReading

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
