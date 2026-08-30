from __future__ import annotations

from pydantic import BaseModel

from argus_core.ids import UuidStr
from argus_core.models.alert import Alert
from argus_core.models.attempt import Attempt
from argus_core.models.change_event import ChangeEvent
from argus_core.models.metrics import MetricBucket


class Evidence(BaseModel):
    """Everything one investigation iteration retrieved, as the reasoner sees it.

    The input side of the LLM seam, and the reason that seam is
    `propose_hypothesis(evidence)` rather than `complete(prompt)`: what the
    Investigator has is evidence, and turning evidence into wording is the
    adapter's job, not the caller's. A caller that passed a prompt string
    would be deciding how to talk to a model it should know nothing about.

    The retrieval fields mirror the three channels - the alert that started it,
    the per-minute buckets that locate the onset, the log lines from the window
    anchored on that onset, and the changes made to the service over a window
    far wider than either.

    `change_events` is what makes a cause *findable* rather than merely
    describable: a deploy or a flag flip can precede the symptoms it causes by
    an unbounded lag, so no log window is reliably wide enough to contain it.
    It defaults to empty so that evidence gathered before the change channel
    existed - a recording, an eval fixture - still constructs.

    `log_window_start`/`log_window_end` are ISO-8601 strings, matching the MCP
    tool that produced the lines. They are carried rather than inferred
    because a model told "these logs cover 10:02 to 10:42" can say *the cause
    is outside this window*; a model handed bare lines can only guess whether
    silence means nothing happened or nothing was fetched.

    `change_window_start`/`change_window_end` do the same job for the third
    channel, and matter more there. An empty log window means "the service
    said nothing", which is ordinary; an empty change window means "nothing
    changed", which is a conclusion. Neither claim is worth anything unless
    the interval it is about is stated - a complete list of changes over an
    unnamed window is not a fact a reader can use.

    `attempts` is what has already been tried for this incident and did not
    help. Empty for a first investigation, and the reason a later one is worth
    running at all: without it a second round is the same question over the
    same evidence, and a model that answered differently would be guessing
    rather than reasoning.

    `incident_id` rides along so the seam stays a one-argument function and
    the hypothesis that comes back is already attached to its incident. It is
    context, not evidence, and is deliberately kept out of the prompt - the
    model has no use for a UUID.
    """

    incident_id: UuidStr
    alert: Alert
    metric_buckets: list[MetricBucket]
    log_lines: list[str]
    change_events: list[ChangeEvent] = []
    attempts: list[Attempt] = []
    log_window_start: str | None = None
    log_window_end: str | None = None
    change_window_start: str | None = None
    change_window_end: str | None = None
