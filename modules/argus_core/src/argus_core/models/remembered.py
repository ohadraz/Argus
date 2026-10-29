"""What an earlier incident tried, as a later one is told it.

A contract because two parties name it: long-term memory files it and reads it
back, and the walk says it on the line that reports a recall - what the earlier
incident did is the one thing about it a reader of this one can act on.
"""

from __future__ import annotations

from pydantic import BaseModel

from argus_core.models.action import ActionIdentity, Verdict


class WhatWasTried(BaseModel):
    """One action Argus took, and what taking it turned out to be worth.

    The action's identity rather than the subject alone, because the subject
    alone is only half of what was done. A flag reverted and a service
    restarted are different experiments, and a later incident told that
    "checkout" was tried and did not help learns nothing it can act on - it
    has to know which thing was done to it. The pair is also what the record
    is compared against: the walk asks what it would do about a candidate and
    matches the answer here, and a match on half a key is a match that is
    sometimes right.

    Only a reached verdict is expressible here. `Verdict` also spells the two
    ways no verdict was reached - an action that could not be performed, and one
    abandoned mid-measurement - and a record carrying either would say a subject
    was tried and failed when it was never tested. What is dropped is dropped
    when the record is composed, so nothing downstream has to remember the
    distinction.
    """

    identity: ActionIdentity
    verdict: Verdict


class RecalledIncident(BaseModel):
    """An earlier incident memory found, and what it had tried when it was
    read.

    What it tried rather than what it was about: a recall that names an
    incident and says nothing of it sends a reader off to look it up, and the
    thing they would find there - an action, and whether it helped - is what
    this incident can use.

    `tried` may be empty in the type. A record is filed only for an incident
    that tried something, but the line saying a recall is read back from rows
    wherever a timeline is rendered, and a row is no place to find that rule
    broken.
    """

    incident_id: str
    tried: list[WhatWasTried]
