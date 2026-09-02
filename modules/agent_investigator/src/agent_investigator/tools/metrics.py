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

from argus_core.events import MetricsRetrieved, Narrator, RetrievalChannel, RetrievalRequested
from argus_core.models.reading import Reading
from argus_core.models.tool_definition import ToolDefinition
from argus_core.models.turn import ToolCall

from agent_investigator.retrieval import MetricsFetcher
from agent_investigator.tools.results import Served, could_not_serve, served, was_already_read

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
    buckets = fetch_metrics(alert_time)
    narrator.say(
        MetricsRetrieved,
        window_start=buckets[0].bucket_id if buckets else None,
        window_end=buckets[-1].bucket_id if buckets else None,
        buckets=list(buckets)
    )

    return served(
        call, json.dumps([bucket.model_dump() for bucket in buckets], indent=2), reading
    )
