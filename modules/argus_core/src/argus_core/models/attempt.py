from __future__ import annotations

from pydantic import BaseModel

from argus_core.models.action import ActionIdentity


class Attempt(BaseModel):
    """A mitigation already taken for this incident, and undone again.

    Only failures are worth recording here: a mitigation that worked ended the
    incident, and there is no later round to tell about it. So an attempt on
    this list is by definition one that changed production and did not help -
    which is why the type carries no outcome field. Adding one would invite a
    caller to record a success nothing would ever read.

    `identity` says what was done as well as where, and says them as one value.
    A later round told that a subject "was tried" cannot tell a flag put back
    from a service restarted, and those are different evidence about the same
    cause - a restart that did not help says the accumulation was not the
    problem, where a flag put back says the toggle was not. The pair is the
    same one the gate counts and the same one memory looks a candidate up by,
    so it is the type those readers share rather than two fields each unpacks.

    It exists to be shown to the model. A second investigation differs from the
    first in two ways, and this is the more valuable one: the window may reach
    further back, but *this* is evidence the model has never seen and cannot
    infer - a named cause was acted on and the service stayed broken.

    `enabled` is the state the flag was set **to** by the attempt, not the
    state it was in before. Both directions happen - a feature flag is put back
    by switching it off, a withdrawn fallback by switching it on - and a model
    told only that something "changed" cannot say which state is now in effect.

    It is absent for an attempt that had no direction to go in. A restart is
    one thing done to one service, and reporting it as having been moved to
    `true` would tell a later round that a switch was thrown - which is a
    different attempt from the one that was made, and a worse lie than saying
    nothing, because the model would reason about the switch.

    `occurred_at` is an ISO-8601 wire-format string, matching
    `FlagChange.occurred_at` and `MetricBucket.bucket_id`: it is read beside
    them, and a second time format would be one more thing to get wrong.
    """

    identity: ActionIdentity
    enabled: bool | None = None
    occurred_at: str
