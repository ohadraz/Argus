"""How an incident broke, as a closed set of patterns.

A failure mode is *how* it broke; a root cause is *why* - the technical
trigger. "A deploy went out and the service got worse" is a mode, where "the
divisor was zero for shoppers who bought nothing this month" is a cause. The
distinction is the published taxonomy's, and it decides what belongs here:
these are modes, because what dispatches on them is the choice of mitigation,
and a mitigation answers the pattern rather than the trigger. Restarting is the
answer to a leak whatever leaked.

Closed rather than open. A model weighing an explanation against a fixed list
is answering a question; one inventing a label is writing prose that something
downstream then has to parse - and the thing downstream is a mapping from mode
to action, which a spelling nobody registered silently falls out of.

`docs/failure-modes-backlog.md` holds the taxonomy these come from, which modes
exist in the world, and which are worth adding next.
"""

from __future__ import annotations

from enum import StrEnum


class FailureMode(StrEnum):
    FEATURE_FLAG_TOGGLE = "feature-flag-toggle"
    BAD_DEPLOYMENT = "bad-deployment"
    # Consumption that grows without the traffic growing - a heap never
    # released, a pool never returned, a queue nobody drains, a disk filling
    # with logs. Named at this level and not two others: `resource-exhaustion`
    # would also cover a correctly-sized resource meeting more load, which
    # wants scaling out rather than restarting and looks identical on a latency
    # graph; `memory-leak` would be one value per resource, each mapping to the
    # same restart.
    RESOURCE_LEAK = "resource-leak"
