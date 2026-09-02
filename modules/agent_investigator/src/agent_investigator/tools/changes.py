"""The change channel: what changed on the service, over its own wide window.

No ceiling, deliberately. The log ceiling exists because log lines are
millions where changes are a handful, and applying it here would silence the
one channel that exists to reach past it - the lag between a change and the
symptoms it produces is unbounded.

A source that cannot be reached raises, and is meant to. It is the one
retrieval failure the model cannot recover from: "nothing changed" is a
conclusion something acts on, so a source that was never read must not arrive
looking like one that was read and found empty.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import timedelta
from typing import Final

from argus_core.config import get_settings
from argus_core.events import ChangesRetrieved, Narrator, RetrievalChannel, RetrievalRequested
from argus_core.models.reading import Reading
from argus_core.models.tool_definition import ToolDefinition
from argus_core.models.turn import ToolCall
from argus_core.timestamps import parse_iso, to_iso

from agent_investigator.retrieval import ChangeFetcher
from agent_investigator.tools.results import Served, could_not_serve, served, was_already_read
from agent_investigator.tools.windows import window_of, window_properties

CHANGES_TOOL: Final = "get_changes"

_NOTHING_IN_THIS_WINDOW = "(nothing changed in this window)"


def changes_tool() -> ToolDefinition:
    """The offer: read what changed, over a window the logs could not afford."""
    return ToolDefinition(
        name=CHANGES_TOOL,
        description=(
            "What changed on the service over one window - deploys and other "
            "recorded changes. Sparse where the logs are dense, so the window can be "
            "far wider. Defaults to a long lookback ending at the onset, because a "
            "change made after the incident began did not begin it."
        ),
        properties=window_properties(),
        required=[]
    )


def read_changes(call: ToolCall,
                 service: str,
                 onset: str,
                 fetch_change_events: ChangeFetcher,
                 already_read: Sequence[Reading],
                 narrator: Narrator) -> Served:
    """The changes on the service over the window the model named, or the
    default one.

    The default ends at the onset: a change made after the incident began did
    not begin it, and offering later ones invites attribution by mere
    proximity - which is the one mistake this channel is most likely to
    produce. It reaches back by the configured lookback rather than by anything
    the log window uses, because how far back a cause may plausibly lie is the
    operator's judgement, not something inferable from the metrics.
    """
    settings = get_settings()
    onset_at = parse_iso(onset)
    window = window_of(
        call,
        default_start=onset_at - timedelta(minutes=settings.change_lookback_minutes),
        default_end=onset_at
    )

    if isinstance(window, str):
        return could_not_serve(call, window)

    start, end = window
    reading = Reading(RetrievalChannel.CHANGES, to_iso(start), to_iso(end))
    if was_already_read(reading, already_read):
        return could_not_serve(call, (
            f"you already read the changes for {reading} in this investigation, and "
            f"nothing further would come back. Ask for a window you have not read, or "
            f"answer from what you have."
        ))

    narrator.say(
        RetrievalRequested,
        channel=RetrievalChannel.CHANGES,
        window_start=to_iso(start),
        window_end=to_iso(end)
    )
    changes = fetch_change_events(service, to_iso(start), to_iso(end))
    narrator.say(
        ChangesRetrieved,
        window_start=to_iso(start),
        window_end=to_iso(end),
        changes=list(changes)
    )

    return served(call, "\n".join([
        f"Every recorded change to {service} from {to_iso(start)} to {to_iso(end)}.",
        json.dumps([change.model_dump() for change in changes], indent=2)
        if changes
        else _NOTHING_IN_THIS_WINDOW
    ]), reading)
