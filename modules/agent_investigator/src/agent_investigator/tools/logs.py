"""The log channel: what the service itself said, over one window.

The expensive channel, and the only one with a ceiling. A window wider than
the maximum is clamped at its start rather than its end, because the tail is
the half certainly inside the incident - and the clamp is said out loud, since
a model that asked for three hours, silently got one, and found nothing would
read the absence of evidence as evidence of absence.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import timedelta
from typing import Final

from argus_core.config import get_settings
from argus_core.events import LogsRetrieved, Narrator, RetrievalChannel, RetrievalRequested
from argus_core.models.reading import Reading
from argus_core.models.tool_definition import ToolDefinition
from argus_core.models.turn import ToolCall
from argus_core.timestamps import parse_iso, to_iso

from agent_investigator.retrieval import LogFetcher
from agent_investigator.tools.results import Served, could_not_serve, served, was_already_read
from agent_investigator.tools.windows import window_of, window_properties

LOGS_TOOL: Final = "get_logs"

_NOTHING_IN_THIS_WINDOW = "(no log lines in this window)"


def logs_tool() -> ToolDefinition:
    """The offer: read the service's own account of one window."""
    return ToolDefinition(
        name=LOGS_TOOL,
        description=(
            "The service's log lines over one window. This is the expensive channel "
            "and the one that says what the service actually did. Defaults to a "
            "window that starts shortly before the onset and ends at the alert. A "
            "window wider than the maximum is clamped at its start, and you are told "
            "when that happened."
        ),
        properties=window_properties(),
        required=[]
    )


def read_logs(call: ToolCall,
              onset: str,
              alert_time: str | None,
              fetch_logs: LogFetcher,
              already_read: Sequence[Reading],
              narrator: Narrator) -> Served:
    """The log lines for the window the model named, or the default one.

    The default starts before the onset because that is where a cause lands -
    a flag flips in a minute that still looks healthy - and ends at the alert,
    which is the one moment the service is known to have been unhealthy. With
    no alert time to end at it runs a short way past the onset instead, which
    is the same window the loop read before the model had any say.
    """
    settings = get_settings()
    onset_at = parse_iso(onset)
    window = window_of(
        call,
        default_start=onset_at - timedelta(minutes=settings.log_initial_lookback_minutes),
        default_end=parse_iso(alert_time) if alert_time is not None
        else onset_at + timedelta(minutes=settings.log_initial_lookahead_minutes)
    )

    if isinstance(window, str):
        return could_not_serve(call, window)

    start, end = window
    earliest_affordable = end - timedelta(minutes=settings.log_max_window_minutes)
    was_clamped = start < earliest_affordable
    start = max(start, earliest_affordable)

    reading = Reading(RetrievalChannel.LOGS, to_iso(start), to_iso(end))
    if was_already_read(reading, already_read):
        return could_not_serve(call, (
            f"you already read the log lines for {reading} in this investigation, and "
            f"nothing further would come back. Ask for a window you have not read, or "
            f"answer from what you have."
        ))

    narrator.say(
        RetrievalRequested,
        channel=RetrievalChannel.LOGS,
        window_start=to_iso(start),
        window_end=to_iso(end)
    )
    lines = fetch_logs(to_iso(start), to_iso(end))
    narrator.say(
        LogsRetrieved,
        window_start=to_iso(start),
        window_end=to_iso(end),
        lines=list(lines)
    )
    said = [
        f"Log lines from {to_iso(start)} to {to_iso(end)}.",
        *(lines or [_NOTHING_IN_THIS_WINDOW])
    ]

    if was_clamped:
        said.insert(0, (
            f"The window you asked for was wider than the maximum of "
            f"{settings.log_max_window_minutes} minutes, so it was clamped at its "
            f"start. What follows is the last {settings.log_max_window_minutes} "
            f"minutes of it, and nothing before that."
        ))

    return served(call, "\n".join(said), reading)
