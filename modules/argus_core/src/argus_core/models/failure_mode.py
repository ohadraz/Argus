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
    # A service this one depends on and does not own stopped answering, and the
    # failure arrived here. The one mode in the set that no mitigation answers,
    # which is not an omission: everything Argus may do reaches its own
    # deployment, and nothing it can revert or restart reaches somebody else's
    # outage. Named for the propagation rather than for what the dependency is
    # - a payment provider, a queue, an identity service are one pattern, and
    # the pattern is what decides the response: say what happened, and hand it
    # to a person who can call them.
    UPSTREAM_DEPENDENCY_FAILURE = "upstream-dependency-failure"
    # A deployment's configuration was changed into a broken state, with
    # nothing wrong in the code and nothing wrong in whatever the
    # configuration points at. Distinct from a bad deployment, which ships new
    # code and is answered by rolling that code back, and from a flag toggle,
    # which is answered by putting one value back through a provider built for
    # it. This is answered by returning the deployment to a revision of its
    # configuration that was already running - a third action, and so a third
    # mode, because what dispatches on a mode is the choice of mitigation.
    CONFIG_INDUCED_FAILURE = "config-induced-failure"

    def meaning(self) -> str:
        """What this mode is, in the words the model weighing it reads.

        Here rather than in the tool that offers the list, because the taxonomy
        has one home and a second copy of it beside the schema is a copy that
        comes to disagree with the comments above - which are what a person
        maintaining the set reads.

        One sentence each, and the two that are hardest to tell apart say what
        separates them. A model handed five hyphenated names infers a taxonomy
        from the spelling, and the pair it most often confuses is exactly the
        pair that dispatches to different mitigations: a deployment that
        shipped bad code is rolled back as code, and a deployment that shipped
        a bad value is returned to a configuration revision that worked.
        """
        return _WHAT_EACH_MODE_MEANS[self]


# Model-facing, so worded for somebody reading evidence rather than for
# somebody maintaining the set: what was observed, and what would distinguish
# it from its nearest neighbour.
_WHAT_EACH_MODE_MEANS: dict[FailureMode, str] = {
    FailureMode.FEATURE_FLAG_TOGGLE: (
        "a feature flag was switched and the service got worse; the code and "
        "the configuration are both unchanged"
    ),
    FailureMode.BAD_DEPLOYMENT: (
        "a deployment shipped new or changed source code and the service got "
        "worse; the fault is in the code that was released"
    ),
    FailureMode.RESOURCE_LEAK: (
        "consumption climbs while traffic does not - a heap never released, a "
        "pool never returned, a disk filling - so the service degrades the "
        "longer the process runs"
    ),
    FailureMode.UPSTREAM_DEPENDENCY_FAILURE: (
        "a service this one depends on and does not own stopped answering, and "
        "the failure arrived here through that dependency"
    ),
    FailureMode.CONFIG_INDUCED_FAILURE: (
        "a deployment changed a configuration value into a broken one - an "
        "endpoint, port, limit or credential - while the source code is "
        "untouched and the thing the configuration points at is healthy. "
        "Choose this over bad-deployment whenever the change that landed was "
        "to configuration rather than to code, even though it arrived as a "
        "deployment: what puts it right is returning the deployment to an "
        "earlier configuration revision, not rolling back code"
    )
}
