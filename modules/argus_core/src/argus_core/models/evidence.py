from __future__ import annotations

from pydantic import BaseModel

from argus_core.ids import UuidStr
from argus_core.models.alert import Alert
from argus_core.models.metrics import MetricBucket


class Evidence(BaseModel):
    """Everything one investigation iteration retrieved, as the reasoner sees it.

    The input side of the LLM seam, and the reason that seam is
    `propose_hypothesis(evidence)` rather than `complete(prompt)`: what the
    Investigator has is evidence, and turning evidence into wording is the
    adapter's job, not the caller's. A caller that passed a prompt string
    would be deciding how to talk to a model it should know nothing about.

    The three fields mirror two-phase retrieval - the alert that started it,
    the per-minute buckets that locate the onset, and the log lines from the
    window anchored on that onset.

    `log_window_start`/`log_window_end` are ISO-8601 strings, matching the MCP
    tool that produced the lines. They are carried rather than inferred
    because a model told "these logs cover 10:02 to 10:42" can say *the cause
    is outside this window*; a model handed bare lines can only guess whether
    silence means nothing happened or nothing was fetched.

    `incident_id` rides along so the seam stays a one-argument function and
    the hypothesis that comes back is already attached to its incident. It is
    context, not evidence, and is deliberately kept out of the prompt - the
    model has no use for a UUID.
    """

    incident_id: UuidStr
    alert: Alert
    metric_buckets: list[MetricBucket]
    log_lines: list[str]
    log_window_start: str | None = None
    log_window_end: str | None = None
