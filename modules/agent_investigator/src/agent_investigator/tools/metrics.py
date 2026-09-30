"""The metrics channel: the per-minute buckets the onset was located in.

The one channel that takes no window. The span is the metrics tool's own
(spec §16) and is already wider than any log window the model may ask for, so
there is nothing here for it to name - and nothing to get wrong, which is why
this channel's only refusal is of a second identical read.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Final

from argus_core.events import MetricsRetrieved, Narrator, RetrievalRequested
from argus_core.models import Reading, RetrievalChannel, ToolCall, ToolDefinition

from agent_investigator.retrieval import MetricsFetcher
from agent_investigator.tools.results import (
    Served,
    could_not_be_read,
    could_not_serve,
    served,
    was_already_read,
)

METRICS_TOOL: Final = "get_metrics"


def metrics_tool() -> ToolDefinition:
    """The offer: re-read the minutes the onset was measured from."""
    return ToolDefinition(
        name=METRICS_TOOL,
        description=(
            "Per-minute error rate, latency and request volume for the service, over "
            "the fixed span around the alert. The onset you were given was located "
            "from this. Takes no window: the span is one the metrics source decides, "
            "and it is already wider than any log window you may ask for."
        ),
        properties={},
        required=[]
    )


def read_metrics(call: ToolCall,
                 alert_time: str | None,
                 fetch_metrics: MetricsFetcher,
                 already_read: Sequence[Reading],
                 narrator: Narrator) -> Served:
    """The buckets, anchored on the alert as they always are.

    Rendered as JSON rather than prose because they are already structured, and
    re-describing them in sentences would lose the per-minute alignment that
    makes an onset visible.

    A second identical read is refused like any other: the span is fixed, so
    asking again returns the same four numbers a minute at the same cost.
    """
    reading = Reading(RetrievalChannel.METRICS, window_start=alert_time)
    if was_already_read(reading, already_read):
        return could_not_serve(call, (
            "you already read the metrics in this investigation. The span is fixed, so "
            "asking again returns the same minutes. Read another channel, or answer "
            "from what you have."
        ))

    narrator.say(RetrievalRequested, channel=RetrievalChannel.METRICS, window_start=alert_time)

    try:
        buckets = fetch_metrics(alert_time)
    except Exception as error:
        # Reported rather than raised, exactly as the other channels report it,
        # and this one was the exception among them. A read that fails here
        # leaves the model mid-conversation with turns left and every minute it
        # has already retrieved still paid for - so letting it out ends the walk
        # over the one kind of failure that says nothing about the incident at
        # all. The same read failing before the conversation is already handled
        # this way, and treating it as fatal only once a model is listening is
        # the expensive way round.
        #
        # Said as a failure to read rather than as an empty window, because a
        # channel that answered with no minutes is a finding about the service
        # and this is the absence of one - opposite claims that would otherwise
        # arrive identically.
        return could_not_be_read(
            call,
            (f"the metrics could not be read, so nothing here says what the "
             f"service's per-minute figures were - it is not that the window was "
             f"empty: {error}"),
            what_was_asked="the service's metrics",
            because=str(error)
        )

    narrator.say(
        MetricsRetrieved,
        window_start=buckets[0].bucket_id if buckets else None,
        window_end=buckets[-1].bucket_id if buckets else None,
        buckets=list(buckets)
    )

    return served(
        call, json.dumps([bucket.model_dump() for bucket in buckets], indent=2), reading
    )
