from __future__ import annotations

from pydantic import BaseModel


class Attempt(BaseModel):
    """A mitigation already taken for this incident, and undone again.

    Only failures are worth recording here: a mitigation that worked ended the
    incident, and there is no later round to tell about it. So an attempt on
    this list is by definition one that changed production and did not help -
    which is why the type carries no outcome field. Adding one would invite a
    caller to record a success nothing would ever read.

    It exists to be shown to the model. A second investigation differs from the
    first in two ways, and this is the more valuable one: the window may reach
    further back, but *this* is evidence the model has never seen and cannot
    infer - a named cause was acted on and the service stayed broken.

    `enabled` is the state the flag was set **to** by the attempt, not the
    state it was in before. Both directions happen - a feature flag is put back
    by switching it off, a withdrawn fallback by switching it on - and a model
    told only that something "changed" cannot say which state is now in effect.

    `occurred_at` is an ISO-8601 wire-format string, matching
    `FlagChange.occurred_at` and `MetricBucket.bucket_id`: it is read beside
    them, and a second time format would be one more thing to get wrong.
    """

    subject: str
    enabled: bool
    occurred_at: str
