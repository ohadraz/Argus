"""A candidate explanation, and what Argus would actually do about it.

Named here rather than in either module that asks, because both do: the walk
asks it to skip a candidate this incident has already answered, and long-term
memory asks it to demote one an earlier incident answered and was no better
for. One question, so one type.
"""

from __future__ import annotations

from pydantic import BaseModel

from argus_core.models.action import ActionIdentity
from argus_core.models.hypothesis import Hypothesis


class WhatWouldBeTried(BaseModel):
    """One candidate, beside the identity of the action that answers it.

    The pair rather than the candidate alone, because a candidate is prose and
    what it is compared against is not. `WhatWasTried` is the record of an
    action; this is the same shape before the fact, and putting the two in the
    same vocabulary is the whole reason either can be matched against the
    other. Compared as candidates, a restart was never comparable at all - the
    model's words for a leak are not the name of a service, and no two
    incidents write them the same way.

    `identity` is `None` where nothing would be done: no strategy answers the
    cause, or the one that does found nothing to act on. That is not a
    candidate that was tried before - it is one that cannot be tried now - so
    nothing matches it and nothing demotes it. The walk still offers it, and
    the gate still refuses it, which is where an unanswerable candidate has
    always been accounted for.
    """

    candidate: Hypothesis
    identity: ActionIdentity | None
