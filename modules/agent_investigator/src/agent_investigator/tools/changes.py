"""The change channel: what changed on the service, over its own wide window.

No ceiling, deliberately. The log ceiling exists because log lines are
millions where changes are a handful, and applying it here would silence the
one channel that exists to reach past it - the lag between a change and the
symptoms it produces is unbounded.

A source that cannot be reached raises, and is meant to - it is answered here
rather than passed on. What the raising is for is a distinction, not an exit:
"nothing changed" is a conclusion something acts on, so a source that was never
read must not arrive looking like one that was read and found empty. A result
saying which of the two it is keeps that whole, and keeps the turns the model
has left to spend on another channel.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import timedelta
from typing import Final

from argus_core import parse_iso, to_iso
from argus_core.events import ChangesRetrieved, Narrator, RetrievalRequested
from argus_core.models import Reading, RetrievalChannel, ToolCall, ToolDefinition

from agent_investigator.budget import InvestigationSettings
from agent_investigator.retrieval import ChangeFetcher
from agent_investigator.tools.results import (
    Served,
    could_not_be_read,
    could_not_serve,
    served,
    was_already_read,
)
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
            "change made after the incident began did not begin it - or at the alert "
            "where no reading covers the incident's minutes, since what ended the "
            "readings lies at or after the last one."
        ),
        properties=window_properties(),
        required=[]
    )


def read_changes(call: ToolCall,
                 service: str,
                 onset: str,
                 alert_time: str | None,
                 readings_cover_the_incident: bool,
                 fetch_change_events: ChangeFetcher,
                 already_read: Sequence[Reading],
                 narrator: Narrator,
                 settings: InvestigationSettings) -> Served:
    """The changes on the service over the window the model named, or the
    default one.

    The default ends at the onset: a change made after the incident began did
    not begin it, and offering later ones invites attribution by mere
    proximity - which is the one mistake this channel is most likely to
    produce. It reaches back by the configured lookback rather than by anything
    the log window uses, because how far back a cause may plausibly lie is the
    operator's judgement, not something inferable from the metrics.

    Where no reading covers the incident's own minutes it ends at the alert
    instead. An onset dated off a window that stops is the last reading before
    the evidence ran out, which bounds when the incident began from below rather
    than naming it - and what ended the readings is the change, so the change
    lies at or after that reading. Ending at the onset there would exclude, by
    construction, the only change that could explain the incident, and this
    channel would come back empty on the one incident whose whole evidence is
    that the readings stop. The alert is the bound that still holds: nothing
    after it began something it already reports.

    Asked as whether the minutes were *read* rather than whether the onset was
    measured, because those differ on the incident this distinction exists
    beside. A weekly integrity check states an onset nothing measured either,
    and states it about minutes the window covers perfectly well - so its onset
    is testimony about when the fault began, the window it names is an hour
    rather than a week, and moving its end to the alert would ask what changed
    during the discovery instead of during the fault.
    """
    onset_at = parse_iso(onset)
    # The alert is the ceiling only where there is one to use. An alert that
    # never said when it fired leaves the onset as the only instant there is,
    # and a window ending nowhere is not an improvement on one ending early.
    the_incident_could_have_begun_until = (
        parse_iso(alert_time)
        if not readings_cover_the_incident and alert_time is not None
        else onset_at
    )
    window = window_of(
        call,
        default_start=onset_at - timedelta(minutes=settings.change_lookback_minutes),
        default_end=the_incident_could_have_begun_until
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
    try:
        changes = fetch_change_events(service, to_iso(start), to_iso(end))
    except Exception as error:
        # The source raises rather than answering emptily, and this is where that
        # lands. What the raising is for is the distinction below: "nothing
        # changed" is a conclusion something acts on, so a window nobody could
        # ask about must never arrive looking like a window with nothing in it -
        # and the text says which of the two this is, in as many words.
        #
        # Reported rather than passed on, though. Letting it through was a
        # stronger claim than the one the raising makes: it ended the
        # investigation, threw away every minute already paid for, and left
        # nothing on the page saying why. The distinction survives a failed
        # result; the investigation does not survive an exception.
        return could_not_be_read(
            call,
            (f"the changes to {service} from {to_iso(start)} to {to_iso(end)} "
             f"could not be read, so nothing here says what changed over that "
             f"window - it is not that nothing did: {error}"),
            what_was_asked=f"what changed on {service}",
            because=str(error)
        )

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
