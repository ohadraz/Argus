"""How an incident broke, as a closed set of patterns.

A failure mode is *how* it broke; a root cause is *why* - the technical
trigger. "A deploy went out and the service got worse" is a mode, where "the
divisor was zero for shoppers who bought nothing this month" is a cause. The
distinction is the published taxonomy's, and it decides what belongs here:
these are modes because a mitigation answers the pattern rather than the
trigger, and restarting is the answer to a leak whatever leaked.

What makes a mode is a distinction a reader of an incident makes, never the
strategy that answers it. The mapping from modes to mitigations is many-to-one -
a bad deployment and a broken configuration are both answered by returning the
deployment to the revision it ran before - and a value that had to earn its
place by bringing a new action with it would be a vocabulary serving the
dispatch table instead of the person reading the incident. The granularity below
follows from the same test: a heap and a pool are not distinct to that reader,
so they are one mode.

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
    # The other half of resource exhaustion: the resource was sized correctly and
    # the load outgrew it. One mode and not one with the leak above, because the
    # split is by what the correct response is - reclaim what accumulated, or add
    # capacity that was never there - and that is exactly the level a mode is
    # named at. It is also the pair a system without the distinction gets wrong:
    # the two are the same shape on a latency graph, and a restart makes this one
    # briefly better before it returns.
    DEMAND_SATURATION = "demand-saturation"
    # The capacity is not wrong, it will not settle: a controller adds replicas,
    # sees the load it just relieved, takes them away again, and the service is a
    # different size every few minutes. Not one mode with the saturation above,
    # though the two are the same family and read the same at the bottom of every
    # cycle - there a fixed capacity was outgrown, here the capacity moves, and
    # the split is by response as the leak's is: add capacity that was never
    # there, or stop the thing that keeps taking it away. Answering one with the
    # other's action is worse than doing nothing, because a count set by hand
    # under a live controller is a count the controller reclaims - so the
    # mitigation appears to work and then is undone, which is the one outcome that
    # costs a responder the time they spent watching it.
    #
    # The fault is a control loop rather than a resource, a revision or a value,
    # and it is the first mode in this set of which that is true. What is left to
    # fix afterwards is neither code nor a count but the loop's own terms - a
    # stabilisation window, a target, a pair of bounds.
    AUTOSCALING_PATHOLOGY = "autoscaling-pathology"
    # A service this one depends on and does not own stopped answering, and the
    # failure arrived here. The one mode in the set that no mitigation answers,
    # which is not an omission: everything Argus may do reaches its own
    # deployment, and nothing it can revert or restart reaches somebody else's
    # outage. Named for the propagation rather than for what the dependency is
    # - a payment provider, a queue, an identity service are one pattern, and
    # the pattern is what decides the response: say what happened, and hand it
    # to a person who can call them.
    UPSTREAM_DEPENDENCY_FAILURE = "upstream-dependency-failure"
    # The same propagation with the dependency on this side of the company
    # boundary: a service the same organisation runs, which nobody remembered
    # was on the request path, and which is now slow or failing. The alerting
    # service is well, so the mitigation is aimed at a service Argus was not
    # paged about - and that is the whole of what separates this from the mode
    # above, because the two are identical in every signal either one produces.
    # Whose the failing service is is not a fact any telemetry carries: it lives
    # in the organisation's own register, and a host name that looks internal
    # looks that way because somebody chose the spelling.
    INTERNAL_DEPENDENCY_FAILURE = "internal-dependency-failure"
    # A deployment's configuration was changed into a broken state, with
    # nothing wrong in the code and nothing wrong in whatever the
    # configuration points at. Distinct from a flag toggle, which is answered by
    # putting one value back through a provider built for it, and distinct from
    # a bad deployment in what it tells a reader and in what is left to fix
    # afterwards - a values file here, the service's source there - though a
    # deployment rollback answers both, since one revision carries the code and
    # the configuration it shipped with.
    CONFIG_INDUCED_FAILURE = "config-induced-failure"
    # A deployment landed and stopped part way, so the service is running as two
    # versions at once and the requests that cross between them fail. Not one
    # mode with the bad deployment above, though the two arrive identically - a
    # single deploy entry at the onset - and are answered identically, by
    # returning the deployment. There the revision carried the fault and going
    # back removes it; here neither revision is faulty and going back *converges*
    # the fleet, which is a different thing that the same call happens to do.
    #
    # The one mode in this set with no culprit commit, which is why it earns a
    # value despite bringing no action with it. A reader who calls it a bad
    # deployment takes the right action and writes a false record: a revision
    # named as the fault, a fix filed against code with no defect in it, and
    # nothing said about the rollout that was left half-done - which is the only
    # thing that will happen again.
    #
    # What is left to fix afterwards is neither code nor configuration but an
    # order of operations: a version that could read both shapes had to ship
    # before one that wrote only the new shape.
    IN_FLIGHT_COMPATIBILITY_BREAK = "in-flight-compatibility-break"

    def meaning(self) -> str:
        """What this mode is, in the words the model weighing it reads.

        Here rather than in the tool that offers the list, because the taxonomy
        has one home and a second copy of it beside the schema is a copy that
        comes to disagree with the comments above - which are what a person
        maintaining the set reads.

        One sentence each, and every mode that is hard to tell from a neighbour
        says what separates it. A model handed a list of hyphenated names infers a
        taxonomy from the spelling, and the pairs it confuses are the ones that
        arrive the same way: a bad deployment, a broken configuration value and a
        rollout that stopped half-way are one deployment at the onset each, and
        all three are mitigated by returning it - so what the model is being asked
        is which of them the change was, because that is what somebody has left to
        fix and what the incident will say it was about.
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
        "worse; the fault is in the code that was released. Choose this over "
        "in-flight-compatibility-break only once the rollout has converged - "
        "every replica on the revision that landed. The two arrive the same way, "
        "as one deployment at the onset, and are answered the same way, so the "
        "deploy history cannot separate them: it records that a revision was "
        "deployed and never whether that revision finished arriving"
    ),
    FailureMode.RESOURCE_LEAK: (
        "consumption climbs while traffic does not - a heap never released, a "
        "pool never returned, a disk filling - so the service degrades the "
        "longer the process runs. Choose this over demand-saturation when the "
        "traffic is where it always was: both are a resource running out and "
        "they look alike in the latency, and what separates them is whether "
        "the consumption moved with the traffic or on its own"
    ),
    FailureMode.DEMAND_SATURATION: (
        "the resource was sized correctly and the load outgrew it - the "
        "requests arriving are several times what the deployment was built "
        "for, so every one of them queues for capacity that is already busy. "
        "Choose this over resource-leak when the traffic climbed with the "
        "consumption rather than the consumption climbing on its own, which is "
        "the whole of what separates the pair - restarting answers a leak and "
        "does nothing here, because demand and capacity are both left where "
        "they were. Choose it over bad-deployment and over the two dependency "
        "modes when nothing changed and nothing was deployed, and the time is "
        "spent in this service's own work rather than waiting on somebody "
        "else's. Choose it over autoscaling-pathology when cpu_limit_cores holds "
        "one value across the whole window: capacity that was outgrown sits "
        "still while the demand climbs past it, where capacity that will not "
        "settle moves"
    ),
    FailureMode.AUTOSCALING_PATHOLOGY: (
        "the capacity is not wrong, it will not settle - a controller adds "
        "replicas, sees the load it has just relieved, takes them away again, "
        "and the deployment is a different size every few minutes, so the "
        "service is starved in some minutes and comfortable in others. "
        "cpu_limit_cores takes more than one value across the window, and that "
        "is what separates this from demand-saturation: at the bottom of every "
        "cycle the two are identical in the alert, the latency, the traffic and "
        "the change channels, so read that series rather than judging between "
        "them. What answers this is stopping the controller from scaling back "
        "down; setting a replica count directly is undone within a minute or "
        "two, because the controller reclaims what it did not ask for"
    ),
    FailureMode.UPSTREAM_DEPENDENCY_FAILURE: (
        "a service this one depends on stopped answering and the failure "
        "arrived here through that dependency, and the organisation running "
        "the alerting service does not own it - so nobody here can restart or "
        "revert anything that reaches it. Choose this over "
        "internal-dependency-failure only once the service register says the "
        "failing dependency belongs to another company: the evidence for the "
        "two is identical, and a host name is not evidence of who owns it"
    ),
    FailureMode.INTERNAL_DEPENDENCY_FAILURE: (
        "a service this one depends on and the same organisation *does* own is "
        "slow or failing, and the failure arrived here through it; the "
        "alerting service itself is healthy and its own code, configuration "
        "and deployment are all unchanged. Choose this over "
        "upstream-dependency-failure when the service register says the "
        "failing dependency is the organisation's own, and over bad-deployment "
        "when the request time is spent waiting on that dependency rather than "
        "in this service's own work"
    ),
    FailureMode.CONFIG_INDUCED_FAILURE: (
        "a deployment changed a configuration value into a broken one - an "
        "endpoint, port, limit or credential - while the source code is "
        "untouched and the thing the configuration points at is healthy. "
        "Choose this over bad-deployment whenever the change that landed was "
        "to configuration rather than to code, even though it arrived as a "
        "deployment and is put right the same way: what differs is the fix "
        "somebody is left with, a values file rather than the source. Which of "
        "the two landed is what the deployment changed, which is retrievable - "
        "read it rather than inferring it. The path a deployment shipped from is "
        "not the answer: that is where its manifests live, and it is the same "
        "directory whatever the commit touched"
    ),
    FailureMode.IN_FLIGHT_COMPATIBILITY_BREAK: (
        "a deployment landed and stopped part way, so two versions of the "
        "service are serving at once and the requests that cross between them "
        "fail - neither revision is faulty on its own, and each one alone would "
        "work. Choose this over bad-deployment when the rollout has not "
        "converged: replicas split across two revisions, or a rolling update "
        "reported as paused. That is a fact about the deployment rather than "
        "about the code it carried, it is retrievable, and the deploy history "
        "does not carry it - read the rollout rather than inferring from the "
        "entry. Choose it over feature-flag-toggle when no flag moved, because "
        "the metrics here are a flag toggle's exactly: an error rate that steps "
        "while every quantile stays flat. What answers it is getting the fleet "
        "onto one revision, which returning the deployment does; what is left "
        "to fix is the migration that changed a stored shape with no version "
        "able to read both"
    )
}
