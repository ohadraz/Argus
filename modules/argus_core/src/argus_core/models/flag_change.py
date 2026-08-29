from __future__ import annotations

from pydantic import BaseModel


class FlagChange(BaseModel):
    """One recorded change to a feature flag's state (spec §7.3).

    What the flag provider says happened, mapped off its own wire shape - the
    same vendor-neutrality `ChangeEvent` has, for the same reason: Unleash,
    LaunchDarkly and a home-grown toggle service each describe a toggle
    differently, and nothing above the retrieval boundary should know which
    one answered.

    Distinct from `ChangeEvent` rather than a `ChangeKind` of it, because the
    two are read for different purposes. A `ChangeEvent` is evidence put to a
    model, so it carries prose; this is read by code that has to *act* on it,
    so it carries the two facts an action needs and cannot be got from prose:
    which flag, and which way it moved.

    `enabled` is the state the flag was changed **to**, not the state it was
    in before. Undoing the change is therefore setting it to `not enabled`,
    and that is the one direction-agnostic statement of what mitigation does.

    `occurred_at` is an ISO-8601 wire-format string, matching
    `MetricBucket.bucket_id` and `ChangeEvent.occurred_at` - it gets compared
    against an onset, and wants the string the rest of the system speaks.
    """

    flag: str
    enabled: bool
    occurred_at: str
    # Who the provider attributes the change to. Absent when it does not say.
    # Not yet load-bearing: Argus authenticates with the same admin credential
    # a human would, so this cannot presently tell its own revert from theirs.
    actor: str | None = None
