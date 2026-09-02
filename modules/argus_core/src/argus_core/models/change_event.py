from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel


class ChangeKind(StrEnum):
    """What sort of change an event records.

    A closed set for the same reason `CauseType` is one: a model weighing a
    deploy against a flag flip needs them to be distinct values it can reason
    about, not free text that happens to differ.

    Two members, from the two systems that record a change to what a service
    does. They stay separate rather than collapsing into "something changed"
    because what follows differs: a flag toggle has a reversible action behind
    it and a deploy does not, and the model is asked to weigh one against the
    other.
    """

    DEPLOY = "deploy"
    FLAG_TOGGLE = "flag-toggle"


class ChangeEvent(BaseModel):
    """Something that changed on the service, as Argus sees it (spec §16).

    The third retrieval channel's model, beside `MetricBucket` and the raw log
    line. Metrics say *when* an incident started and logs say what the service
    said about it; this says *what changed* - which is what a cause actually
    is. The lag between a change and the symptoms it produces is unbounded, so
    these are retrieved over their own much wider window: changes are sparse
    where log lines are not.

    Vendor-neutral by construction. Argo, a flag provider's audit log and a
    CI system all describe a change differently, and each gets an adapter that
    maps its shape onto this one - so nothing above the retrieval boundary
    knows which system reported what. That mapping is deterministic code, never
    a model: a hallucinated deploy is a fabricated cause.

    `occurred_at` is an ISO-8601 wire-format string rather than a `datetime`,
    matching `MetricBucket.bucket_id` - it gets compared against the onset and
    quoted into a prompt, and both want the string the rest of the system
    already speaks.
    """

    kind: ChangeKind
    occurred_at: str
    reference: str
    summary: str
    # Absent whenever the reporting source does not say. A change no one is
    # named for is still a real change; dropping it for want of a name would
    # lose the evidence.
    actor: str | None = None
    source: str | None = None
