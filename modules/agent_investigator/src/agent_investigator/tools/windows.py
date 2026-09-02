"""The window a retrieval call asks about - offered, read, and checked.

Shared by the two channels that take one, because a window means the same
thing to both: the model names either bound or neither, and what is wrong with
one it named is something it can fix on its next turn. What differs between
the channels is only the default and whether there is a ceiling, and both of
those stay with the channel they belong to.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Final

from argus_core.models.turn import ToolCall
from argus_core.timestamps import parse_iso, to_iso

# The arguments a windowed tool takes. Named once because the schema offers
# them and the dispatcher reads them back, and those two agreeing is the whole
# point of offering a strict schema.
WINDOW_START_ARG: Final = "window_start"
WINDOW_END_ARG: Final = "window_end"

# JSON Schema's own vocabulary, named here because this is one of the two
# modules that writes a schema fragment by hand.
_STRING_TYPE: Final = "string"

_A_TIMESTAMP = "An ISO-8601 instant, as the evidence writes them: 2026-08-29T22:15:00Z."


def window_properties() -> dict[str, Any]:
    """The two optional bounds, as a tool offers them.

    A function rather than a constant so each tool gets its own dictionary. A
    shared one would be a mutable object living in three tool definitions at
    once, and the day something edits it in place all three change.
    """
    return {
        WINDOW_START_ARG: {
            "type": _STRING_TYPE,
            "description": f"Where the window begins. {_A_TIMESTAMP}"
        },
        WINDOW_END_ARG: {
            "type": _STRING_TYPE,
            "description": f"Where the window ends. {_A_TIMESTAMP}"
        }
    }


def window_of(call: ToolCall,
              default_start: datetime,
              default_end: datetime) -> tuple[datetime, datetime] | str:
    """The window one call asks about, or what is wrong with the one it asked for.

    A string rather than an exception because the caller turns it straight into
    a failed result: what is wrong with a window is something the model can fix
    on its next turn, and the investigation has already paid for everything it
    read before this call.

    Either bound may be left out, and each defaults on its own. A model that
    names only where to start has said something real - read from here to
    wherever you would have stopped - and making it supply both would be asking
    it to restate an anchor it was already given.
    """
    requested_start = call.arguments.get(WINDOW_START_ARG)
    requested_end = call.arguments.get(WINDOW_END_ARG)

    try:
        start = parse_iso(requested_start) if requested_start else default_start
        end = parse_iso(requested_end) if requested_end else default_end
    except ValueError:
        return (
            f"{requested_start!r} and {requested_end!r} are not both ISO-8601 "
            f"instants, so the window could not be read. Write them as "
            f"2026-08-29T22:15:00Z."
        )

    if end <= start:
        return (
            f"the window {to_iso(start)} to {to_iso(end)} ends before it starts, "
            f"so nothing was read. Ask again with the earlier instant first."
        )

    return start, end
